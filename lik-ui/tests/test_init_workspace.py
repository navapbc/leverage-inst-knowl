"""Unit tests for scripts/init_workspace.py.

Pure logic only — payload building, skill partitioning, SSM formatting, credential
resolution, and the create/error branches against a fake client. The live-API create path
and the definition-capture one-liner are exercised by hand (see the script's docstring),
mirroring how smoke.py splits fakes from real-network stages.
"""

from types import SimpleNamespace

import pytest

from scripts import init_workspace as iw


@pytest.fixture(autouse=True)
def clean():
    """Override conftest's DB-backed autouse fixture — these tests never touch Postgres."""
    yield


# --- fakes ------------------------------------------------------------------------------

class _FakeResource:
    def __init__(self, new_id, *, exc=None):
        self._id = new_id
        self._exc = exc
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(id=self._id)


class _FakeClient:
    def __init__(self, *, env_exc=None):
        self.environments = _FakeResource("env_new", exc=env_exc)
        self.agents = _FakeResource("agent_new")
        self.beta = SimpleNamespace(environments=self.environments, agents=self.agents)


TOOLSET = {
    "type": "agent_toolset_20260401",
    "default_config": {"permission_policy": {"type": "always_allow"}},
}
MCP_TOOLSET = {"type": "mcp_toolset", "mcp_server_name": "lik-mcp"}
MCP_SERVER = {"type": "url", "name": "lik-mcp", "url": "https://lik.example.com/mcp"}
ANTHROPIC_SKILL = {"type": "anthropic", "skill_id": "xlsx"}
CUSTOM_SKILL = {"type": "custom", "skill_id": "skill_abc123", "version": "1"}


def _agent_defn(**overrides):
    defn = {
        "name": "Knowledge Search",
        "model": "claude-opus-4-8",
        "system": "You are a knowledge search agent.",
        "mcp_servers": [MCP_SERVER],
        "tools": [TOOLSET, MCP_TOOLSET],
        "skills": [ANTHROPIC_SKILL],
        "description": "Finds things.",
    }
    defn.update(overrides)
    return defn


# --- build_agent_payload ----------------------------------------------------------------

def test_agent_payload_preserves_all_fields_including_tool_policy():
    payload, dropped = iw.build_agent_payload(_agent_defn())
    assert dropped == []
    assert payload["name"] == "Knowledge Search"
    assert payload["model"] == "claude-opus-4-8"
    assert payload["system"] == "You are a knowledge search agent."
    assert payload["mcp_servers"] == [MCP_SERVER]
    # full tools structure survives, including the mcp_toolset entry and permission policy
    assert payload["tools"] == [TOOLSET, MCP_TOOLSET]
    assert payload["tools"][0]["default_config"]["permission_policy"]["type"] == "always_allow"
    assert payload["skills"] == [ANTHROPIC_SKILL]
    assert payload["description"] == "Finds things."


def test_agent_payload_model_override_wins():
    payload, _ = iw.build_agent_payload(_agent_defn(), model="claude-sonnet-5")
    assert payload["model"] == "claude-sonnet-5"


def test_agent_payload_inherits_model_when_no_override():
    payload, _ = iw.build_agent_payload(_agent_defn(model={"id": "claude-opus-4-8", "speed": "standard"}))
    # snapshot's model shape (dict form) is passed through verbatim
    assert payload["model"] == {"id": "claude-opus-4-8", "speed": "standard"}


def test_agent_payload_name_override():
    payload, _ = iw.build_agent_payload(_agent_defn(), name="LIK Knowledge Search")
    assert payload["name"] == "LIK Knowledge Search"


def test_agent_payload_omits_empty_optional_fields():
    payload, dropped = iw.build_agent_payload(
        {"name": "Bare", "model": "claude-opus-4-8", "system": None, "mcp_servers": [], "tools": [], "skills": []}
    )
    assert dropped == []
    assert set(payload) == {"name", "model"}  # optional empties are omitted, not sent as null/[]


def test_agent_payload_drops_custom_skills_by_default():
    defn = _agent_defn(skills=[ANTHROPIC_SKILL, CUSTOM_SKILL])
    payload, dropped = iw.build_agent_payload(defn)
    assert payload["skills"] == [ANTHROPIC_SKILL]  # only the anthropic prebuilt survives
    assert dropped == [CUSTOM_SKILL]


def test_agent_payload_strict_skills_raises_on_custom():
    defn = _agent_defn(skills=[CUSTOM_SKILL])
    with pytest.raises(ValueError, match="skill_abc123"):
        iw.build_agent_payload(defn, strict_skills=True)


# --- partition_skills -------------------------------------------------------------------

def test_partition_skills_splits_by_type():
    anthropic_skills, custom = iw.partition_skills({"skills": [ANTHROPIC_SKILL, CUSTOM_SKILL]})
    assert anthropic_skills == [ANTHROPIC_SKILL]
    assert custom == [CUSTOM_SKILL]


def test_partition_skills_handles_missing_skills():
    assert iw.partition_skills({}) == ([], [])


# --- build_env_payload ------------------------------------------------------------------

def test_env_payload_copies_config_verbatim():
    config = {"type": "cloud", "networking": {"type": "limited", "allowed_hosts": ["x.example.com"]}}
    payload = iw.build_env_payload({"name": "lik-ui", "config": config, "description": "env"})
    assert payload["config"] == config
    assert payload["name"] == "lik-ui"
    assert payload["description"] == "env"


def test_env_payload_name_override():
    payload = iw.build_env_payload({"name": "lik-ui", "config": {"type": "cloud"}}, name="lik-ui-prod")
    assert payload["name"] == "lik-ui-prod"
    assert "description" not in payload  # omitted when absent


# --- format_ssm_block -------------------------------------------------------------------

def test_ssm_block_shape_and_no_trailing_space():
    block = iw.format_ssm_block("sk-ant-realkey", "agent_new", "env_new")
    lines = block.split("\n")
    assert lines[0] == "$P/lik-ui/LIK_UI_ANTHROPIC_API_KEY=sk-ant-realkey"
    assert lines[1] == "$P/lik-ui/LIK_UI_AGENTS_CONFIG=agent_new:env_new"
    for line in lines:
        assert line == line.rstrip()  # set-ssm-secrets.sh takes value verbatim; no trailing space


def test_ssm_block_placeholder_when_no_key():
    block = iw.format_ssm_block(None, "agent_new", "env_new")
    assert "LIK_UI_ANTHROPIC_API_KEY=sk-ant-…" in block
    assert "LIK_UI_AGENTS_CONFIG=agent_new:env_new" in block


# --- redact -----------------------------------------------------------------------------

def test_redact_never_reveals_full_key():
    key = "sk-ant-api03-abcdefghijklmnop-qrstuvwxyz"
    hint = iw.redact(key)
    assert key not in hint
    assert hint.startswith("sk-ant-api")
    assert iw.redact(None) == "(none)"
    assert iw.redact("short") == "sk-ant-…"


# --- resolve_target_key -----------------------------------------------------------------

def test_resolve_key_cli_wins():
    assert iw.resolve_target_key("sk-ant-cli") == "sk-ant-cli"


def test_resolve_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("LIK_UI_ANTHROPIC_API_KEY", "sk-ant-fromenv")
    assert iw.resolve_target_key(None) == "sk-ant-fromenv"


# --- create_resources -------------------------------------------------------------------

def test_create_resources_creates_env_then_agent():
    client = _FakeClient()
    agent_id, env_id = iw.create_resources(
        client, {"name": "Knowledge Search", "model": "claude-opus-4-8"}, {"name": "lik-ui", "config": {}}
    )
    assert (agent_id, env_id) == ("agent_new", "env_new")
    assert client.environments.calls and client.agents.calls  # both created


def test_create_resources_env_409_raises_and_skips_agent():
    boom = type("Boom", (Exception,), {"status_code": 409})()
    client = _FakeClient(env_exc=boom)
    with pytest.raises(iw.EnvNameConflict, match="lik-ui"):
        iw.create_resources(client, {"name": "a", "model": "m"}, {"name": "lik-ui", "config": {}})
    assert client.agents.calls == []  # agent must NOT be created after an env conflict


def test_create_resources_reraises_non_409():
    boom = type("Boom", (Exception,), {"status_code": 500})()
    client = _FakeClient(env_exc=boom)
    with pytest.raises(Exception) as excinfo:
        iw.create_resources(client, {"name": "a", "model": "m"}, {"name": "lik-ui", "config": {}})
    assert not isinstance(excinfo.value, iw.EnvNameConflict)


# --- main integration (dry-run + placeholder guard) -------------------------------------

def test_main_dry_run_prints_ssm_block_and_creates_nothing(capsys, monkeypatch):
    monkeypatch.delenv("LIK_UI_ANTHROPIC_API_KEY", raising=False)  # deterministic placeholder key line
    rc = iw.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "LIK_UI_AGENTS_CONFIG=agent_<new>:env_<new>" in out


def test_main_dry_run_notes_uncaptured_placeholder(capsys, monkeypatch):
    monkeypatch.setattr(iw, "DEFINITIONS_CAPTURED", False)
    iw.main(["--dry-run"])
    assert "PLACEHOLDER" in capsys.readouterr().out  # warns the constants aren't captured yet


def test_main_refuses_real_run_against_placeholder(monkeypatch):
    monkeypatch.setattr(iw, "DEFINITIONS_CAPTURED", False)
    with pytest.raises(SystemExit, match="placeholder"):
        iw.main(["--target-key", "sk-ant-x"])


def test_main_captured_run_requires_key(monkeypatch):
    monkeypatch.setattr(iw, "DEFINITIONS_CAPTURED", True)
    monkeypatch.delenv("LIK_UI_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="no API key"):
        iw.main([])
