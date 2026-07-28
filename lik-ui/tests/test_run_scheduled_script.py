"""Smoke tests for the scheduled-runs scanner script's orchestration: claim due rows, run each
via the shared core, and persist the outcome (complete vs auth-lapse pause). The platform side is
faked; the DB side is real (test `store`). The run-core itself is covered in test_scheduled_runner."""

from datetime import timedelta

from lik_ui.settings import AgentOption, AutoApproveTool
from scripts.run_scheduled import run_due_schedules

AGENT = "Catalog Registration Agent"


class FakeVault:
    def vault_exists(self, vault_id):
        return True

    def create_vault(self, **kwargs):
        return "vlt_1"


class FakeSessions:
    def __init__(self, streams):
        self.streams = list(streams)

    def create_session(self, agent_id, environment_id, vault_ids, title):
        return "sess_1"

    def send_and_stream(self, session_id, message):
        return iter(self.streams.pop(0))

    def confirm_and_stream(self, session_id, tool_use_id, result, session_thread_id=None):
        return iter(self.streams.pop(0))

    def delete_session(self, session_id):
        pass


def _agents():
    return [
        AgentOption(
            agent_id="ag_1", environment_id="env_1", agent_name=AGENT, schedulable=True,
            auto_approve=[AutoApproveTool(server="lik-mcp", tool="register_catalog_entry")], max_runtime=1800,
        )
    ]


def test_run_due_schedules_runs_and_completes(store):
    a = store.upsert_user("a@navapbc.com")
    store.create_scheduled_run(a["id"], AGENT, "sync the indexes", timedelta(hours=1))
    fake = FakeSessions([
        [{"type": "tool_use", "id": "t1", "name": "register_catalog_entry", "server": "lik-mcp",
          "permission": "ask", "session_thread_id": None},
         {"type": "awaiting_confirmation", "event_ids": ["t1"]}],
        [{"type": "done"}],
    ])
    ran, failed = run_due_schedules(store, fake, FakeVault(), _agents())
    assert (ran, failed) == (1, 0)
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["last_status"] == "success"
    assert row["started_at"] is None  # completed, advanced
    # A second scan finds nothing due (next_run_at advanced by the interval).
    assert run_due_schedules(store, FakeSessions([]), FakeVault(), _agents()) == (0, 0)


def test_run_due_schedules_auth_lapse_pauses_and_counts_failure(store):
    a = store.upsert_user("a@navapbc.com")
    store.create_scheduled_run(a["id"], AGENT, "sync", timedelta(hours=1))
    fake = FakeSessions([
        [{"type": "error", "error_type": "mcp_authentication_failed_error", "message": "Confluence auth lapsed"}],
    ])
    ran, failed = run_due_schedules(store, fake, FakeVault(), _agents())
    assert (ran, failed) == (1, 1)  # ran, but counted as a failure
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["paused"] is True
    assert row["pause_reason"] == "needs_reauth"
    assert row["last_status"] == "auth_lapsed"
