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


# The two reasons a down vote can carry. An up vote carries none.
DOWN_REASONS = {"bad-retrieval", "wrong-content"}

# Upsert: one confirmation per user per source. The vote/reason/comment and the content-state
# marker are all non-key state, so re-voting the same source (flip up<->down or change reason)
# updates that row in place instead of inserting a second — a resolvable vote is always
# "recorded". The DO UPDATE set-list overwrites every non-key field so a flip fully replaces
# the prior vote rather than leaving a stale reason/comment behind.
_INSERT = """
INSERT INTO confirmations (store_kind, location, locator, source_state, confirmed_by, vote, reason, comment)
VALUES (%(store_kind)s, %(location)s, %(locator)s, %(source_state)s, %(confirmed_by)s, %(vote)s, %(reason)s, %(comment)s)
ON CONFLICT (confirmed_by, store_kind, location, locator)
DO UPDATE SET source_state = EXCLUDED.source_state, vote = EXCLUDED.vote,
              reason = EXCLUDED.reason, comment = EXCLUDED.comment, created_at = now()
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
    db: Database,
    citation: Citation,
    confirmed_by: str,
    resolver: CitationResolver,
    vote: str = "up",
    reason: Optional[str] = None,
    comment: Optional[str] = None,
) -> ConfirmResult:
    """Record a signed vote on a cited source. `vote` is 'up' (right) or 'down' (wrong);
    a down vote names a `reason` ('bad-retrieval' | 'wrong-content'), an up vote names none.
    `comment` is an optional free-text note, available to any vote. Rejects an unresolvable
    citation or a malformed vote; otherwise upserts to one row per user per source — re-voting
    (flip up<->down or change reason) replaces the prior vote rather than stacking a second."""
    if not resolver.resolve(citation):
        return ConfirmResult(status="rejected", reason="unresolvable_citation")
    reason = reason or None
    comment = comment or None
    if vote not in ("up", "down"):
        return ConfirmResult(status="rejected", reason="invalid_vote")
    if vote == "down":
        if reason is None:
            return ConfirmResult(status="rejected", reason="missing_reason")
        if reason not in DOWN_REASONS:
            return ConfirmResult(status="rejected", reason="invalid_reason")
    elif reason is not None:
        return ConfirmResult(status="rejected", reason="reason_on_upvote")
    params = {
        **citation.model_dump(),
        "confirmed_by": confirmed_by,
        "vote": vote,
        "reason": reason,
        "comment": comment,
    }
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
