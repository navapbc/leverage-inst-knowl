from lik_ui.settings import Settings
from lik_ui.sources import build_source_registry, normalize_url


def test_registry_empty_without_likmcp_config():
    assert build_source_registry(Settings(env="test")) == {}


def test_registry_has_likmcp_entry_keyed_by_normalized_url():
    s = Settings(
        env="test",
        likmcp_client_id="cid.apps.googleusercontent.com",
        likmcp_client_secret="secret",
        likmcp_resource_url="https://lik.example.com/mcp/",  # trailing slash
    )
    reg = build_source_registry(s)
    key = normalize_url("https://lik.example.com/mcp")
    assert key in reg
    cfg = reg[key]
    assert cfg.client_id == "cid.apps.googleusercontent.com"
    assert cfg.scopes == ["openid", "email"]
    assert cfg.offline is True
