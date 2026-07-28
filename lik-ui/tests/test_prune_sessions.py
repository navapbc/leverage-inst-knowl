"""Tests for the scheduled session-cleanup script. Require a reachable `_test` Postgres
(see conftest `store`). The platform side is faked; the DB side is real."""

from datetime import datetime, timezone
from types import SimpleNamespace

import scripts.prune_sessions as prune
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


def test_db_delete_failure_after_platform_success_aborts_run(store):
    # 'first' sorts before 'second' (earlier auto_delete_at), so it is processed first.
    a = store.upsert_user("a@navapbc.com")
    store.create_session(a["id"], "agent_1", "first")
    store.set_session_auto_delete_at("first", a["id"], datetime(2000, 1, 1, tzinfo=timezone.utc))
    store.create_session(a["id"], "agent_1", "second")
    store.set_session_auto_delete_at("second", a["id"], datetime(2001, 1, 1, tzinfo=timezone.utc))

    platform = FakePlatform()
    original_delete = store.delete_session

    def boom(session_id, user_id):
        if session_id == "first":
            raise RuntimeError("db down")
        return original_delete(session_id, user_id)

    store.delete_session = boom
    result = prune_due_sessions(store, platform)

    # 'first' had its transcript deleted, then the DB row delete failed -> abort before 'second'
    # so we don't keep destroying transcripts against a failing DB.
    assert result == PruneResult(deleted=0, failed=1)
    assert platform.deleted == ["first"]          # transcript already gone for 'first'
    assert "second" not in platform.deleted        # loop aborted; 'second' never touched
    assert store.get_session("first", a["id"]) is not None   # both rows survive for retry
    assert store.get_session("second", a["id"]) is not None


def _fake_settings(**kw):
    kw.setdefault("is_stub", True)
    kw.setdefault("anthropic_api_key", "sk-ant-x")
    kw.setdefault("conninfo", "postgresql://ignored")
    return SimpleNamespace(**kw)


def test_main_returns_nonzero_on_partial_failure(monkeypatch):
    monkeypatch.setattr(prune, "Settings", lambda: _fake_settings())
    monkeypatch.setattr(prune, "Database", lambda conninfo: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(prune, "Store", lambda db: SimpleNamespace(db=db))
    monkeypatch.setattr(prune, "build_sessions_client", lambda s: None)
    monkeypatch.setattr(prune, "prune_due_sessions", lambda store, client: PruneResult(deleted=1, failed=2))
    assert prune.main() == 1


def test_main_returns_zero_on_full_success(monkeypatch):
    monkeypatch.setattr(prune, "Settings", lambda: _fake_settings())
    monkeypatch.setattr(prune, "Database", lambda conninfo: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(prune, "Store", lambda db: SimpleNamespace(db=db))
    monkeypatch.setattr(prune, "build_sessions_client", lambda s: None)
    monkeypatch.setattr(prune, "prune_due_sessions", lambda store, client: PruneResult(deleted=3, failed=0))
    assert prune.main() == 0


def test_main_fails_closed_when_prod_api_key_missing(monkeypatch):
    monkeypatch.setattr(prune, "Settings", lambda: _fake_settings(is_stub=False, anthropic_api_key=""))

    def _should_not_run(*a, **k):
        raise AssertionError("must not touch the DB when failing closed")

    monkeypatch.setattr(prune, "Database", _should_not_run)
    monkeypatch.setattr(prune, "prune_due_sessions", _should_not_run)
    # Fails closed BEFORE constructing the store or deleting anything.
    assert prune.main() == 1
