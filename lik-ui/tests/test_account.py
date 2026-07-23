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


def test_settings_page_lists_credentials(db):
    client, vc = _client(db)
    vc.credentials = [{"id": "vcrd_1", "display_name": "lik-mcp", "url": "https://mcp.example/mcp"}]
    r = client.get("/settings")
    assert r.status_code == 200
    assert "lik-mcp" in r.text
    assert "https://mcp.example/mcp" in r.text
    assert "vcrd_1" in r.text  # the delete button carries the credential id


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
