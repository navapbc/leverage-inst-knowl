"""Route tests for the analytics pages /stats (own) and /all-stats (all users). Reuse the
chat test harness (login + fake sessions client) and a real store."""

from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.db import Store
from lik_ui.settings import Settings
from tests.test_app_auth import FakeOidc
from tests.test_chat import FakeSessionsClient, _app, _login, _owner_id
from tests.test_vault import FakeVaultClient


def _seed_deleted(store, session_id, user_id, email, tokens, *, tools=3, errors=1):
    from datetime import datetime, timezone
    store.write_session_analytics({
        "session_id": session_id, "user_id": user_id, "user_email": email,
        "deletion_path": "prune", "created_at": datetime.now(timezone.utc),
        "input_tokens": tokens, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0,
        "tool_use_count": tools, "error_count": errors,
    })


# ---- /stats (U6) --------------------------------------------------------------

def test_stats_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).get("/stats")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_stats_empty_state_renders(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    r = client.get("/stats")
    assert r.status_code == 200
    assert "No deleted sessions yet." in r.text and "No live sessions." in r.text


def test_stats_shows_own_deleted_totals_and_bars(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    store = Store(db)
    _seed_deleted(store, "s1", _owner_id(db), "alice@navapbc.com", 100)
    _seed_deleted(store, "s2", _owner_id(db), "alice@navapbc.com", 50)
    text = client.get("/stats").text
    assert "Deleted sessions" in text and "Tokens over time" in text
    assert "150" in text  # summed tokens rendered
    # Bars are hydrated client-side (stats.js) from the raw per-session series data.
    assert 'id="tokens-over-time"' in text and "data-series=" in text


def test_stats_scoped_to_viewer_only(db):
    # AE5 / R1: alice sees only her own records on /stats, never bob's.
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    store = Store(db)
    bob = store.upsert_user("bob@navapbc.com")
    _seed_deleted(store, "alice_s", _owner_id(db), "alice@navapbc.com", 100)
    _seed_deleted(store, "bob_s", bob["id"], "bob@navapbc.com", 999)
    text = client.get("/stats").text
    assert "100" in text and "999" not in text  # bob's tokens absent
    # /stats has no per-user "By user" section (that's an /all-stats thing).
    assert "By user" not in text


def test_stats_live_section_shows_cumulative_only(db):
    # AE4 / R11: live rows carry cumulative tokens + status but no per-tool/per-message tallies.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1")  # create a live session
    text = client.get("/stats").text
    assert "Live sessions" in text and "usage unavailable" not in text
    assert "Tool calls" in text  # that label belongs to the DELETED totals table...
    # ...but the live table never emits per-tool breakdown markup.
    assert "tool_breakdown" not in text


def test_stats_live_section_shows_agent_name(db):
    # The live table resolves each session's agent id to its human-readable name.
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1")  # create a live session
    text = client.get("/stats").text
    assert "<th>Agent</th>" in text
    assert "Discovery Layer Agent" in text  # FakeAgentsClient.describe() name


def test_stats_live_section_falls_back_to_agent_id(db):
    # When the name can't be resolved (describe raises), the raw agent id is shown instead.
    class BrokenAgents:
        def resolve_agent_id(self, name):
            return "agent_1"

        def resolve_environment_id(self, name):
            return "env_1"

        def describe(self, agent_id):
            raise RuntimeError("platform unreachable")

    from pathlib import Path

    from tests.test_oauth_connector import RecordingVaultClient
    oidc = FakeOidc({"email": "alice@navapbc.com", "email_verified": True})
    settings = Settings(env="test", agents_config_path=Path(__file__).parent / "fixtures" / "agents.toml")
    app = build_app(settings, store=Store(db), app_oidc=oidc, vault_client=RecordingVaultClient(),
                    agents_client=BrokenAgents(), sessions_client=FakeSessionsClient())
    client = TestClient(app, follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1")
    text = client.get("/stats").text
    assert "agent_1" in text  # raw id rendered as the fallback label


def test_stats_link_in_nav_after_settings(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    nav = client.get("/stats").text
    assert nav.index('href="/settings"') < nav.index('href="/stats"') < nav.index('href="/faq"')


# ---- /all-stats (U7) ----------------------------------------------------------

def test_all_stats_requires_login(db):
    oidc = FakeOidc({})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=FakeVaultClient())
    r = TestClient(app, follow_redirects=False).get("/all-stats")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_all_stats_spans_all_users(db):
    # AE5 / R3: /all-stats shows records from every user, and the per-user breakdown.
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    store = Store(db)
    bob = store.upsert_user("bob@navapbc.com")
    _seed_deleted(store, "alice_s", _owner_id(db), "alice@navapbc.com", 100)
    _seed_deleted(store, "bob_s", bob["id"], "bob@navapbc.com", 40)
    text = client.get("/all-stats").text
    assert "all users" in text and "By user" in text
    assert "alice@navapbc.com" in text and "bob@navapbc.com" in text
    assert "140" in text  # combined tokens


def test_all_stats_not_linked_in_nav(db):
    # R3: reachable only by URL — never rendered as a nav link.
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    assert 'href="/all-stats"' not in client.get("/stats").text


def test_stats_live_session_has_owner_delete_button(db):
    # Own live session on /stats gets a Delete button that returns to /stats.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1")  # create a live session owned by alice
    text = client.get("/stats").text
    assert 'action="/sessions/delete"' in text
    assert 'name="next" value="/stats"' in text


def test_all_stats_no_delete_button_for_other_users_sessions(db):
    # On /all-stats, a session owned by another user must NOT show a Delete button (owner-scoped).
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)  # alice
    bob = Store(db).upsert_user("bob@navapbc.com")
    Store(db).create_session(bob["id"], "agent_1", "bob_live", "Bob live session")
    text = client.get("/all-stats").text
    assert "Bob live session" in text            # listed in the live section
    assert 'value="bob_live"' not in text        # but no delete form targets it


def test_stats_live_table_shows_local_row_fields(db):
    # created_at / auto_delete_at (as dated <time> cells) and the shared flag come from the DB row.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]
    text = client.get("/stats").text
    assert "<th>Created</th>" in text and "<th>Deletes on</th>" in text and "<th>Shared</th>" in text
    assert 'data-format="date"' in text  # dated cells rendered via tz.js
    assert "Private" in text             # a fresh session is private by default
    # Once shared, the flag flips.
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    assert "Shared" in client.get("/stats").text


def test_stats_live_table_shows_input_output_columns(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1")
    text = client.get("/stats").text
    assert '<th class="num">Input tokens</th>' in text and '<th class="num">Output tokens</th>' in text
    assert ">12<" in text and ">8<" in text  # FakeSessionsClient snapshot input=12, output=8


def test_deleted_totals_show_mcp_split(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    store = Store(db)
    store.write_session_analytics({
        "session_id": "s1", "user_id": _owner_id(db), "user_email": "alice@navapbc.com",
        "deletion_path": "prune", "tool_use_count": 3,
        "tool_breakdown": {"tools": {"search": 2, "think": 1}, "servers": {"atlassian": 2, "builtin": 1}},
    })
    text = client.get("/stats").text
    assert "MCP tool calls" in text and "Builtin tool calls" in text
