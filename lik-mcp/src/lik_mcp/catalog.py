from datetime import datetime
from typing import Optional

from psycopg.types.json import Json
from pydantic import BaseModel, ConfigDict, Field

from .db import Database


class SourceRef(BaseModel):
    """One entry in `source_refs`: a pointer to a DS record this Catalog row was derived
    from. `source_state` is an opaque content-state marker (a native change signal or a
    content hash, per source), compared by equality to detect drift. It is optional so a
    row that omits it deserializes without error; recency uses `catalog.updated_at`.
    Extra fields are forbidden so a caller still sending the removed `version` / `fetched_at`
    fails loudly at the contract boundary instead of having them silently dropped."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source_state: Optional[str] = None


class CatalogEntry(BaseModel):
    """A Catalog row. Discovery keys are (entry_type, subject); the rest follows the
    v0.4 schema. Defaults match the schema so a producer supplies only what it knows."""

    entry_type: str
    subject: str
    location: str
    store_kind: str
    locator: Optional[str] = None
    provenance: str = "ai-generated"
    verification: str = "unverified"
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    freshness: str = "current"
    source_refs: list[SourceRef] = Field(default_factory=list)
    last_computed_at: Optional[datetime] = None
    last_validated_at: Optional[datetime] = None
    access_groups: list[str] = Field(default_factory=list)
    sensitivity: str = "restricted"
    category: Optional[str] = None
    computed_by: str
    row_provenance: str = "skill"


class RegisterResult(BaseModel):
    status: str  # "inserted" | "updated"
    entry_type: str
    subject: str


class LookupResult(BaseModel):
    found: bool
    entry: Optional[dict] = None


class ListResult(BaseModel):
    count: int
    entries: list[dict] = Field(default_factory=list)


class SearchResult(BaseModel):
    """Ranked candidate rows from a partial/fuzzy search. Each entry carries a `score`
    (trigram similarity to the query, 0..1). Bounded by `limit` — never the full table."""

    count: int
    entries: list[dict] = Field(default_factory=list)


_UPSERT = """
INSERT INTO catalog (
    entry_type, subject, location, store_kind, locator, provenance, verification,
    verified_by, verified_at, freshness, source_refs, last_computed_at, last_validated_at,
    access_groups, sensitivity, category, computed_by, row_provenance, updated_by
) VALUES (
    %(entry_type)s, %(subject)s, %(location)s, %(store_kind)s, %(locator)s, %(provenance)s,
    %(verification)s, %(verified_by)s, %(verified_at)s, %(freshness)s, %(source_refs)s,
    %(last_computed_at)s, %(last_validated_at)s, %(access_groups)s, %(sensitivity)s,
    %(category)s, %(computed_by)s, %(row_provenance)s, %(updated_by)s
)
ON CONFLICT (entry_type, subject) DO UPDATE SET
    location = EXCLUDED.location, store_kind = EXCLUDED.store_kind, locator = EXCLUDED.locator,
    provenance = EXCLUDED.provenance, verification = EXCLUDED.verification,
    verified_by = EXCLUDED.verified_by, verified_at = EXCLUDED.verified_at,
    freshness = EXCLUDED.freshness, source_refs = EXCLUDED.source_refs,
    last_computed_at = EXCLUDED.last_computed_at, last_validated_at = EXCLUDED.last_validated_at,
    access_groups = EXCLUDED.access_groups, sensitivity = EXCLUDED.sensitivity,
    category = EXCLUDED.category, computed_by = EXCLUDED.computed_by,
    row_provenance = EXCLUDED.row_provenance, updated_by = EXCLUDED.updated_by,
    updated_at = now()
RETURNING (xmax::text::bigint = 0) AS inserted
"""


def _serialize(row: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def register_catalog_entry(db: Database, entry: CatalogEntry, updated_by: str) -> RegisterResult:
    """Upsert a Catalog row on (entry_type, subject) — re-registering a key updates in place."""
    params = entry.model_dump()
    params["source_refs"] = Json([r.model_dump(mode="json") for r in entry.source_refs])
    params["updated_by"] = updated_by
    with db.connection() as conn:
        row = conn.execute(_UPSERT, params).fetchone()
        conn.commit()
    return RegisterResult(
        status="inserted" if row["inserted"] else "updated",
        entry_type=entry.entry_type,
        subject=entry.subject,
    )


def lookup_catalog_entry(db: Database, entry_type: str, subject: str) -> LookupResult:
    """Exact-match lookup on the discovery keys. A miss is a clean not-found, never an error."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM catalog WHERE entry_type = %s AND subject = %s",
            (entry_type, subject),
        ).fetchone()
    if row is None:
        return LookupResult(found=False)
    return LookupResult(found=True, entry=_serialize(row))


def list_catalog_entries(db: Database, entry_type: str) -> ListResult:
    """Return every Catalog row for one entry_type, ordered by subject. Bounded by the
    discovery key, not a free-form predicate — no row matches is a clean empty list."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM catalog WHERE entry_type = %s ORDER BY subject",
            (entry_type,),
        ).fetchall()
    entries = [_serialize(row) for row in rows]
    return ListResult(count=len(entries), entries=entries)


def search_catalog_entries(
    db: Database,
    entry_type: str,
    query: str,
    *,
    category: Optional[str] = None,
    limit: int = 10,
    min_similarity: float = 0.3,
) -> SearchResult:
    """Partial + fuzzy search on `subject` within one entry_type, returning the top
    `limit` rows ranked by word similarity (highest first). A row matches when its subject
    contains the query as a substring (ILIKE) OR the query is trigram-similar to some
    extent of the subject (`word_similarity` >= `min_similarity`, which catches typos and
    reordered words). `word_similarity` — not plain `similarity` — is used so a short query
    isn't diluted by a long subject (e.g. "Atals" still matches "Atlas Mapping Service"). The
    substring arm keeps partials that fall below the similarity floor. `category`, when
    given, is an exact-match pre-filter (it is not fuzzy-matched; note that index rows
    currently leave category NULL). An empty/whitespace query is a clean empty result (it
    must not degenerate into a match-all), and `limit` is clamped to a sane range so a
    caller can neither error nor pull an unbounded page. No match is a clean empty result,
    never an error — mirrors lookup/list. Like those, it applies no ACL filtering.

    The gin_trgm_ops index on `subject` accelerates the ILIKE arm; the word_similarity arm
    is computed over the entry_type-filtered subset (narrowed by the composite PK). Fine at
    thousands of rows; if a single entry_type grows much larger, switch to a GiST
    gist_trgm_ops index and the `<%` operator to index the fuzzy arm."""
    if not query.strip():
        return SearchResult(count=0)
    limit = max(1, min(limit, 50))
    # Escape LIKE metacharacters so a literal % or _ in the query isn't treated as a
    # wildcard — the substring arm should match the user's literal text, not over-match.
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    sql = [
        "SELECT *, word_similarity(%(query)s, subject) AS score FROM catalog",
        "WHERE entry_type = %(entry_type)s",
        "AND (subject ILIKE %(like)s ESCAPE '\\' OR word_similarity(%(query)s, subject) >= %(min)s)",
    ]
    params: dict = {
        "entry_type": entry_type,
        "query": query,
        "like": f"%{escaped}%",
        "min": min_similarity,
        "limit": limit,
    }
    if category is not None:
        sql.append("AND category = %(category)s")
        params["category"] = category
    sql.append("ORDER BY score DESC, subject LIMIT %(limit)s")
    with db.connection() as conn:
        rows = conn.execute("\n".join(sql), params).fetchall()
    entries = [_serialize(row) for row in rows]
    return SearchResult(count=len(entries), entries=entries)
