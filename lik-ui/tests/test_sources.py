from lik_ui.settings import Settings
from lik_ui.sources import build_source_registry, normalize_url


def test_registry_empty_without_configured_sources():
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


def test_registry_has_gdrive_entry_with_drive_scope():
    s = Settings(
        env="test",
        gdrivemcp_client_id="gcid.apps.googleusercontent.com",
        gdrivemcp_client_secret="gsecret",
        gdrivemcp_resource_url="https://drive.example.com/mcp/",  # trailing slash
    )
    reg = build_source_registry(s)
    key = normalize_url("https://drive.example.com/mcp")
    assert key in reg
    cfg = reg[key]
    assert cfg.client_id == "gcid.apps.googleusercontent.com"
    assert cfg.scopes == ["openid", "email", "https://www.googleapis.com/auth/drive.readonly"]
    assert cfg.offline is True


def test_registry_has_github_entry_with_read_scopes():
    s = Settings(
        env="test",
        github_client_id="Ov23liExample",
        github_client_secret="ghsecret",
        github_resource_url="https://api.githubcopilot.com/mcp/",  # trailing slash
    )
    reg = build_source_registry(s)
    key = normalize_url("https://api.githubcopilot.com/mcp")
    assert key in reg
    cfg = reg[key]
    assert cfg.client_id == "Ov23liExample"
    # Empty scopes make the GitHub MCP server 403; request the read set it needs.
    assert cfg.scopes == ["repo", "read:org", "read:user"]


def test_registry_holds_both_sources_independently():
    s = Settings(
        env="test",
        likmcp_client_id="lik.apps.googleusercontent.com",
        likmcp_resource_url="https://lik.example.com/mcp",
        gdrivemcp_client_id="gdrive.apps.googleusercontent.com",
        gdrivemcp_resource_url="https://drive.example.com/mcp",
    )
    reg = build_source_registry(s)
    assert set(reg) == {"https://lik.example.com/mcp", "https://drive.example.com/mcp"}
