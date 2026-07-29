"""Account settings: the Settings page and the vault-delete action."""

from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.db import Store
from lik_ui.settings import Settings
from tests.test_app_auth import FakeOidc, _start_login_and_get_state
from tests.test_chat import FakeSessionsClient
from tests.test_vault import FakeVaultClient


def _client(db, sessions_client=None):
    oidc = FakeOidc({"email": "alice@navapbc.com", "email_verified": True})
    vc = FakeVaultClient()
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=vc,
                    sessions_client=sessions_client)
    client = TestClient(app, follow_redirects=False)
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=x&state={state}")  # logs in + provisions a vault
    return client, vc


def test_settings_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).get("/settings")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_settings_page_renders(db):
    client, _ = _client(db)
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Delete my vault" in r.text


def test_settings_page_has_timezone_selector(db):
    """The time-zone preference is a client-side setting (like dark mode): the page ships the
    empty selector and the tz.js module that populates it and persists the choice."""
    html = _client(db)[0].get("/settings").text
    assert 'id="tz-select"' in html
    assert "/static/tz.js" in html


def test_settings_page_lists_credentials(db):
    client, vc = _client(db)
    vc.credentials = [{"id": "vcrd_1", "display_name": "lik-mcp", "url": "https://mcp.example/mcp"}]
    r = client.get("/settings")
    assert r.status_code == 200
    assert "lik-mcp" in r.text
    assert "https://mcp.example/mcp" in r.text
    assert "vcrd_1" in r.text  # the delete button carries the credential id


def test_settings_page_shows_management_agent_toggle_and_warning(db):
    client, _ = _client(db)
    r = client.get("/settings")
    assert r.status_code == 200
    assert 'name="show_management_agents"' in r.text
    assert "Management agents write data." in r.text  # the guardrail warning


def test_management_toggle_defaults_off(db):
    client, _ = _client(db)
    html = client.get("/settings").text
    # Fresh session: the checkbox renders unchecked.
    assert "show_management_agents" in html
    assert "checked" not in html


def test_enabling_management_toggle_persists_and_renders_checked(db):
    client, _ = _client(db)
    r = client.post("/settings/agent-visibility", data={"show_management_agents": "1"})
    assert r.status_code == 303
    assert r.headers["location"] == "/settings"
    # AE1/AE2: the preference sticks — a later GET in the same session renders it checked.
    assert "checked" in client.get("/settings").text


def test_disabling_management_toggle_persists_off(db):
    client, _ = _client(db)
    client.post("/settings/agent-visibility", data={"show_management_agents": "1"})
    # Unchecked checkbox submits no field -> stored off.
    client.post("/settings/agent-visibility", data={})
    assert "checked" not in client.get("/settings").text


def test_set_agent_visibility_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).post("/settings/agent-visibility", data={"show_management_agents": "1"})
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_delete_credential_deletes_only_that_credential(db):
    client, vc = _client(db)
    user = Store(db).get_user_vault(Store(db).get_user_by_email("alice@navapbc.com")["id"])

    r = client.post("/settings/credential/delete", data={"credential_id": "vcrd_1"})
    assert r.status_code == 303
    assert r.headers["location"] == "/settings"
    assert vc.deleted_credentials == [(user, "vcrd_1")]
    assert vc.deleted == []  # the vault itself is left intact


def test_delete_credential_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).post(
        "/settings/credential/delete", data={"credential_id": "vcrd_1"}
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_delete_vault_deletes_and_forgets_mapping(db):
    client, vc = _client(db)
    user = Store(db).get_user_by_email("alice@navapbc.com")
    assert Store(db).get_user_vault(user["id"]) == "vlt_1"

    r = client.post("/settings/vault/delete")
    assert r.status_code == 303
    assert r.headers["location"] == "/settings?deleted=1"
    assert vc.deleted == ["vlt_1"]
    assert Store(db).get_user_vault(user["id"]) is None


def test_settings_page_shows_delete_all_sessions_when_user_has_sessions(db):
    client, _ = _client(db)
    user = Store(db).get_user_by_email("alice@navapbc.com")
    Store(db).create_session(user["id"], "agent_1", "sess_a", "Chat A")
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Delete all sessions" in r.text


def test_settings_page_hides_delete_all_when_no_sessions(db):
    client, _ = _client(db)
    r = client.get("/settings")
    assert "Delete all sessions" not in r.text
    assert "no sessions to delete" in r.text


def test_delete_all_sessions_removes_every_row_and_platform_session(db):
    sc = FakeSessionsClient()
    client, _ = _client(db, sessions_client=sc)
    user = Store(db).get_user_by_email("alice@navapbc.com")
    Store(db).create_session(user["id"], "agent_1", "sess_a", "Chat A")
    Store(db).create_session(user["id"], "agent_1", "sess_b", "Chat B")

    r = client.post("/settings/sessions/delete-all")
    assert r.status_code == 303
    assert r.headers["location"] == "/settings?sessions_deleted=1"
    assert sorted(sc.deleted) == ["sess_a", "sess_b"]  # platform data removed for each
    assert Store(db).list_sessions(user["id"]) == []  # and every local row is gone


def test_delete_all_sessions_only_touches_the_current_user(db):
    sc = FakeSessionsClient()
    client, _ = _client(db, sessions_client=sc)
    alice = Store(db).get_user_by_email("alice@navapbc.com")
    bob = Store(db).upsert_user("bob@navapbc.com")
    Store(db).create_session(alice["id"], "agent_1", "sess_a", "Alice's")
    Store(db).create_session(bob["id"], "agent_1", "sess_b", "Bob's")

    client.post("/settings/sessions/delete-all")
    assert sc.deleted == ["sess_a"]  # Bob's platform session is left alone
    assert [s["session_id"] for s in Store(db).list_sessions(bob["id"])] == ["sess_b"]


def test_delete_all_sessions_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).post("/settings/sessions/delete-all")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_delete_vault_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).post("/settings/vault/delete")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


# --- scheduled runs (U7) -------------------------------------------------------

from lik_ui.settings import AgentOption  # noqa: E402


def _with_schedulable(client, *options):
    """Populate the resolved-agent roster (empty in stub mode) so the scheduler UI has agents."""
    client.app.state.agents = list(options)
    return client


def _sched_agent(name="Sched Agent", schedulable=True, max_runtime=1800):
    return AgentOption(agent_id="ag_" + name, environment_id="env", agent_name=name,
                       schedulable=schedulable, max_runtime=max_runtime)


def _uid(db):
    return Store(db).get_user_by_email("alice@navapbc.com")["id"]


def test_create_schedule_lists_it_for_the_owner(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    r = client.post("/settings/scheduled-runs",
                    data={"agent_name": "Sched Agent", "interval_count": "1", "interval_unit": "days",
                          "prompt": "sync the indexes"})
    assert r.status_code == 303
    assert r.headers["location"] == "/settings?scheduled=1"
    runs = Store(db).list_scheduled_runs(_uid(db))
    assert [(x["agent_name"], x["prompt"]) for x in runs] == [("Sched Agent", "sync the indexes")]
    assert runs[0]["max_runtime_s"] == 1800  # materialized from the agent's roster value
    # AE1: it appears on the page with a next-run time.
    html = client.get("/settings").text
    assert "Sched Agent" in html and "Next run:" in html


def test_create_schedule_accepts_a_multi_week_cadence(db):
    from datetime import timedelta
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    r = client.post("/settings/scheduled-runs",
                    data={"agent_name": "Sched Agent", "interval_count": "3", "interval_unit": "weeks",
                          "prompt": "go"})
    assert r.headers["location"] == "/settings?scheduled=1"
    assert Store(db).list_scheduled_runs(_uid(db))[0]["run_interval"] == timedelta(weeks=3)
    # The list renders the interval as a human cadence, not a raw timedelta.
    html = client.get("/settings").text
    assert "every 3 weeks" in html


def test_create_rejects_bad_cadence(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    for bad in ({"interval_count": "0", "interval_unit": "days"},      # below the minimum
                {"interval_count": "99", "interval_unit": "weeks"},    # above MAX_CADENCE_COUNT
                {"interval_count": "abc", "interval_unit": "days"},     # not a number
                {"interval_count": "1", "interval_unit": "hours"}):     # unknown unit
        r = client.post("/settings/scheduled-runs",
                        data={"agent_name": "Sched Agent", "prompt": "go", **bad})
        assert r.headers["location"] == "/settings?scheduled_error=1"
    assert Store(db).list_scheduled_runs(_uid(db)) == []


def test_scheduler_only_offers_schedulable_agents(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent("Sched Agent"), _sched_agent("Plain Agent", schedulable=False))
    html = client.get("/settings").text
    # AE6: only the schedulable agent is an option in the picker.
    assert 'value="Sched Agent"' in html
    assert 'value="Plain Agent"' not in html


def test_create_rejects_non_schedulable_agent(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent("Plain Agent", schedulable=False))
    r = client.post("/settings/scheduled-runs",
                    data={"agent_name": "Plain Agent", "interval_count": "1", "interval_unit": "days", "prompt": "go"})
    assert r.headers["location"] == "/settings?scheduled_error=1"
    assert Store(db).list_scheduled_runs(_uid(db)) == []


def test_create_rejects_missing_prompt(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    r = client.post("/settings/scheduled-runs",
                    data={"agent_name": "Sched Agent", "interval_count": "1", "interval_unit": "days", "prompt": "  "})
    assert r.headers["location"] == "/settings?scheduled_error=1"
    assert Store(db).list_scheduled_runs(_uid(db)) == []


def test_pause_and_resume_schedule(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    client.post("/settings/scheduled-runs",
                data={"agent_name": "Sched Agent", "interval_count": "1", "interval_unit": "days", "prompt": "go"})
    run_id = Store(db).list_scheduled_runs(_uid(db))[0]["id"]
    client.post(f"/settings/scheduled-runs/{run_id}/pause", data={"paused": "true"})
    assert Store(db).list_scheduled_runs(_uid(db))[0]["paused"] is True
    assert "Resume" in client.get("/settings").text
    client.post(f"/settings/scheduled-runs/{run_id}/pause", data={"paused": "false"})
    assert Store(db).list_scheduled_runs(_uid(db))[0]["paused"] is False


def test_delete_schedule(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    client.post("/settings/scheduled-runs",
                data={"agent_name": "Sched Agent", "interval_count": "1", "interval_unit": "days", "prompt": "go"})
    run_id = Store(db).list_scheduled_runs(_uid(db))[0]["id"]
    r = client.post(f"/settings/scheduled-runs/{run_id}/delete")
    assert r.status_code == 303
    assert Store(db).list_scheduled_runs(_uid(db)) == []


def test_needs_reauth_badge_renders(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    client.post("/settings/scheduled-runs",
                data={"agent_name": "Sched Agent", "interval_count": "1", "interval_unit": "days", "prompt": "go"})
    run_id = Store(db).list_scheduled_runs(_uid(db))[0]["id"]
    # Simulate a lapsed-credential run outcome (what the scanner's pause_and_flag records).
    Store(db).pause_and_flag(run_id, "needs_reauth", error="Confluence auth lapsed")
    html = client.get("/settings").text
    assert "needs re-authentication" in html  # AE5 health badge


def test_delete_vault_cancels_schedules(db):
    client, _ = _client(db)
    _with_schedulable(client, _sched_agent())
    client.post("/settings/scheduled-runs",
                data={"agent_name": "Sched Agent", "interval_count": "1", "interval_unit": "days", "prompt": "go"})
    assert Store(db).list_scheduled_runs(_uid(db)) != []
    client.post("/settings/vault/delete")
    # R19: deleting the vault cancels the user's schedules so none can run without credentials.
    assert Store(db).list_scheduled_runs(_uid(db)) == []


def test_create_schedule_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).post(
        "/settings/scheduled-runs", data={"agent_name": "x", "interval_count": "1", "interval_unit": "days", "prompt": "y"}
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_delete_all_sessions_captures_analytics_for_each(db):
    # R6: delete-all routes every session through capture, tagged 'delete_all'.
    sc = FakeSessionsClient()
    client, _ = _client(db, sessions_client=sc)
    user = Store(db).get_user_by_email("alice@navapbc.com")
    Store(db).create_session(user["id"], "agent_1", "sess_a", "Chat A")
    Store(db).create_session(user["id"], "agent_1", "sess_b", "Chat B")

    client.post("/settings/sessions/delete-all")
    for sid in ("sess_a", "sess_b"):
        rec = Store(db).get_session_analytics(sid)
        assert rec is not None and rec["deletion_path"] == "delete_all"
        assert rec["capture_incomplete"] is False
