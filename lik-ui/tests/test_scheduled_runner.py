"""Unit tests for the shared unattended run-core. A scripted fake SessionsClient feeds the
normalized event vocabulary (text / tool_use / awaiting_confirmation / error / done) so the
allow/deny loop, watchdog, error classification, and empty-session cleanup are exercised without
the platform. Uses the real Store (test DB) so session registration/cleanup are real."""

from lik_ui.scheduled_runner import (
    AUTH_LAPSED,
    DENY_LOOP,
    MAX_DENIES_PER_TOOL,
    SUCCESS,
    TIMED_OUT,
    run_scheduled,
)
from lik_ui.settings import AgentOption, AutoApproveTool


class FakeVault:
    def vault_exists(self, vault_id):
        return True

    def create_vault(self, **kwargs):
        return "vlt_1"


class FakeSessions:
    """Returns each queued stream in turn: the first for send_and_stream, then one per confirm."""

    def __init__(self, streams):
        self.streams = list(streams)
        self.confirms = []
        self.deleted = []

    def create_session(self, agent_id, environment_id, vault_ids, title):
        return "sess_1"

    def _next(self):
        return iter(self.streams.pop(0))

    def send_and_stream(self, session_id, message):
        return self._next()

    def confirm_and_stream(self, session_id, tool_use_id, result, session_thread_id=None):
        self.confirms.append((tool_use_id, result, session_thread_id))
        return self._next()

    def delete_session(self, session_id):
        self.deleted.append(session_id)


def _agents(allowlist=()):
    return [
        AgentOption(
            agent_id="ag_1",
            environment_id="env_1",
            agent_name="Catalog Registration Agent",
            schedulable=True,
            auto_approve=list(allowlist),
            max_runtime=1800,
        )
    ]


def _row(user_id, *, max_runtime_s=1800, prompt="sync the indexes"):
    return {
        "user_id": user_id,
        "agent_name": "Catalog Registration Agent",
        "prompt": prompt,
        "max_runtime_s": max_runtime_s,
    }


def _tool_use(tid, name, *, permission="ask", server="lik-mcp"):
    return {"type": "tool_use", "id": tid, "name": name, "server": server, "permission": permission,
            "session_thread_id": None}


def _await(*ids):
    return {"type": "awaiting_confirmation", "event_ids": list(ids)}


def test_allowlisted_tool_is_auto_approved(store):
    a = store.upsert_user("a@navapbc.com")
    fake = FakeSessions([
        [_tool_use("t1", "register_catalog_entry"), _await("t1")],
        [{"type": "done"}],
    ])
    allowlist = [AutoApproveTool(server="lik-mcp", tool="register_catalog_entry")]
    out = run_scheduled(store, fake, FakeVault(), _agents(allowlist), _row(a["id"]))
    assert out.status == SUCCESS
    assert out.skipped == []
    assert fake.confirms == [("t1", "allow", None)]
    # The run is registered as a session in the owner's list.
    assert [s["session_id"] for s in store.list_sessions(a["id"])] == ["sess_1"]


def test_non_allowlisted_tool_is_denied_and_recorded_but_run_completes(store):
    a = store.upsert_user("a@navapbc.com")
    fake = FakeSessions([
        [_tool_use("t1", "delete_everything"), _await("t1")],
        [{"type": "done"}],
    ])
    out = run_scheduled(store, fake, FakeVault(), _agents(allowlist=[]), _row(a["id"]))
    assert out.status == SUCCESS  # run still completes (skip-and-record, no hang)
    assert out.skipped == [{"server": "lik-mcp", "tool": "delete_everything"}]
    assert fake.confirms == [("t1", "deny", None)]


def test_batched_confirmations_are_all_answered(store):
    a = store.upsert_user("a@navapbc.com")
    # A pause carrying two event_ids: the loop must answer both before the turn resumes.
    fake = FakeSessions([
        [_tool_use("t1", "register_catalog_entry"), _tool_use("t2", "register_catalog_entry"), _await("t1", "t2")],
        [_await("t1", "t2")],  # still paused after the first confirm -> answer the second
        [{"type": "done"}],
    ])
    allowlist = [AutoApproveTool(server="lik-mcp", tool="register_catalog_entry")]
    out = run_scheduled(store, fake, FakeVault(), _agents(allowlist), _row(a["id"]))
    assert out.status == SUCCESS
    assert [c[0] for c in fake.confirms] == ["t1", "t2"]  # both answered, no hang


def test_deny_loop_is_capped(store):
    a = store.upsert_user("a@navapbc.com")
    # The agent re-requests the same denied tool (new id each time) forever; the guard ends it.
    streams = [[_tool_use(f"t{i}", "loop_tool"), _await(f"t{i}")] for i in range(MAX_DENIES_PER_TOOL + 1)]
    fake = FakeSessions(streams)
    out = run_scheduled(store, fake, FakeVault(), _agents(allowlist=[]), _row(a["id"]))
    assert out.status == DENY_LOOP
    assert len(fake.confirms) == MAX_DENIES_PER_TOOL  # capped, did not loop unbounded


def test_auth_lapse_is_classified_and_empty_session_deleted(store):
    a = store.upsert_user("a@navapbc.com")
    fake = FakeSessions([
        [{"type": "error", "error_type": "mcp_authentication_failed_error", "message": "Confluence auth lapsed"}],
    ])
    out = run_scheduled(store, fake, FakeVault(), _agents(), _row(a["id"]))
    assert out.status == AUTH_LAPSED
    # No transcript -> the just-created empty session is cleaned up (row + platform).
    assert store.list_sessions(a["id"]) == []
    assert fake.deleted == ["sess_1"]


def test_benign_error_does_not_abort_the_run(store):
    a = store.upsert_user("a@navapbc.com")
    fake = FakeSessions([
        [{"type": "error", "error_type": "overloaded_error", "message": "busy"},
         {"type": "text", "text": "done working"},
         {"type": "done"}],
    ])
    out = run_scheduled(store, fake, FakeVault(), _agents(), _row(a["id"]))
    assert out.status == SUCCESS  # a non-auth error is not terminal
    # The transcript-bearing session is kept (not deleted).
    assert [s["session_id"] for s in store.list_sessions(a["id"])] == ["sess_1"]
    assert fake.deleted == []


def test_silent_stream_times_out(store):
    a = store.upsert_user("a@navapbc.com")

    def _silent():
        import time
        time.sleep(30)  # never yields within the budget
        yield {"type": "done"}

    fake = FakeSessions([_silent()])
    out = run_scheduled(store, fake, FakeVault(), _agents(), _row(a["id"], max_runtime_s=1))
    assert out.status == TIMED_OUT
    assert store.list_sessions(a["id"]) == []  # empty session cleaned up


def test_unknown_agent_is_a_recorded_failure(store):
    a = store.upsert_user("a@navapbc.com")
    fake = FakeSessions([])
    row = {"user_id": a["id"], "agent_name": "Ghost Agent", "prompt": "x", "max_runtime_s": 60}
    out = run_scheduled(store, fake, FakeVault(), _agents(), row)
    assert out.status == "failed" and "not in the schedulable roster" in out.error
