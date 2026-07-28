"""Tests for the scheduled session-cleanup script. Require a reachable `_test` Postgres
(see conftest `store`). The platform side is faked; the DB side is real."""

from datetime import datetime, timezone

from scripts.prune_sessions import PruneResult, prune_due_sessions

PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)


class FakePlatform:
    """Records platform deletions; optionally raises for specific session ids."""

    def __init__(self, raise_on=()):
        self.deleted: list[str] = []
        self.raise_on = set(raise_on)

    def delete_session(self, session_id: str) -> None:
        if session_id in self.raise_on:
            raise RuntimeError("platform boom")
        self.deleted.append(session_id)


def _expire(store, user_id, session_id):
    store.create_session(user_id, "agent_1", session_id)
    store.set_session_auto_delete_at(session_id, user_id, PAST)


def test_prunes_only_expired_platform_before_row(store):
    a = store.upsert_user("a@navapbc.com")
    b = store.upsert_user("b@navapbc.com")
    _expire(store, a["id"], "past1")
    _expire(store, b["id"], "past2")
    store.create_session(a["id"], "agent_1", "future")  # default +7d, not due

    platform = FakePlatform()
    result = prune_due_sessions(store, platform)

    assert result == PruneResult(deleted=2, failed=0)
    assert set(platform.deleted) == {"past1", "past2"}   # both hit the platform
    assert store.get_session("past1", a["id"]) is None   # and both rows are gone
    assert store.get_session("past2", b["id"]) is None
    assert store.get_session("future", a["id"]) is not None  # the future one is untouched


def test_continues_past_platform_failure_and_keeps_that_row(store):
    a = store.upsert_user("a@navapbc.com")
    _expire(store, a["id"], "boom")
    _expire(store, a["id"], "ok")

    platform = FakePlatform(raise_on={"boom"})
    result = prune_due_sessions(store, platform)

    assert result == PruneResult(deleted=1, failed=1)
    # The failed session's row survives (never orphan a transcript); the other is deleted.
    assert store.get_session("boom", a["id"]) is not None
    assert store.get_session("ok", a["id"]) is None


def test_stub_mode_deletes_rows_without_a_platform_client(store):
    a = store.upsert_user("a@navapbc.com")
    _expire(store, a["id"], "past")
    result = prune_due_sessions(store, None)
    assert result == PruneResult(deleted=1, failed=0)
    assert store.get_session("past", a["id"]) is None


def test_no_due_sessions_is_a_noop(store):
    a = store.upsert_user("a@navapbc.com")
    store.create_session(a["id"], "agent_1", "future")  # default +7d
    platform = FakePlatform()
    result = prune_due_sessions(store, platform)
    assert result == PruneResult(deleted=0, failed=0)
    assert platform.deleted == []
