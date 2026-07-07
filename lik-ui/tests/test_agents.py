"""Agent selection and required-connection resolution."""

from fastapi.testclient import TestClient

from lik_ui.agents import resolve_connections
from lik_ui.app import build_app
from lik_ui.db import Store
from lik_ui.settings import Settings
from tests.test_app_auth import FakeOidc, _start_login_and_get_state
from tests.test_oauth_connector import RecordingVaultClient

LIK = {"name": "lik-mcp", "url": "https://lik.example.com/mcp"}
ATL = {"name": "atlassian", "url": "https://mcp.atlassian.com/v1/sse"}


class FakeAgentsClient:
    def __init__(self, servers, *, raises=False, system="You are a helpful agent.", model="claude-opus-4-8"):
        self.servers = servers
        self.raises = raises
        self.system = system
        self.model = model

    def describe(self, agent_id):
        if self.raises:
            raise RuntimeError("agent retrieval failed")
        return {"servers": self.servers, "system": self.system, "model": self.model}


def test_resolve_marks_connected_and_missing():
    conns = resolve_connections([LIK, ATL], {LIK["url"]})  # lik-mcp connected
    by = {c["name"]: c for c in conns}
    assert by["lik-mcp"]["connected"] is True
    assert by["atlassian"]["connected"] is False


def test_resolve_zero_declared_returns_empty():
    assert resolve_connections([], set()) == []


def _app(db, agents_client, vc):
    oidc = FakeOidc({"email": "alice@navapbc.com", "email_verified": True})
    settings = Settings(env="test", default_agent_id="agent_1", default_environment_id="env_1")
    return build_app(settings, store=Store(db), app_oidc=oidc, vault_client=vc, agents_client=agents_client)


def _login(client):
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=x&state={state}")


def test_connections_page_reflects_vault_state_and_flips_on_connect(db):
    vc = RecordingVaultClient()
    client = TestClient(_app(db, FakeAgentsClient([LIK]), vc), follow_redirects=False)
    _login(client)

    r = client.get("/connections?agent_id=agent_1")
    assert r.status_code == 200
    assert "lik-mcp" in r.text
    assert "Not connected" in r.text
    assert "You are a helpful agent." in r.text  # agent system prompt is shown

    # Simulate a completed connect by adding the credential; status flips to connected.
    vc.credentials.append({"mcp_server_url": LIK["url"]})
    r2 = client.get("/connections?agent_id=agent_1")
    assert "Connected" in r2.text


def test_connections_unknown_agent_is_404(db):
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    assert client.get("/connections?agent_id=nope").status_code == 404


def test_connections_agent_error_surfaces_502(db):
    client = TestClient(_app(db, FakeAgentsClient([], raises=True), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    assert client.get("/connections?agent_id=agent_1").status_code == 502


def test_connections_requires_login(db):
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    r = client.get("/connections?agent_id=agent_1")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
