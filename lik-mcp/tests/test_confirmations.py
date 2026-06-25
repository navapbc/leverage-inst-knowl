import re

import pytest
from pydantic import ValidationError

from lik_mcp.citations import Citation, ShapeResolver
from lik_mcp.confirmations import confirm_source, read_confirmations

RESOLVER = ShapeResolver()
ALICE = "alice@navapbc.com"
BOB = "bob@navapbc.com"


def _citation(**overrides) -> Citation:
    base = dict(store_kind="confluence", location="page:123", locator="", source_state="abc")
    base.update(overrides)
    return Citation(**base)


def _citation_no_state(**overrides) -> Citation:
    base = dict(store_kind="confluence", location="page:123", locator="")
    base.update(overrides)
    return Citation(**base)


def test_citation_rejects_removed_version_field(db):
    """Citation forbids extra fields, so a caller still sending the removed `version` fails
    loudly rather than silently recording an empty marker."""
    with pytest.raises(ValidationError):
        Citation(store_kind="confluence", location="page:1", version="v5")


def test_unresolvable_citation_rejected(db):
    """A citation that doesn't resolve is refused and writes no row."""
    bad = Citation(store_kind="unknown-store", location="x", source_state="s1")
    result = confirm_source(db, bad, ALICE, RESOLVER)
    assert result.status == "rejected"
    assert result.reason == "unresolvable_citation"
    assert read_confirmations(db, bad).count == 0


def test_confirm_records(db):
    """A resolvable confirmation is recorded with its source_state marker."""
    citation = _citation(source_state="abc")
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "recorded"
    rows = read_confirmations(db, citation)
    assert rows.count == 1
    assert rows.confirmations[0].source_state == "abc"
    assert rows.confirmations[0].confirmed_by == ALICE


def test_reconfirm_upserts_to_one_row(db):
    """Re-confirming the same source by the same user keeps ONE row and updates the
    stored marker to the latest state vouched for — always returns 'recorded'."""
    assert confirm_source(db, _citation(source_state="abc"), ALICE, RESOLVER).status == "recorded"
    assert confirm_source(db, _citation(source_state="xyz"), ALICE, RESOLVER).status == "recorded"

    rows = read_confirmations(db, _citation())
    assert rows.count == 1
    assert rows.confirmations[0].source_state == "xyz"


def test_reconfirm_same_marker_idempotent(db):
    """Confirming the exact same source+marker twice stays one row (no duplicate slot)."""
    citation = _citation(source_state="abc")
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "recorded"
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "recorded"
    assert read_confirmations(db, citation).count == 1


def test_distinct_users_each_get_a_row(db):
    """Two different users confirming the same source yield two rows, each with its own
    marker — the marker is non-key state, but confirmed_by is part of the key."""
    confirm_source(db, _citation(source_state="abc"), ALICE, RESOLVER)
    confirm_source(db, _citation(source_state="def"), BOB, RESOLVER)

    rows = read_confirmations(db, _citation())
    assert rows.count == 2
    by_user = {c.confirmed_by: c.source_state for c in rows.confirmations}
    assert by_user == {ALICE: "abc", BOB: "def"}


def test_read_matches_on_source_not_marker(db):
    """read_confirmations matches on store_kind + location + locator; the citation's own
    source_state does not filter, so a read with any marker surfaces the confirmation."""
    confirm_source(db, _citation(source_state="abc"), ALICE, RESOLVER)

    found = read_confirmations(db, _citation(source_state="totally-different"))
    assert found.count == 1
    assert found.confirmations[0].source_state == "abc"
    # created_at is ISO 8601 — the basis for recency weighing.
    assert re.match(r"\d{4}-\d{2}-\d{2}T", found.confirmations[0].created_at)


def test_confirm_with_source_state_none_normalizes(db):
    """Citation(source_state=None) normalizes to '' and records successfully."""
    citation = Citation(store_kind="confluence", location="page:456", source_state=None)
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "recorded"
    rows = read_confirmations(db, citation)
    assert rows.count == 1
    assert rows.confirmations[0].source_state == ""


def test_no_marker_row_has_created_at(db):
    """When source_state='', created_at is still present and parseable for recency weighing."""
    citation = _citation_no_state()
    confirm_source(db, citation, ALICE, RESOLVER)
    rows = read_confirmations(db, citation)
    assert rows.count == 1
    row = rows.confirmations[0]
    assert row.source_state == ""
    assert re.match(r"\d{4}-\d{2}-\d{2}T", row.created_at)


def test_edited_since_false_when_marker_matches(db):
    """Live marker == stored marker -> edited_since is False (confirmed state still current)."""
    confirm_source(db, _citation(source_state="abc"), ALICE, RESOLVER)
    rows = read_confirmations(db, _citation(), current_source_state="abc")
    assert rows.confirmations[0].edited_since is False


def test_edited_since_true_when_marker_differs(db):
    """Live marker != stored marker -> edited_since is True (source edited since confirmed)."""
    confirm_source(db, _citation(source_state="abc"), ALICE, RESOLVER)
    rows = read_confirmations(db, _citation(), current_source_state="xyz")
    assert rows.confirmations[0].edited_since is True


def test_edited_since_none_when_no_live_marker(db):
    """No current_source_state supplied -> edited_since is None (unknown, not unchanged)."""
    confirm_source(db, _citation(source_state="abc"), ALICE, RESOLVER)
    rows = read_confirmations(db, _citation())
    assert rows.confirmations[0].edited_since is None


# --- Signed votes (thumbs up / down) -------------------------------------------------

def _raw_votes(db):
    """Raw (vote, reason, comment) rows straight from the table, so the write path is
    verifiable independent of what read_confirmations exposes."""
    with db.connection() as conn:
        return conn.execute(
            "SELECT vote, reason, comment FROM confirmations ORDER BY id"
        ).fetchall()


def test_upvote_default_records_positive(db):
    """AE1: a bare confirmation defaults to an up vote with no reason or comment."""
    assert confirm_source(db, _citation(), ALICE, RESOLVER).status == "recorded"
    assert _raw_votes(db) == [{"vote": "up", "reason": None, "comment": None}]


def test_downvote_bad_retrieval_records_without_note(db):
    """AE3: a down/bad-retrieval vote records the reason with no note required."""
    result = confirm_source(db, _citation(), ALICE, RESOLVER, vote="down", reason="bad-retrieval")
    assert result.status == "recorded"
    assert _raw_votes(db) == [{"vote": "down", "reason": "bad-retrieval", "comment": None}]


def test_downvote_wrong_content_stores_note(db):
    """AE2: a down/wrong-content vote stores the reason and the free-text note."""
    note = "states the 2019 rate, superseded in 2022"
    result = confirm_source(
        db, _citation(), ALICE, RESOLVER, vote="down", reason="wrong-content", comment=note
    )
    assert result.status == "recorded"
    assert _raw_votes(db) == [{"vote": "down", "reason": "wrong-content", "comment": note}]


def test_revote_flip_replaces_to_one_row(db):
    """AE4 / R6: flipping an up vote to a down vote replaces it — one row, now negative."""
    confirm_source(db, _citation(), ALICE, RESOLVER)  # up
    confirm_source(db, _citation(), ALICE, RESOLVER, vote="down", reason="bad-retrieval")
    assert read_confirmations(db, _citation()).count == 1
    assert _raw_votes(db) == [{"vote": "down", "reason": "bad-retrieval", "comment": None}]


def test_revote_change_reason_clears_stale_comment(db):
    """Changing reason replaces in place: a later bad-retrieval vote clears the prior
    wrong-content note rather than leaving it behind."""
    confirm_source(db, _citation(), ALICE, RESOLVER, vote="down", reason="wrong-content", comment="old note")
    confirm_source(db, _citation(), ALICE, RESOLVER, vote="down", reason="bad-retrieval")
    assert _raw_votes(db) == [{"vote": "down", "reason": "bad-retrieval", "comment": None}]


def test_downvote_missing_reason_rejected(db):
    """A down vote with no reason is rejected and writes nothing."""
    result = confirm_source(db, _citation(), ALICE, RESOLVER, vote="down")
    assert result.status == "rejected"
    assert result.reason == "missing_reason"
    assert _raw_votes(db) == []


def test_downvote_invalid_reason_rejected(db):
    """A down vote with an out-of-enum reason is rejected and writes nothing."""
    result = confirm_source(db, _citation(), ALICE, RESOLVER, vote="down", reason="bogus")
    assert result.status == "rejected"
    assert result.reason == "invalid_reason"
    assert _raw_votes(db) == []


def test_upvote_with_reason_rejected(db):
    """An up vote may not carry a reason — rejected, nothing written."""
    result = confirm_source(db, _citation(), ALICE, RESOLVER, vote="up", reason="bad-retrieval")
    assert result.status == "rejected"
    assert result.reason == "reason_on_upvote"
    assert _raw_votes(db) == []


def test_invalid_vote_rejected(db):
    """An unknown vote direction is rejected, nothing written."""
    result = confirm_source(db, _citation(), ALICE, RESOLVER, vote="sideways")
    assert result.status == "rejected"
    assert result.reason == "invalid_vote"
    assert _raw_votes(db) == []


def test_comment_on_upvote_is_stored(db):
    """R3: the comment field is reason-agnostic — an up vote may carry a note."""
    result = confirm_source(db, _citation(), ALICE, RESOLVER, comment="handy")
    assert result.status == "recorded"
    assert _raw_votes(db) == [{"vote": "up", "reason": None, "comment": "handy"}]


def test_edited_since_true_when_stored_marker_empty(db):
    """A stored '' marker differs from any non-empty live marker -> edited_since is True."""
    confirm_source(db, _citation_no_state(), ALICE, RESOLVER)
    rows = read_confirmations(db, _citation_no_state(), current_source_state="abc")
    assert rows.confirmations[0].source_state == ""
    assert rows.confirmations[0].edited_since is True


def test_edited_since_per_user(db):
    """edited_since is computed per row against each user's own stored marker."""
    confirm_source(db, _citation(source_state="abc"), ALICE, RESOLVER)
    confirm_source(db, _citation(source_state="xyz"), BOB, RESOLVER)
    rows = read_confirmations(db, _citation(), current_source_state="xyz")
    flags = {c.confirmed_by: c.edited_since for c in rows.confirmations}
    assert flags == {ALICE: True, BOB: False}


def test_read_no_confirmations_is_empty(db):
    """A source with no confirmations is a clean empty result, even with a live marker."""
    rows = read_confirmations(db, _citation(), current_source_state="abc")
    assert rows.count == 0
    assert rows.confirmations == []
