import textwrap

import pytest
from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.settings import Settings


def test_env_prefix_and_list_property(monkeypatch):
    monkeypatch.setenv("LIK_UI_HTTP_ALLOWED_HOSTS", "localhost, 127.0.0.1 , example.com")
    monkeypatch.setenv("LIK_UI_DB_HOST", "dbhost")
    s = Settings()
    assert s.db_host == "dbhost"
    assert s.allowed_hosts == ["localhost", "127.0.0.1", "example.com"]


def test_conninfo_builds_libpq_string():
    s = Settings(db_host="h", db_port=5555, db_name="likuidb_test", db_user="u", db_password="p")
    assert "host=h port=5555 dbname=likuidb_test user=u password=p" in s.conninfo


def _roster(tmp_path, body: str):
    """Write a roster TOML to a temp file and return its path."""
    path = tmp_path / "agents.toml"
    path.write_text(textwrap.dedent(body))
    return path


def test_shipped_roster_parses_to_at_least_one_agent():
    # The default packaged agents.toml must be valid and non-empty (guards the seeded file).
    roster = Settings(env="test").agent_roster
    assert len(roster) >= 1
    assert all(e.agent_name and e.environment_name for e in roster)


def test_agent_roster_lists_configured_agents_in_file_order(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Agent X"
        environment = "Env X"

        [[agents]]
        agent = "Agent Y"
        environment = "Env Y"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(e.agent_name, e.environment_name) for e in s.agent_roster] == [
        ("Agent X", "Env X"),
        ("Agent Y", "Env Y"),
    ]


def test_agent_roster_uses_default_environment_when_omitted(tmp_path):
    path = _roster(
        tmp_path,
        """
        default_environment = "Env Default"

        [[agents]]
        agent = "Agent A"

        [[agents]]
        agent = "Agent B"
        environment = "Env Special"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(e.agent_name, e.environment_name) for e in s.agent_roster] == [
        ("Agent A", "Env Default"),  # inherits the top-level default
        ("Agent B", "Env Special"),  # own environment overrides the default
    ]


def test_agent_roster_environment_empty_when_no_default_and_none_set(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Agent A"
        """,
    )
    assert Settings(env="test", agents_config_path=path).agent_roster[0].environment_name == ""


def test_agent_roster_empty_when_file_has_no_entries(tmp_path):
    assert Settings(env="test", agents_config_path=_roster(tmp_path, "")).agent_roster == []


def test_agent_roster_empty_when_file_missing(tmp_path):
    assert Settings(env="test", agents_config_path=tmp_path / "nope.toml").agent_roster == []


def test_agent_roster_skips_entry_missing_agent_name(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        environment = "Env Orphan"

        [[agents]]
        agent = "Agent OK"
        environment = "Env OK"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(e.agent_name, e.environment_name) for e in s.agent_roster] == [("Agent OK", "Env OK")]


def test_require_production_config_raises_when_unconfigured():
    s = Settings(env="prod")  # missing session secret, oauth, api key
    with pytest.raises(RuntimeError) as exc:
        s.require_production_config()
    assert "LIK_UI_SESSION_SECRET" in str(exc.value)


def test_require_production_config_raises_on_empty_roster(tmp_path):
    # All secrets present, but the roster file is empty -> fail closed, naming the roster.
    s = Settings(
        env="prod",
        session_secret="s",
        app_oauth_client_id="id",
        app_oauth_client_secret="secret",
        anthropic_api_key="sk-ant-x",
        agents_config_path=_roster(tmp_path, ""),
    )
    with pytest.raises(RuntimeError) as exc:
        s.require_production_config()
    assert "roster" in str(exc.value)


def test_require_production_config_passes_when_stub():
    Settings(env="local").require_production_config()  # no raise


def test_app_boots_and_healthz_ok():
    app = build_app(Settings(env="test"))
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
