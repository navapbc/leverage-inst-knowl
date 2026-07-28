"""Agent selection and required-connection resolution."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lik_ui.agents import (
    AnthropicAgentsClient,
    CachingAgentsClient,
    build_agents_client,
    resolve_connections,
)
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

    def resolve_agent_id(self, name):
        # The test roster names resolve to the fixed ids the route tests key off of.
        return "agent_1"

    def resolve_environment_id(self, name):
        return "env_1"

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


class CountingAgentsClient:
    """Delegate that records how often each method is hit, so the cache wrapper can be checked
    by counting the underlying calls. ``describe`` returns per-agent-id data to prove no bleed."""

    def __init__(self):
        self.describe_calls: list[str] = []
        self.skill_calls = 0
        self.resolve_agent_calls = 0
        self.resolve_env_calls = 0
        self.describe_error: Exception | None = None

    def resolve_agent_id(self, name):
        self.resolve_agent_calls += 1
        return f"id-{name}"

    def resolve_environment_id(self, name):
        self.resolve_env_calls += 1
        return f"env-{name}"

    def describe(self, agent_id):
        self.describe_calls.append(agent_id)
        if self.describe_error is not None:
            raise self.describe_error
        return {"name": agent_id, "servers": [], "system": None, "model": None,
                "skills": [], "version": "1"}

    def describe_skill(self, skill_id, version):
        self.skill_calls += 1
        return {"name": skill_id, "description": "x"}


def test_caching_describe_hits_delegate_once_within_ttl():
    delegate = CountingAgentsClient()
    client = CachingAgentsClient(delegate, ttl_seconds=60)
    first = client.describe("a")
    second = client.describe("a")
    assert delegate.describe_calls == ["a"]  # one underlying fetch
    assert first == second


def test_caching_describe_refetches_after_ttl_expiry(monkeypatch):
    delegate = CountingAgentsClient()
    client = CachingAgentsClient(delegate, ttl_seconds=60)
    clock = {"now": 1000.0}
    monkeypatch.setattr("lik_ui.agents.time.monotonic", lambda: clock["now"])
    client.describe("a")
    clock["now"] += 61  # past the TTL window
    client.describe("a")
    assert delegate.describe_calls == ["a", "a"]  # re-fetched after expiry


def test_caching_describe_isolates_distinct_ids():
    delegate = CountingAgentsClient()
    client = CachingAgentsClient(delegate, ttl_seconds=60)
    a = client.describe("a")
    b = client.describe("b")
    assert delegate.describe_calls == ["a", "b"]  # one fetch each, no cross-agent bleed
    assert a["name"] == "a" and b["name"] == "b"


def test_caching_disabled_when_ttl_zero():
    delegate = CountingAgentsClient()
    client = CachingAgentsClient(delegate, ttl_seconds=0)
    client.describe("a")
    client.describe("a")
    assert delegate.describe_calls == ["a", "a"]  # pass-through, always fetch


def test_caching_delegates_non_describe_methods_uncached():
    delegate = CountingAgentsClient()
    client = CachingAgentsClient(delegate, ttl_seconds=60)
    assert client.resolve_agent_id("x") == "id-x"
    client.resolve_agent_id("x")
    client.resolve_environment_id("y")
    client.describe_skill("s", "1")
    client.describe_skill("s", "1")
    assert delegate.resolve_agent_calls == 2  # not cached
    assert delegate.resolve_env_calls == 1
    assert delegate.skill_calls == 2  # not cached


def test_caching_does_not_store_on_delegate_error():
    delegate = CountingAgentsClient()
    delegate.describe_error = RuntimeError("boom")
    client = CachingAgentsClient(delegate, ttl_seconds=60)
    with pytest.raises(RuntimeError):
        client.describe("a")
    delegate.describe_error = None
    client.describe("a")  # cache was not poisoned by the failure — re-attempts the delegate
    assert delegate.describe_calls == ["a", "a"]


def test_build_agents_client_wraps_with_caching():
    settings = Settings(env="prod", anthropic_api_key="sk-test", agent_describe_ttl=42)
    client = build_agents_client(settings)
    assert isinstance(client, CachingAgentsClient)
    assert isinstance(client._delegate, AnthropicAgentsClient)
    assert client._ttl == 42


def test_build_agents_client_returns_none_for_stub():
    assert build_agents_client(Settings(env="local")) is None


def test_agent_describe_ttl_defaults_to_60():
    assert Settings().agent_describe_ttl == 60


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
    settings = Settings(env="test", agents_config_path=Path(__file__).parent / "fixtures" / "agents.toml")
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


def test_skill_details_endpoint_returns_name_description_and_source_url(db):
    """The endpoint joins describe_skill's name/description with an always-present source_url
    (the blob link) and no longer fetches or returns the SKILL.md instructions."""
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    r = client.get("/skill-details?skill_id=lik-query-project-index&version=3")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Skill lik-query-project-index"
    assert "v3" in body["description"]
    assert "instructions" not in body  # instructions are not shown in-app
    assert body["source_url"] == (
        "https://github.com/navapbc/leverage-inst-knowl/blob/main"
        "/claude_platform/skills/Skill lik-query-project-index/SKILL.md"
    )


def test_skill_details_endpoint_error_surfaces_502(db):
    """When describe_skill fails the endpoint 502s (unchanged)."""
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


# --- name -> id resolution at startup ----------------------------------------------------------


def test_resolve_agent_options_maps_roster_names_to_ids(tmp_path):
    """The name roster resolves to AgentOptions carrying the ids the fake returns, in file order."""
    from lik_ui.agents import resolve_agent_options
    from lik_ui.settings import Settings

    path = tmp_path / "agents.toml"
    path.write_text('default_environment = "Env"\n\n[[agents]]\nagent = "Test Agent"\n')
    settings = Settings(env="test", agents_config_path=path)
    options = resolve_agent_options(settings, FakeAgentsClient([LIK]))
    assert [(o.agent_id, o.environment_id) for o in options] == [("agent_1", "env_1")]


def test_resolve_agent_options_carries_section_and_management(tmp_path):
    """Section metadata from the roster is carried onto the resolved AgentOptions so the picker
    can group and hide management agents without re-reading the roster."""
    from lik_ui.agents import resolve_agent_options
    from lik_ui.settings import Settings

    path = tmp_path / "agents.toml"
    path.write_text(
        'default_environment = "Env"\n\n'
        '[[sections]]\nname = "Knowledge"\n\n'
        '[[sections]]\nname = "Management"\nmanagement = true\n\n'
        '[[agents]]\nagent = "Searcher"\nsection = "Knowledge"\n\n'
        '[[agents]]\nagent = "Registrar"\nsection = "Management"\n'
    )
    settings = Settings(env="test", agents_config_path=path)
    options = resolve_agent_options(settings, FakeAgentsClient([LIK]))
    assert [(o.section, o.is_management) for o in options] == [
        ("Knowledge", False),
        ("Management", True),
    ]


def test_resolve_agent_options_carries_user_prompt(tmp_path):
    """The roster's user_prompt is carried onto the resolved AgentOption so the chat page can
    render it above the transcript without re-reading the roster."""
    from lik_ui.agents import resolve_agent_options
    from lik_ui.settings import Settings

    path = tmp_path / "agents.toml"
    path.write_text(
        'default_environment = "Env"\n\n'
        '[[agents]]\nagent = "Test Agent"\nuser_prompt = "Ask me anything."\n'
    )
    settings = Settings(env="test", agents_config_path=path)
    options = resolve_agent_options(settings, FakeAgentsClient([LIK]))
    assert options[0].user_prompt == "Ask me anything."


def test_resolve_agent_options_empty_without_client(tmp_path):
    """No agents client (local/test stub) -> empty resolved list, so the app still boots."""
    from lik_ui.agents import resolve_agent_options
    from lik_ui.settings import Settings

    path = tmp_path / "agents.toml"
    path.write_text('[[agents]]\nagent = "Test Agent"\nenvironment = "Env"\n')
    settings = Settings(env="test", agents_config_path=path)
    assert resolve_agent_options(settings, None) == []


def test_resolve_agent_options_unresolved_name_raises(tmp_path):
    """A roster name with no platform match raises (loud startup failure, not a blank picker)."""
    from types import SimpleNamespace

    from lik_ui.agents import AnthropicAgentsClient, resolve_agent_options
    from lik_ui.settings import Settings

    client = AnthropicAgentsClient.__new__(AnthropicAgentsClient)
    client._client = SimpleNamespace(
        beta=SimpleNamespace(
            agents=SimpleNamespace(list=lambda: []),  # no agents on the platform
            environments=SimpleNamespace(list=lambda: [SimpleNamespace(id="env_1", name="Env")]),
        )
    )
    path = tmp_path / "agents.toml"
    path.write_text('[[agents]]\nagent = "Missing Agent"\nenvironment = "Env"\n')
    settings = Settings(env="test", agents_config_path=path)
    with pytest.raises(ValueError):
        resolve_agent_options(settings, client)


def test_resolve_id_by_name_ambiguous_raises():
    """Two platform resources sharing a name is an error — by-name resolution must be unambiguous."""
    from types import SimpleNamespace

    from lik_ui.agents import AnthropicAgentsClient

    items = [SimpleNamespace(id="1", name="Dup"), SimpleNamespace(id="2", name="Dup")]
    with pytest.raises(ValueError):
        AnthropicAgentsClient._resolve_id_by_name(items, "Dup", "agent")
