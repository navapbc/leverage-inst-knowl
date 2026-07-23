"""Agent selection and required-connection resolution."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from lik_ui.agents import AnthropicAgentsClient, resolve_connections
from lik_ui.app import build_app
from lik_ui.db import Store
from lik_ui.settings import Settings
from tests.test_app_auth import FakeOidc, _start_login_and_get_state
from tests.test_oauth_connector import RecordingVaultClient

LIK = {"name": "lik-mcp", "url": "https://lik.example.com/mcp"}
ATL = {"name": "atlassian", "url": "https://mcp.atlassian.com/v1/sse"}


class FakeAgentsClient:
    def __init__(self, servers, *, raises=False, name="Discovery Layer Agent",
                 system="You are a helpful agent.", model="claude-opus-4-8", skills=None, version="7"):
        self.servers = servers
        self.raises = raises
        self.name = name
        self.system = system
        self.model = model
        self.skills = skills or []
        self.version = version

    def describe(self, agent_id):
        if self.raises:
            raise RuntimeError("agent retrieval failed")
        return {"name": self.name, "servers": self.servers, "system": self.system,
                "model": self.model, "skills": self.skills, "version": self.version}

    def describe_skill(self, skill_id, version):
        return {"name": f"Skill {skill_id}", "description": f"Does {skill_id} things (v{version})."}


def test_resolve_marks_connected_and_missing():
    conns = resolve_connections([LIK, ATL], {LIK["url"]})  # lik-mcp connected
    by = {c["name"]: c for c in conns}
    assert by["lik-mcp"]["connected"] is True
    assert by["atlassian"]["connected"] is False


def test_resolve_zero_declared_returns_empty():
    assert resolve_connections([], set()) == []


def test_resolve_matches_across_trailing_slash():
    # GitHub declares its server with a trailing slash, but the vault platform stores the
    # URL with it stripped; the connected check must still match the two.
    github = {"name": "github", "url": "https://api.githubcopilot.com/mcp/"}
    conns = resolve_connections([github], {"https://api.githubcopilot.com/mcp"})
    assert conns[0]["connected"] is True
    assert conns[0]["url"] == "https://api.githubcopilot.com/mcp/"  # declared form preserved for the connect link


def test_describe_skill_resolves_latest_version():
    """A skill pinned to "latest" is resolved to the concrete latest_version before the
    version lookup that carries name/description."""
    fake_sdk = SimpleNamespace(
        beta=SimpleNamespace(
            skills=SimpleNamespace(
                retrieve=lambda sid: SimpleNamespace(latest_version="1759178010641129"),
                versions=SimpleNamespace(
                    retrieve=lambda version, *, skill_id: SimpleNamespace(
                        name="Query Project Index", description="Short blurb."
                    ),
                ),
            )
        )
    )
    client = AnthropicAgentsClient.__new__(AnthropicAgentsClient)
    client._client = fake_sdk

    out = client.describe_skill("lik-query-project-index", "latest")
    assert out == {"name": "Query Project Index", "description": "Short blurb."}


def test_describe_maps_permission_policy_per_server():
    """The per-server permission policy lives on the agent's mcp_toolset tools (keyed by
    mcp_server_name), not on mcp_servers; describe joins them onto each server."""
    agent = SimpleNamespace(
        name="A", system=None, model=None, skills=[], version="2",
        mcp_servers=[SimpleNamespace(name="atlassian", url="https://a/"),
                     SimpleNamespace(name="github", url="https://g/")],
        tools=[
            SimpleNamespace(type="mcp_toolset", mcp_server_name="atlassian",
                            default_config=SimpleNamespace(permission_policy=SimpleNamespace(type="ask"))),
            SimpleNamespace(type="mcp_toolset", mcp_server_name="github",
                            default_config=SimpleNamespace(permission_policy=SimpleNamespace(type="always_allow"))),
            # A non-toolset tool is ignored; a server with no toolset gets None.
            SimpleNamespace(type="agent_toolset_20260401", mcp_server_name=None, default_config=None),
        ],
    )
    client = AnthropicAgentsClient.__new__(AnthropicAgentsClient)
    client._client = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(
        retrieve=lambda aid: agent)))

    servers = client.describe("agent_1")["servers"]
    assert servers == [
        {"name": "atlassian", "url": "https://a/", "permission_policy": "ask"},
        {"name": "github", "url": "https://g/", "permission_policy": "always_allow"},
    ]


def _app(db, agents_client, vc):
    oidc = FakeOidc({"email": "alice@navapbc.com", "email_verified": True})
    settings = Settings(env="test", agents_config="agent_1:env_1")
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
    # Start chatting is blocked while a source is unconnected. Key off the button's rendered
    # attribute, not a bare "disabled" substring — the gate-override script also mentions it.
    assert "disabled>Start chatting" in r.text

    # Simulate a completed connect by adding the credential; status flips to connected.
    vc.credentials.append({"mcp_server_url": LIK["url"]})
    r2 = client.get("/connections?agent_id=agent_1")
    assert "Connected" in r2.text
    assert "disabled>Start chatting" not in r2.text  # all sources connected -> enabled


def test_home_page_shows_agent_version(db):
    client = TestClient(_app(db, FakeAgentsClient([LIK], version="7"), RecordingVaultClient()),
                        follow_redirects=False)
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "Version" in r.text
    assert ">7<" in r.text


def test_connections_page_lists_agent_skills(db):
    skills = [{"id": "lik-query-project-index", "type": "custom", "version": "1"}]
    client = TestClient(_app(db, FakeAgentsClient([LIK], skills=skills), RecordingVaultClient()),
                        follow_redirects=False)
    _login(client)
    r = client.get("/connections?agent_id=agent_1")
    assert r.status_code == 200
    assert "Skills (1)" in r.text
    assert "lik-query-project-index" in r.text
    assert "skill-details-btn" in r.text  # each skill has a button to fetch its details


def test_skill_details_endpoint_returns_name_description_and_instructions(db, monkeypatch):
    """F3: the endpoint joins describe_skill's name/description with the SKILL.md fetched from
    GitHub and an always-present source_url (the blob link)."""
    async def fake_fetch(name, settings, client_factory=None):
        return "# full instructions"

    monkeypatch.setattr("lik_ui.agents.fetch_skill_instructions", fake_fetch)
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    r = client.get("/skill-details?skill_id=lik-query-project-index&version=3")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Skill lik-query-project-index"
    assert "v3" in body["description"]
    assert body["instructions"] == "# full instructions"
    assert body["source_url"] == (
        "https://github.com/navapbc/leverage-inst-knowl/blob/main"
        "/.claude/skills/Skill lik-query-project-index/SKILL.md"
    )


def test_skill_details_endpoint_degrades_when_fetch_unavailable(db, monkeypatch):
    """R4: a failed SKILL.md fetch yields instructions: null with a non-null source_url and a
    200 — the page shows the fallback link, never an error."""
    async def fake_fetch(name, settings, client_factory=None):
        return None

    monkeypatch.setattr("lik_ui.agents.fetch_skill_instructions", fake_fetch)
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    r = client.get("/skill-details?skill_id=lik-thing&version=3")
    assert r.status_code == 200
    body = r.json()
    assert body["instructions"] is None
    assert body["source_url"].startswith("https://github.com/navapbc/leverage-inst-knowl/blob/main/")
    assert body["source_url"].endswith("/SKILL.md")


def test_skill_details_endpoint_error_skips_fetch(db, monkeypatch):
    """When describe_skill fails the endpoint 502s (unchanged) and never attempts the fetch."""
    async def boom_fetch(name, settings, client_factory=None):
        raise AssertionError("fetch must not run when describe_skill fails")

    monkeypatch.setattr("lik_ui.agents.fetch_skill_instructions", boom_fetch)

    class RaisingSkillClient(FakeAgentsClient):
        def describe_skill(self, skill_id, version):
            raise RuntimeError("skill lookup failed")

    client = TestClient(_app(db, RaisingSkillClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    r = client.get("/skill-details?skill_id=x&version=1")
    assert r.status_code == 502
    assert "Could not load skill" in r.json()["detail"]


def test_skill_details_requires_login(db):
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    r = client.get("/skill-details?skill_id=x&version=1")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


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
