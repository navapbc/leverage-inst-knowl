"""Tests for the agent + environment deploy script.

Fakes the Anthropic SDK client (mirroring test_deploy_skills.py / test_attach_skills_to_agent.py) so
by-name resolution, skill name->id substitution, create-vs-update, and env sync are exercised without
the SDK or any network access.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import deploy_agents as da


# --- fakes -------------------------------------------------------------------------------------


class FakeAgents:
    def __init__(self, existing=None):
        # existing: list of (agent_id, name, version)
        self._existing = [SimpleNamespace(id=i, name=n, version=v) for i, n, v in (existing or [])]
        self.create_calls = []
        self.update_calls = []

    def list(self):
        return list(self._existing)

    def retrieve(self, agent_id):
        return next(a for a in self._existing if a.id == agent_id)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id="agent_new", version="1")

    def update(self, agent_id, **kwargs):
        self.update_calls.append({"agent_id": agent_id, **kwargs})
        return SimpleNamespace(id=agent_id, version="2")


class FakeEnvironments:
    def __init__(self, existing=None):
        # existing: list of (env_id, name) or (env_id, name, current_dict). current_dict is what
        # retrieve() returns for the unchanged/updated comparison; defaults to just the name.
        self._existing = []
        self._current = {}
        for item in (existing or []):
            eid, ename = item[0], item[1]
            self._existing.append(SimpleNamespace(id=eid, name=ename))
            self._current[eid] = item[2] if len(item) > 2 else {"name": ename}
        self.create_calls = []
        self.update_calls = []

    def list(self):
        return list(self._existing)

    def retrieve(self, env_id):
        return self._current[env_id]

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id="env_new", name=kwargs.get("name"))

    def update(self, env_id, **kwargs):
        self.update_calls.append({"env_id": env_id, **kwargs})
        return SimpleNamespace(id=env_id, name=kwargs.get("name"))


class FakeSkills:
    """Records create / versions.create and answers list() from a seeded set (mirrors
    test_deploy_skills.FakeSkills) — deploy_agents now publishes referenced skills itself."""

    def __init__(self, existing=None):
        # existing: list of (skill_id, display_title)
        self._existing = [SimpleNamespace(id=i, display_title=t) for i, t in (existing or [])]
        self.create_calls = []
        self.version_calls = []
        self.versions = SimpleNamespace(create=self._version_create)

    def list(self):
        return list(self._existing)

    def create(self, *, files, display_title):
        self.create_calls.append({"files": files, "display_title": display_title})
        return SimpleNamespace(id="skill_new", latest_version=111)

    def _version_create(self, skill_id, *, files):
        self.version_calls.append({"skill_id": skill_id, "files": files})
        return SimpleNamespace(version=222)


class FakeClient:
    def __init__(self, *, agents=None, environments=None, skills_list=None):
        self.beta = SimpleNamespace(
            agents=FakeAgents(agents),
            environments=FakeEnvironments(environments),
            skills=FakeSkills(skills_list),
        )


# --- fixtures: temp spec trees -----------------------------------------------------------------


AGENT_YAML = """\
name: "LIK Query: Project Index"
model:
  id: claude-sonnet-5
system: "You are a test agent."
mcp_servers:
  - name: lik-mcp
    type: url
    url: https://example/mcp
tools: []
skills:
  - name: lik-query-project-index
metadata: {}
"""

ENV_YAML = """\
name: lik-ui
description: null
config:
  type: cloud
  networking:
    type: limited
    allow_mcp_servers: true
"""


def _wire(tmp_path: Path, monkeypatch, *, agent=AGENT_YAML, env=ENV_YAML, skill="lik-query-project-index"):
    agents_root = tmp_path / "agents"
    envs_root = tmp_path / "environments"
    skills_root = tmp_path / "skills"
    agents_root.mkdir()
    envs_root.mkdir()
    skills_root.mkdir()
    if agent is not None:
        (agents_root / "lik-query-project-index.yaml").write_text(agent, encoding="utf-8")
    if env is not None:
        (envs_root / "lik-ui.yaml").write_text(env, encoding="utf-8")
    if skill is not None:
        # The skill the agent references, so deploy_agents can publish it (dir name == SKILL.md name).
        sdir = skills_root / skill
        sdir.mkdir()
        (sdir / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: test\n---\n# {skill}\n", encoding="utf-8")
    monkeypatch.setattr(da, "AGENTS_ROOT", agents_root)
    monkeypatch.setattr(da, "ENVIRONMENTS_ROOT", envs_root)
    monkeypatch.setattr(da.ds, "SKILLS_ROOT", skills_root)
    return agents_root, envs_root


# --- read_spec / selection ---------------------------------------------------------------------


def test_read_spec_requires_name(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("model:\n  id: x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        da.read_spec(p)


def test_read_spec_missing_file(tmp_path):
    with pytest.raises(ValueError):
        da.read_spec(tmp_path / "nope.yaml")


def test_select_agent_all_and_named(tmp_path, monkeypatch):
    agents_root, _ = _wire(tmp_path, monkeypatch)
    (agents_root / "second.yaml").write_text("name: Second\n", encoding="utf-8")
    assert [p.stem for p in da.select_agent_specs("all")] == ["lik-query-project-index", "second"]
    assert [p.stem for p in da.select_agent_specs("second")] == ["second"]


def test_select_agent_unknown_raises(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        da.select_agent_specs("nope")


# --- by-name matching --------------------------------------------------------------------------


def test_match_by_name_ambiguous_raises():
    items = [SimpleNamespace(name="A", id="1"), SimpleNamespace(name="A", id="2")]
    with pytest.raises(ValueError):
        da._match_by_name(items, "A")


# --- resolve_skills (deploy referenced skills + name -> id substitution) -----------------------


def test_resolve_skills_publishes_new_skill_and_substitutes_id(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    client = FakeClient(skills_list=[])  # skill not on platform yet -> create
    out = da.resolve_skills(client, [{"name": "lik-query-project-index"}])
    assert out == [{"type": "custom", "skill_id": "skill_new", "version": "latest"}]
    assert client.beta.skills.create_calls  # the referenced skill was published


def test_resolve_skills_publishes_new_version_when_skill_exists(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    client = FakeClient(skills_list=[("skill_abc", "lik-query-project-index")])
    out = da.resolve_skills(client, [{"name": "lik-query-project-index"}])
    assert out == [{"type": "custom", "skill_id": "skill_abc", "version": "latest"}]
    assert client.beta.skills.version_calls  # new version, not a duplicate create
    assert client.beta.skills.create_calls == []


def test_resolve_skills_missing_repo_dir_fails_fast(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    client = FakeClient(skills_list=[])
    with pytest.raises(ValueError):
        da.resolve_skills(client, [{"name": "no-such-skill-in-repo"}])
    assert client.beta.skills.create_calls == []  # nothing published


def test_resolve_skills_entry_without_name_fails(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    client = FakeClient(skills_list=[])
    with pytest.raises(ValueError):
        da.resolve_skills(client, [{"skill_id": "skill_abc"}])


def test_resolve_skills_dry_run_does_not_publish(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    client = FakeClient(skills_list=[("skill_abc", "lik-query-project-index")])
    out = da.resolve_skills(client, [{"name": "lik-query-project-index"}], deploy=False)
    assert out == [{"type": "custom", "skill_id": "skill_abc", "version": "latest"}]
    assert client.beta.skills.create_calls == []
    assert client.beta.skills.version_calls == []


# --- deploy_agent: create vs update ------------------------------------------------------------


def test_deploy_new_agent_creates_with_resolved_skills(tmp_path, monkeypatch):
    agents_root, _ = _wire(tmp_path, monkeypatch)
    client = FakeClient(agents=[], skills_list=[("skill_abc", "lik-query-project-index")])
    result = da.deploy_agent(client, agents_root / "lik-query-project-index.yaml")

    assert result.action == "created"
    assert result.resource_id == "agent_new"
    assert client.beta.agents.update_calls == []
    created = client.beta.agents.create_calls[0]
    assert created["name"] == "LIK Query: Project Index"
    assert created["skills"] == [{"type": "custom", "skill_id": "skill_abc", "version": "latest"}]


def test_deploy_existing_agent_updates_preserving_version(tmp_path, monkeypatch):
    agents_root, _ = _wire(tmp_path, monkeypatch)
    client = FakeClient(
        agents=[("agent_1", "LIK Query: Project Index", 7)],
        skills_list=[("skill_abc", "lik-query-project-index")],
    )
    result = da.deploy_agent(client, agents_root / "lik-query-project-index.yaml")

    assert result.action == "updated"
    assert result.resource_id == "agent_1"
    assert client.beta.agents.create_calls == []
    call = client.beta.agents.update_calls[0]
    assert call["agent_id"] == "agent_1"
    assert call["version"] == 7  # current version re-sent
    assert call["name"] == "LIK Query: Project Index"  # full spec re-sent (not dropped)
    assert call["system"] == "You are a test agent."
    assert call["skills"] == [{"type": "custom", "skill_id": "skill_abc", "version": "latest"}]


def test_deploy_agent_missing_skill_dir_makes_no_write(tmp_path, monkeypatch):
    # The referenced skill has no directory under claude_platform/skills/ -> fail fast, nothing written.
    agents_root, _ = _wire(tmp_path, monkeypatch, skill=None)  # no skill dir in the repo
    client = FakeClient(agents=[], skills_list=[])
    with pytest.raises(ValueError):
        da.deploy_agent(client, agents_root / "lik-query-project-index.yaml")
    assert client.beta.agents.create_calls == []
    assert client.beta.agents.update_calls == []
    assert client.beta.skills.create_calls == []


def test_deploy_agent_dry_run_makes_no_write(tmp_path, monkeypatch):
    agents_root, _ = _wire(tmp_path, monkeypatch)
    client = FakeClient(agents=[], skills_list=[("skill_abc", "lik-query-project-index")])
    result = da.deploy_agent(client, agents_root / "lik-query-project-index.yaml", apply=False)
    assert result.action == "would-create"
    assert client.beta.agents.create_calls == []
    assert client.beta.agents.update_calls == []


# --- deploy_environment: create vs update ------------------------------------------------------


def test_deploy_new_environment_creates(tmp_path, monkeypatch):
    _, envs_root = _wire(tmp_path, monkeypatch)
    client = FakeClient(environments=[])
    result = da.deploy_environment(client, envs_root / "lik-ui.yaml")
    assert result.action == "created"
    assert client.beta.environments.update_calls == []
    assert client.beta.environments.create_calls[0]["name"] == "lik-ui"


def test_deploy_existing_environment_updates_when_a_declared_field_differs(tmp_path, monkeypatch):
    _, envs_root = _wire(tmp_path, monkeypatch)
    # Current networking.type differs from the spec (limited) -> a real change -> update.
    current = {"name": "lik-ui", "description": None, "config": {"type": "cloud", "networking": {"type": "strict"}}}
    client = FakeClient(environments=[("env_1", "lik-ui", current)])
    result = da.deploy_environment(client, envs_root / "lik-ui.yaml")
    assert result.action == "updated"
    assert result.resource_id == "env_1"
    assert client.beta.environments.create_calls == []
    assert client.beta.environments.update_calls[0]["env_id"] == "env_1"


def test_deploy_unchanged_environment_reports_unchanged_and_skips_update(tmp_path, monkeypatch):
    _, envs_root = _wire(tmp_path, monkeypatch)
    # Current already matches every field the spec declares (plus platform extras that are ignored).
    current = {
        "name": "lik-ui",
        "description": None,
        "config": {
            "type": "cloud",
            "networking": {"type": "limited", "allow_mcp_servers": True},
            "packages": {"type": "packages", "apt": []},  # platform extra the spec omits -> ignored
        },
    }
    client = FakeClient(environments=[("env_1", "lik-ui", current)])
    result = da.deploy_environment(client, envs_root / "lik-ui.yaml")
    assert result.action == "unchanged"
    assert result.resource_id == "env_1"
    assert client.beta.environments.update_calls == []  # no-op: not touched
    assert client.beta.environments.create_calls == []


# --- main: env-first ordering + selection ------------------------------------------------------


def test_main_syncs_envs_then_selected_agent(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    client = FakeClient(agents=[], environments=[], skills_list=[("skill_abc", "lik-query-project-index")])
    monkeypatch.setattr(da.ds, "build_client", lambda: client)

    rc = da.main(["--agent", "all"])
    assert rc == 0
    # environment created before the agent
    assert client.beta.environments.create_calls[0]["name"] == "lik-ui"
    assert client.beta.agents.create_calls[0]["name"] == "LIK Query: Project Index"
    # the agent's referenced skill was published as part of the same run
    assert client.beta.skills.version_calls  # skill existed -> new version published


def test_main_dry_run_mutates_nothing(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    client = FakeClient(agents=[], environments=[], skills_list=[("skill_abc", "lik-query-project-index")])
    monkeypatch.setattr(da.ds, "build_client", lambda: client)

    rc = da.main(["--agent", "all", "--dry-run"])
    assert rc == 0
    assert client.beta.agents.create_calls == []
    assert client.beta.environments.create_calls == []
    assert client.beta.skills.create_calls == []  # dry run publishes no skills either
    assert client.beta.skills.version_calls == []
