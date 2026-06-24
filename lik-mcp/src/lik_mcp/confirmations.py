from typing import Optional

from pydantic import BaseModel

from .citations import Citation, CitationResolver
from .db import Database


class ConfirmResult(BaseModel):
    status: str  # "recorded" | "duplicate" | "rejected"
    reason: Optional[str] = None


class ConfirmationsResult(BaseModel):
    count: int
    confirmations: list[dict]


_INSERT = """
INSERT INTO confirmations (store_kind, location, locator, version, confirmed_by)
VALUES (%(store_kind)s, %(location)s, %(locator)s, %(version)s, %(confirmed_by)s)
ON CONFLICT (confirmed_by, store_kind, location, locator, version) DO NOTHING
RETURNING id
"""

_SELECT = """
SELECT id, confirmed_by, version, created_at
FROM confirmations
WHERE store_kind = %(store_kind)s AND location = %(location)s
  AND locator = %(locator)s AND version = %(version)s AND archived_at IS NULL
ORDER BY created_at
"""


def confirm_source(
    db: Database, citation: Citation, confirmed_by: str, resolver: CitationResolver
) -> ConfirmResult:
    """Record a confirmation against a cited source-version. Rejects an unresolvable
    citation; dedupes to at most one per user per cited source-version."""
    if not resolver.resolve(citation):
        return ConfirmResult(status="rejected", reason="unresolvable_citation")
    params = {**citation.model_dump(), "confirmed_by": confirmed_by}
    with db.connection() as conn:
        row = conn.execute(_INSERT, params).fetchone()
        conn.commit()
    return ConfirmResult(status="recorded" if row else "duplicate")


def read_confirmations(db: Database, citation: Citation) -> ConfirmationsResult:
    """Return confirmations (and a count) for one cited source-version."""
    with db.connection() as conn:
        rows = conn.execute(_SELECT, citation.model_dump()).fetchall()
    confirmations = [
        {
            "id": r["id"],
            "confirmed_by": r["confirmed_by"],
            "version": r["version"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    return ConfirmationsResult(count=len(confirmations), confirmations=confirmations)
