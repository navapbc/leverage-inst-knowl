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
    agents = Settings(env="test").agents
    assert len(agents) >= 1
    assert all(a.agent_id and a.environment_id for a in agents)


def test_agents_lists_configured_agents_in_file_order(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent_id = "agent_x"
        environment_id = "env_x"

        [[agents]]
        agent_id = "agent_y"
        environment_id = "env_y"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(a.agent_id, a.environment_id) for a in s.agents] == [
        ("agent_x", "env_x"),
        ("agent_y", "env_y"),
    ]


def test_agents_empty_when_file_has_no_entries(tmp_path):
    assert Settings(env="test", agents_config_path=_roster(tmp_path, "")).agents == []


def test_agents_empty_when_file_missing(tmp_path):
    assert Settings(env="test", agents_config_path=tmp_path / "nope.toml").agents == []


def test_agents_skips_entry_missing_agent_id(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        environment_id = "env_orphan"

        [[agents]]
        agent_id = "agent_ok"
        environment_id = "env_ok"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(a.agent_id, a.environment_id) for a in s.agents] == [("agent_ok", "env_ok")]


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
