from datetime import datetime
from typing import Optional

from psycopg.types.json import Json
from pydantic import BaseModel, Field

from .db import Database


class SourceRef(BaseModel):
    """One entry in `source_refs`: a pointer to a DS record this Catalog row was derived
    from. `version` is the store's own version identifier when available; `fetched_at` is
    an ISO 8601 timestamp recorded at sync time as a proxy when no version is available.
    Both are optional so legacy rows (missing either field) deserialize without error."""

    id: str
    version: Optional[str] = None
    fetched_at: Optional[str] = None


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
    isn't diluted by a long subject (e.g. "Atals" still matches "project: Atlas"). The
    substring arm keeps partials that fall below the similarity floor. `category`, when
    given, is an exact-match pre-filter (it is not fuzzy-matched; note that index rows
    currently leave category NULL). No match is a clean empty result, never an error —
    mirrors lookup/list. Like those, it applies no ACL filtering."""
    sql = [
        "SELECT *, word_similarity(%(query)s, subject) AS score FROM catalog",
        "WHERE entry_type = %(entry_type)s",
        "AND (subject ILIKE %(like)s OR word_similarity(%(query)s, subject) >= %(min)s)",
    ]
    params: dict = {
        "entry_type": entry_type,
        "query": query,
        "like": f"%{query}%",
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
