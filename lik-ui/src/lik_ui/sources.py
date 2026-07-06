"""Per-source OAuth configuration registry.

Most MCP servers advertise dynamic client registration (DCR), so lik-ui self-registers a
client at runtime and needs no entry here. This registry carries a pre-configured client
ONLY for sources whose authorization server has no DCR — today that is lik-mcp, whose AS
is Google (Google has no registration endpoint). Adding a DCR-capable source later needs
no entry; adding a no-DCR source needs one.
"""

from pydantic import BaseModel

from .settings import Settings


class SourceConfig(BaseModel):
    """A pre-configured OAuth client for a no-DCR source, keyed by MCP server URL."""

    client_id: str
    client_secret: str | None = None
    scopes: list[str] = []
    offline: bool = False  # request a refresh token (offline access)


def normalize_url(url: str) -> str:
    """Canonical key form: drop a single trailing slash so declared/stored URLs match."""
    return url.rstrip("/")


def build_source_registry(settings: Settings) -> dict[str, SourceConfig]:
    registry: dict[str, SourceConfig] = {}
    if settings.likmcp_resource_url and settings.likmcp_client_id:
        registry[normalize_url(settings.likmcp_resource_url)] = SourceConfig(
            client_id=settings.likmcp_client_id,
            client_secret=settings.likmcp_client_secret or None,
            scopes=["openid", "email"],
            offline=True,
        )
    return registry
