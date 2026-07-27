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


class SectionAgentsClient:
    """Resolves distinct ids per agent name and describes each with a distinct label, so the
    grouped/filtered picker can be observed in the rendered HTML."""

    def __init__(self, name_to_id):
        self.name_to_id = name_to_id
        self.id_to_label = {v: k for k, v in name_to_id.items()}

    def resolve_agent_id(self, name):
        return self.name_to_id[name]

    def resolve_environment_id(self, name):
        return "env_1"

    def describe(self, agent_id):
        return {"name": self.id_to_label[agent_id], "servers": [], "system": None,
                "model": None, "skills": [], "version": None}


_SECTION_ROSTER = """
default_environment = "Env"

[[sections]]
name = "Knowledge"

[[sections]]
name = "Management"
management = true

[[agents]]
agent = "Searcher"
section = "Knowledge"

[[agents]]
agent = "Registrar"
section = "Management"

[[agents]]
agent = "Loner"
"""


def _section_client(db, tmp_path, roster=_SECTION_ROSTER):
    path = tmp_path / "agents.toml"
    path.write_text(roster)
    settings = Settings(env="test", agents_config_path=path)
    from tests.test_oauth_connector import RecordingVaultClient

    agents_client = SectionAgentsClient({"Searcher": "id_search", "Registrar": "id_reg", "Loner": "id_lone"})
    oidc = FakeOidc({"email": "alice@navapbc.com", "email_verified": True})
    app = build_app(settings, store=Store(db), app_oidc=oidc, vault_client=RecordingVaultClient(),
                    agents_client=agents_client)
    client = TestClient(app, follow_redirects=False)
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=x&state={state}")
    return client


def test_picker_hides_management_section_by_default(db, tmp_path):
    html = _section_client(db, tmp_path).get("/").text
    assert "Searcher" in html          # non-management agent shown
    assert "Knowledge" in html         # its section heading shown
    assert "Registrar" not in html     # management agent hidden by default (AE1)
    assert "Management" not in html    # empty (all-filtered) section renders no heading


def test_picker_shows_management_section_when_enabled(db, tmp_path):
    client = _section_client(db, tmp_path)
    client.post("/settings/agent-visibility", data={"show_management_agents": "1"})
    html = client.get("/").text
    assert "Registrar" in html         # now visible (AE1)
    assert "Management" in html         # its heading now rendered


def test_sectionless_agent_falls_into_default_group(db, tmp_path):
    html = _section_client(db, tmp_path).get("/").text
    assert "Loner" in html             # AE4: no-section agent still renders
    assert "Other" in html             # under the trailing default heading


def test_sections_render_in_declared_order(db, tmp_path):
    client = _section_client(db, tmp_path)
    client.post("/settings/agent-visibility", data={"show_management_agents": "1"})
    html = client.get("/").text
    assert html.index("Knowledge") < html.index("Management") < html.index("Other")


def test_management_agent_reachable_by_direct_url_when_hidden(db, tmp_path):
    """AE3: the toggle is cosmetic — a management agent hidden from the picker is still reachable
    by a direct /connections URL."""
    client = _section_client(db, tmp_path)  # toggle off by default
    r = client.get("/connections?agent_id=id_reg")
    assert r.status_code == 200
    assert "Registrar" in r.text


def test_empty_roster_shows_empty_state(db, tmp_path):
    html = _section_client(db, tmp_path, roster='default_environment = "Env"\n').get("/").text
    assert "No agents are configured" in html


def test_logout_clears_session(db):
    client, _, _ = _client(db, {"email": "alice@navapbc.com", "email_verified": True})
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=abc&state={state}")
    assert client.get("/").status_code == 200

    r = client.get("/logout")
    assert r.status_code == 303
    assert client.get("/").status_code == 303  # back to anonymous
