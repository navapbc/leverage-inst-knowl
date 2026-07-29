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
    store.write_session_analytics({
        "session_id": session_id, "user_id": user_id, "user_email": email,
        "deletion_path": "prune", "input_tokens": tokens, "output_tokens": 0,
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
    assert "bar-fill" in text  # the over-time bars are present


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
    assert "tool calls" in text  # that label belongs to the DELETED totals grid...
    # ...but the live table never emits per-tool breakdown markup.
    assert "tool_breakdown" not in text


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
