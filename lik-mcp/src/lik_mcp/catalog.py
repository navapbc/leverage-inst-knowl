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
    store_kind: str  # how to fetch: gdoc | gsheet | confluence | postgres | bigquery
    locator: Optional[str] = None
    provenance: str = "ai-generated"  # how the content was produced: ai-generated | human-created
    verification: str = "unverified"
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    freshness: str = "current"
    # The DS records this row was derived from; a list so a row synthesized from
    # several sources can detect drift in any one independently. See SourceRef.
    source_refs: list[SourceRef] = Field(default_factory=list)
    last_computed_at: Optional[datetime] = None
    last_validated_at: Optional[datetime] = None
    # Propagated ACL hint — the output's single assigned audience group. Never trusted for enforcement.
    access_groups: list[str] = Field(default_factory=list)
    sensitivity: str = "restricted"  # restricted (default) | cleared
    category: Optional[str] = None  # descriptive classification; also an ACL-mapping input
    computed_by: str  # the skill that owns this row
    # which writer owns the row, so the skill re-derives only its own rows and leaves human ones alone
    row_provenance: str = "skill"  # skill | human


class RegisterResult(BaseModel):
    status: str  # "inserted" | "updated"
    id: int  # the surrogate row handle (stable across re-derivation)
    entry_type: str
    subject: str


class LookupResult(BaseModel):
    """Ranked Catalog rows for one (entry_type, subject). A key may resolve to several
    pointers — duplicates from independent human saves coexist (v0.4 §3, "Keys"). Rows come
    back best-first on what the Catalog holds: `human-verified` over `unverified`, fresher
    over staler, most-recently-updated as the tie-breaker. Confirmation-based boost/demotion
    is the consumer's job (the Query skill reads confirmations live), not applied here. The
    top row is the default entry point; a consumer that cares can weigh the rest. Empty = a
    clean miss (cache miss), never an error."""

    count: int
    entries: list[dict] = Field(default_factory=list)


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
ON CONFLICT (entry_type, subject, computed_by) WHERE row_provenance = 'skill' DO UPDATE SET
    location = EXCLUDED.location, store_kind = EXCLUDED.store_kind, locator = EXCLUDED.locator,
    provenance = EXCLUDED.provenance, verification = EXCLUDED.verification,
    verified_by = EXCLUDED.verified_by, verified_at = EXCLUDED.verified_at,
    freshness = EXCLUDED.freshness, source_refs = EXCLUDED.source_refs,
    last_computed_at = EXCLUDED.last_computed_at, last_validated_at = EXCLUDED.last_validated_at,
    access_groups = EXCLUDED.access_groups, sensitivity = EXCLUDED.sensitivity,
    category = EXCLUDED.category, computed_by = EXCLUDED.computed_by,
    row_provenance = EXCLUDED.row_provenance, updated_by = EXCLUDED.updated_by,
    updated_at = now()
RETURNING id, (xmax::text::bigint = 0) AS inserted
"""

# A key may hold several rows; return them ranked best-first on what the Catalog itself
# holds — human-verified first, then fresher, then most-recently-updated. Confirmation-based
# boost/demotion is deliberately NOT applied here: the Query skill owns it, reading
# confirmations live at present-time (v0.4 §3). Keeping lookup off the confirmations table
# leaves it servable from the catalog row alone.
_LOOKUP = """
SELECT * FROM catalog
WHERE entry_type = %s AND subject = %s
ORDER BY (verification = 'human-verified') DESC,
         CASE freshness WHEN 'current' THEN 0 WHEN 'stale' THEN 1 ELSE 2 END,
         updated_at DESC
"""


def _serialize(row: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def register_catalog_entry(db: Database, entry: CatalogEntry, updated_by: str) -> RegisterResult:
    """Register a Catalog row. A skill row upserts on (entry_type, subject, computed_by) —
    re-registering updates that skill's own row in place. A human row (row_provenance =
    'human') is exempt from the arbiter, so every save inserts a new pointer and duplicates
    on a key coexist as ranked rows; superseding one is a separate, deliberate write."""
    params = entry.model_dump()
    params["source_refs"] = Json([r.model_dump(mode="json") for r in entry.source_refs])
    params["updated_by"] = updated_by
    with db.connection() as conn:
        row = conn.execute(_UPSERT, params).fetchone()
        conn.commit()
    return RegisterResult(
        status="inserted" if row["inserted"] else "updated",
        id=row["id"],
        entry_type=entry.entry_type,
        subject=entry.subject,
    )


def lookup_catalog_entry(db: Database, entry_type: str, subject: str) -> LookupResult:
    """Resolve the discovery keys to all matching pointers, ranked best-first (see
    LookupResult). A miss is a clean empty result, never an error."""
    with db.connection() as conn:
        rows = conn.execute(_LOOKUP, (entry_type, subject)).fetchall()
    entries = [_serialize(row) for row in rows]
    return LookupResult(count=len(entries), entries=entries)


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
