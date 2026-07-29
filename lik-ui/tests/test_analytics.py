"""Analytics domain-logic tests: the pure event tally, and (below) the capture-before-delete
step and read-model helpers. No platform required for the pure pieces."""

from lik_ui.analytics import tally_events


def test_tally_counts_messages_tools_and_errors_with_breakdowns():
    events = [
        {"type": "user", "text": "q1"},
        {"type": "tool_use", "name": "search", "server": "atlassian"},
        {"type": "tool_use", "name": "search", "server": "atlassian"},
        {"type": "tool_use", "name": "read_file", "server": None},  # built-in -> "builtin"
        {"type": "text", "text": "a1"},
        {"type": "error", "error_type": "mcp_connection_failed"},
        {"type": "user", "text": "q2"},
        {"type": "text", "text": "a2"},
        {"type": "usage", "input": 10},        # ignored by the tally
        {"type": "turn_duration", "seconds": 5},  # ignored by the tally
    ]
    t = tally_events(events)
    assert t["user_message_count"] == 2
    assert t["ai_message_count"] == 2
    assert t["tool_use_count"] == 3
    assert t["error_count"] == 1
    assert t["tool_breakdown"] == {
        "tools": {"search": 2, "read_file": 1},
        "servers": {"atlassian": 2, "builtin": 1},
    }
    assert t["error_types"] == {"mcp_connection_failed": 1}


def test_tally_of_empty_stream_is_all_zero():
    t = tally_events([])
    assert t["user_message_count"] == 0 and t["tool_use_count"] == 0 and t["error_count"] == 0
    assert t["tool_breakdown"] == {"tools": {}, "servers": {}}
    assert t["error_types"] == {}


# --- capture-before-delete (U3) ------------------------------------------------

from lik_ui.analytics import capture_session_analytics
from lik_ui.chat import SessionNotFound


class FakeCapturePlatform:
    """A SessionsClient stand-in for capture tests: serves a usage snapshot and an event
    stream, and can be told to raise on either read to exercise the flagged-fallback path."""

    def __init__(self, snapshot=None, events=None, raise_on_read=False):
        self._snapshot = snapshot or {}
        self._events = events or []
        self._raise = raise_on_read

    def usage_snapshot(self, session_id):
        if self._raise:
            raise SessionNotFound(session_id)
        return self._snapshot

    def list_events(self, session_id):
        if self._raise:
            raise SessionNotFound(session_id)
        return iter(self._events)


def _session_row(store, path_agent="agent_1"):
    from datetime import datetime, timezone
    u = store.upsert_user("a@navapbc.com")
    return {
        "session_id": "s1", "user_id": u["id"], "agent_id": path_agent,
        "created_at": datetime(2026, 7, 27, tzinfo=timezone.utc),
    }


def test_capture_full_record_when_platform_reachable(store):
    row = _session_row(store)
    snap = {"input": 100, "output": 40, "cache_read": 10, "cache_creation": 7,
            "active_seconds": 12.5, "wall_clock_seconds": 30.0, "status": "idle",
            "created_at": None, "agent": "agent_1"}
    events = [
        {"type": "user", "text": "q"},
        {"type": "tool_use", "name": "search", "server": "atlassian"},
        {"type": "text", "text": "a"},
        {"type": "error", "error_type": "mcp_connection_failed"},
    ]
    platform = FakeCapturePlatform(snapshot=snap, events=events)
    capture_session_analytics(store, platform, row, "manual")
    rec = store.get_session_analytics("s1")
    assert rec["capture_incomplete"] is False
    assert rec["input_tokens"] == 100 and rec["cache_creation_tokens"] == 7
    assert rec["active_seconds"] == 12.5 and rec["wall_clock_seconds"] == 30.0
    assert rec["user_message_count"] == 1 and rec["ai_message_count"] == 1
    assert rec["tool_use_count"] == 1 and rec["error_count"] == 1
    assert rec["tool_breakdown"]["tools"] == {"search": 1}
    assert rec["error_types"] == {"mcp_connection_failed": 1}
    assert rec["agent_id"] == "agent_1" and rec["deletion_path"] == "manual"
    assert rec["user_email"] == "a@navapbc.com"  # denormalized for /all-stats


def test_capture_writes_flagged_record_when_read_fails(store):
    row = _session_row(store)
    platform = FakeCapturePlatform(raise_on_read=True)
    # Must not raise — deletion must never be blocked by capture (AE2 / R8).
    capture_session_analytics(store, platform, row, "prune")
    rec = store.get_session_analytics("s1")
    assert rec["capture_incomplete"] is True and rec["capture_reason"]
    assert rec["input_tokens"] is None  # local-only, no metrics
    assert rec["agent_id"] == "agent_1" and rec["deletion_path"] == "prune"


def test_capture_platform_lost_writes_flagged_record_without_reading(store):
    row = _session_row(store)

    class Boom:
        def usage_snapshot(self, s):
            raise AssertionError("must not read when platform_lost")

        def list_events(self, s):
            raise AssertionError("must not read when platform_lost")

    capture_session_analytics(store, Boom(), row, "self_heal", platform_lost=True)
    rec = store.get_session_analytics("s1")
    assert rec["capture_incomplete"] is True
    assert "lost" in rec["capture_reason"].lower()
    assert rec["deletion_path"] == "self_heal"


def test_capture_with_stub_client_none_writes_flagged_record(store):
    row = _session_row(store)
    capture_session_analytics(store, None, row, "manual")
    rec = store.get_session_analytics("s1")
    assert rec["capture_incomplete"] is True and rec["input_tokens"] is None


def test_capture_tolerates_thin_prune_row(store):
    # A prune-style row carries only session_id/user_id/agent_id/created_at; a read failure must
    # still write a record and never KeyError inside the fallback (would abort a prune run).
    u = store.upsert_user("a@navapbc.com")
    thin = {"session_id": "s1", "user_id": u["id"]}  # no agent_id / created_at
    platform = FakeCapturePlatform(raise_on_read=True)
    capture_session_analytics(store, platform, thin, "prune")
    rec = store.get_session_analytics("s1")
    assert rec is not None and rec["capture_incomplete"] is True
    assert rec["agent_id"] is None and rec["created_at"] is None


def test_capture_is_idempotent_on_repeated_calls(store):
    row = _session_row(store)
    platform = FakeCapturePlatform(raise_on_read=True)
    capture_session_analytics(store, platform, row, "manual")
    capture_session_analytics(store, platform, row, "manual")
    with store.db.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM session_analytics").fetchone()["n"] == 1


def test_capture_never_raises_even_if_both_reads_raise(store):
    row = _session_row(store)

    class BothRaise:
        def usage_snapshot(self, s):
            raise RuntimeError("retrieve boom")

        def list_events(self, s):
            raise RuntimeError("events boom")

    capture_session_analytics(store, BothRaise(), row, "delete_all")  # must not raise
    assert store.get_session_analytics("s1")["capture_incomplete"] is True
