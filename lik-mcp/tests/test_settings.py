"""Transport selection settings (U1). These read only env vars, so no DB is needed."""

from lik_mcp.settings import Settings


def test_transport_defaults_to_stdio(monkeypatch):
    """No LIK_TRANSPORT set -> stdio, so `uv run python -m lik_mcp` and the test
    fixtures keep their spawned-per-session behavior."""
    monkeypatch.delenv("LIK_TRANSPORT", raising=False)
    assert Settings(_env_file=None).transport == "stdio"


def test_transport_reads_lik_transport_env(monkeypatch):
    """The container sets LIK_TRANSPORT=streamable-http to run the HTTP listener."""
    monkeypatch.setenv("LIK_TRANSPORT", "streamable-http")
    assert Settings(_env_file=None).transport == "streamable-http"


def test_transport_env_is_case_insensitive(monkeypatch):
    """LIK_-prefixed settings are case-insensitive (pydantic-settings default), so a
    lowercased var name still resolves."""
    monkeypatch.delenv("LIK_TRANSPORT", raising=False)
    monkeypatch.setenv("lik_transport", "streamable-http")
    assert Settings(_env_file=None).transport == "streamable-http"
