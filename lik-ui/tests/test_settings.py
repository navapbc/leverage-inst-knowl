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


def test_agents_empty_without_agent_id():
    assert Settings(env="test").agents == []


def test_agents_lists_configured_agent():
    s = Settings(env="test", default_agent_id="agent_x", default_environment_id="env_y")
    agents = s.agents
    assert len(agents) == 1
    assert agents[0].agent_id == "agent_x"
    assert agents[0].environment_id == "env_y"


def test_require_production_config_raises_when_unconfigured():
    s = Settings(env="prod")  # missing session secret, oauth, api key, agent
    with pytest.raises(RuntimeError) as exc:
        s.require_production_config()
    assert "LIK_UI_SESSION_SECRET" in str(exc.value)


def test_require_production_config_passes_when_stub():
    Settings(env="local").require_production_config()  # no raise


def test_app_boots_and_healthz_ok():
    app = build_app(Settings(env="test"))
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
