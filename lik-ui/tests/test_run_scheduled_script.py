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


def test_run_due_schedules_logs_chat_url(store, capsys):
    """The job output names each run's session as a clickable chat URL — at start (so a hanging
    run is still attributable) and on completion, with the measured duration."""
    a = store.upsert_user("a@navapbc.com")
    store.create_scheduled_run(a["id"], AGENT, "sync the indexes", timedelta(hours=1))
    fake = FakeSessions([[{"type": "done"}]])
    run_due_schedules(store, fake, FakeVault(), _agents(), "https://ui.lik.navapbc.com/")
    out = capsys.readouterr().out
    assert "started -> https://ui.lik.navapbc.com/chat/sess_1" in out
    assert "-> success in " in out and "https://ui.lik.navapbc.com/chat/sess_1" in out


def test_run_due_schedules_records_duration(store):
    """A completed run persists its measured wall-clock in last_duration_s, so max_runtime can be
    tuned per agent from real run times."""
    a = store.upsert_user("a@navapbc.com")
    store.create_scheduled_run(a["id"], AGENT, "sync", timedelta(hours=1))
    run_due_schedules(store, FakeSessions([[{"type": "done"}]]), FakeVault(), _agents())
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["last_status"] == "success"
    assert row["last_duration_s"] is not None and row["last_duration_s"] >= 0


def test_hard_backstop_records_a_run_blocked_past_its_budget(store, monkeypatch):
    """If a run blocks past its budget (the in-run watchdog failed to fire), the process-level
    SIGALRM backstop trips and the scanner records the row as failed — instead of the whole CI job
    being killed by GitHub with the row left unrecorded (the original stuck-run failure)."""
    import scripts.run_scheduled as rs

    a = store.upsert_user("a@navapbc.com")
    store.create_scheduled_run(a["id"], AGENT, "sync", timedelta(hours=1), max_runtime_s=1)
    monkeypatch.setattr(rs, "_HARD_TIMEOUT_MARGIN_S", 0)  # trip at max_runtime_s (1s), not +120

    def _blocks(*_args, **_kwargs):
        import time
        time.sleep(30)  # never returns within the budget

    monkeypatch.setattr(rs, "run_scheduled", _blocks)
    ran, failed = rs.run_due_schedules(store, FakeSessions([]), FakeVault(), _agents())
    assert failed == 1
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["last_status"] == "failed"
    assert "backstop" in (row["last_error"] or "")
    assert row["last_duration_s"] is not None  # recorded even for the backstop path


def test_terminal_write_is_retried_after_a_transient_db_failure(store, monkeypatch):
    """The terminal write happens after a long stretch of no DB traffic, so it is the write most
    exposed to a dropped connection. A blip must be retried, not lost."""
    import scripts.run_scheduled as rs

    monkeypatch.setattr(rs, "_RECORD_RETRY_BACKOFF_S", (0, 0, 0))
    a = store.upsert_user("a@navapbc.com")
    store.create_scheduled_run(a["id"], AGENT, "sync", timedelta(hours=1))
    real_complete = store.complete_run
    calls = {"n": 0}

    def _flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("couldn't get a connection after 5.00 sec")
        return real_complete(*args, **kwargs)

    monkeypatch.setattr(store, "complete_run", _flaky)
    ran, failed = rs.run_due_schedules(store, FakeSessions([[{"type": "done"}]]), FakeVault(), _agents())
    assert (ran, failed) == (1, 0)  # the retry recorded it, so this is not a job failure
    row = store.list_scheduled_runs(a["id"])[0]
    assert row["last_status"] == "success"
    assert row["started_at"] is None  # advanced, not left in flight


def test_unrecordable_outcome_counts_as_failure_without_aborting_the_scan(store, monkeypatch):
    """When the outcome cannot be persisted at all, the scan still finishes the remaining rows and
    the job exits non-zero (the row stays in flight and is reclaimed next scan)."""
    import scripts.run_scheduled as rs

    monkeypatch.setattr(rs, "_RECORD_RETRY_BACKOFF_S", (0, 0))
    a = store.upsert_user("a@navapbc.com")
    store.create_scheduled_run(a["id"], AGENT, "sync", timedelta(hours=1))

    def _always_fails(*_args, **_kwargs):
        raise RuntimeError("couldn't get a connection after 5.00 sec")

    monkeypatch.setattr(store, "complete_run", _always_fails)
    ran, failed = rs.run_due_schedules(store, FakeSessions([[{"type": "done"}]]), FakeVault(), _agents())
    assert (ran, failed) == (1, 1)


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
