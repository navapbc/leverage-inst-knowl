"""App-login flow: OIDC callback establishes a session, upserts the user, and provisions
their vault. Google is faked — no network. Uses the db-backed store fixture."""

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.db import Store
from lik_ui.settings import Settings
from tests.test_vault import FakeVaultClient


class FakeOidc:
    def __init__(self, claims: dict):
        self.claims = claims
        self.exchanged = False
        self.last_nonce = ""

    async def authorization_url(self, state: str, nonce: str) -> str:
        return f"https://accounts.example/authorize?state={state}&nonce={nonce}"

    async def exchange_code(self, code: str) -> dict:
        self.exchanged = True
        return {"access_token": "at-123", "id_token": "it-123"}

    async def verify_id_token(self, id_token: str, nonce: str) -> dict:
        self.last_nonce = nonce
        return self.claims


def _client(db, userinfo):
    oidc = FakeOidc(userinfo)
    vc = FakeVaultClient()
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=vc)
    return TestClient(app, follow_redirects=False), oidc, vc


def _start_login_and_get_state(client) -> str:
    r = client.get("/auth/login")
    assert r.status_code == 303
    return parse_qs(urlsplit(r.headers["location"]).query)["state"][0]


def test_successful_login_sets_session_and_provisions_vault(db):
    client, oidc, vc = _client(db, {"email": "alice@navapbc.com", "email_verified": True})
    state = _start_login_and_get_state(client)

    r = client.get(f"/auth/callback?code=abc&state={state}")
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert oidc.exchanged

    store = Store(db)
    user = store.get_user_by_email("alice@navapbc.com")
    assert user is not None
    assert store.get_user_vault(user["id"]) == "vlt_1"

    # Now authenticated: the home page (agent picker) renders with the user's email.
    home = client.get("/")
    assert home.status_code == 200
    assert "alice@navapbc.com" in home.text


def test_callback_rejects_state_mismatch(db):
    client, oidc, _ = _client(db, {"email": "x@navapbc.com", "email_verified": True})
    r = client.get("/auth/callback?code=abc&state=forged")
    assert r.status_code == 400
    assert not oidc.exchanged  # never reached token exchange


def test_callback_rejects_unverified_email(db):
    client, _, _ = _client(db, {"email": "x@navapbc.com", "email_verified": False})
    state = _start_login_and_get_state(client)
    r = client.get(f"/auth/callback?code=abc&state={state}")
    assert r.status_code == 403
    assert Store(db).get_user_by_email("x@navapbc.com") is None  # no user created


def test_login_page_renders(db):
    client, _, _ = _client(db, {"email": "x@navapbc.com", "email_verified": True})
    r = client.get("/login")
    assert r.status_code == 200
    assert "Sign in with Google" in r.text


def test_callback_handles_denied_consent(db):
    # Google redirects with ?error=access_denied (no code) when the user declines.
    client, oidc, _ = _client(db, {"email": "x@navapbc.com", "email_verified": True})
    _start_login_and_get_state(client)
    r = client.get("/auth/callback?error=access_denied&state=whatever")
    assert r.status_code == 400
    assert not oidc.exchanged


def test_home_redirects_anonymous_to_login(db):
    client, _, _ = _client(db, {"email": "x@navapbc.com", "email_verified": True})
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_logout_clears_session(db):
    client, _, _ = _client(db, {"email": "alice@navapbc.com", "email_verified": True})
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=abc&state={state}")
    assert client.get("/").status_code == 200

    r = client.get("/logout")
    assert r.status_code == 303
    assert client.get("/").status_code == 303  # back to anonymous
