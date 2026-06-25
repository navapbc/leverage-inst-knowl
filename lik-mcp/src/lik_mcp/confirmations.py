from typing import Optional

from pydantic import BaseModel

from .citations import Citation, CitationResolver
from .db import Database


class ConfirmResult(BaseModel):
    status: str  # "recorded" | "rejected"
    reason: Optional[str] = None


class ConfirmationRow(BaseModel):
    """One row returned by read_confirmations. `source_state` is the opaque content-state
    marker the user vouched for; `created_at` is when they last confirmed (bumped on
    re-confirm) and is the basis for recency-based trust weighing. `edited_since` is True
    when the source has changed since this user confirmed it (stored marker != the live
    marker the caller supplied), False when it matches, and None when the caller supplied
    no live marker — None means *unknown*, not *unchanged*."""

    id: int
    confirmed_by: str
    source_state: str
    created_at: str  # ISO 8601; basis for recency weighing
    edited_since: Optional[bool] = None


class ConfirmationsResult(BaseModel):
    count: int
    confirmations: list[ConfirmationRow]


# Upsert: one confirmation per user per source. The content-state marker is non-key
# state, so re-confirming the same source updates the marker (and the timestamp) instead
# of inserting a second row — so a resolvable confirmation is always "recorded".
_INSERT = """
INSERT INTO confirmations (store_kind, location, locator, source_state, confirmed_by)
VALUES (%(store_kind)s, %(location)s, %(locator)s, %(source_state)s, %(confirmed_by)s)
ON CONFLICT (confirmed_by, store_kind, location, locator)
DO UPDATE SET source_state = EXCLUDED.source_state, created_at = now()
"""

# `id` is a stable tiebreak so rows with identical created_at (e.g. same-now() re-confirms)
# read back in a deterministic order.
_SELECT = """
SELECT id, confirmed_by, source_state, created_at
FROM confirmations
WHERE store_kind = %(store_kind)s AND location = %(location)s
  AND locator = %(locator)s AND archived_at IS NULL
ORDER BY created_at, id
"""


def confirm_source(
    db: Database, citation: Citation, confirmed_by: str, resolver: CitationResolver
) -> ConfirmResult:
    """Record a confirmation against a cited source. Rejects an unresolvable citation;
    otherwise upserts to one row per user per source — re-confirming an edited source
    updates the stored content-state marker to what the user just vouched for."""
    if not resolver.resolve(citation):
        return ConfirmResult(status="rejected", reason="unresolvable_citation")
    params = {**citation.model_dump(), "confirmed_by": confirmed_by}
    with db.connection() as conn:
        conn.execute(_INSERT, params)
        conn.commit()
    return ConfirmResult(status="recorded")


def read_confirmations(
    db: Database, citation: Citation, current_source_state: Optional[str] = None
) -> ConfirmationsResult:
    """Return confirmations (and a count) for a cited source, matched on store_kind +
    location + locator — one row per user who confirmed it, each carrying the
    `source_state` marker they vouched for and `created_at`. The citation's own
    `source_state` is not used to filter.

    When `current_source_state` is supplied (the source's live marker, fetched by the
    caller), each row's `edited_since` is set to whether that user's stored marker differs
    from it. When it is omitted, `edited_since` stays None — *unknown*, not *unchanged*."""
    with db.connection() as conn:
        rows = conn.execute(_SELECT, citation.model_dump()).fetchall()
    confirmations = [
        ConfirmationRow(
            id=r["id"],
            confirmed_by=r["confirmed_by"],
            source_state=r["source_state"],
            created_at=r["created_at"].isoformat(),
            edited_since=(
                None
                if current_source_state is None
                else r["source_state"] != current_source_state
            ),
        )
        for r in rows
    ]
    return ConfirmationsResult(count=len(confirmations), confirmations=confirmations)
