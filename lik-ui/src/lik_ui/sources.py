"""Per-source OAuth configuration registry.

Most MCP servers advertise dynamic client registration (DCR), so lik-ui self-registers a
client at runtime and needs no entry here. This registry carries a pre-configured client
ONLY for sources whose authorization server has no DCR — today those are lik-mcp and
Google Drive (both fronted by Google as the AS) and GitHub, none of which expose a
registration endpoint. Adding a DCR-capable source later needs no entry; adding a
no-DCR source needs one.
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
    # One entry per no-DCR source; a source is included only when both its URL and client
    # id are configured. Each is keyed by the MCP server URL the agent declares.
    declared = [
        (settings.likmcp_resource_url, settings.likmcp_client_id, settings.likmcp_client_secret,
         ["openid", "email"]),
        (settings.gdrivemcp_resource_url, settings.gdrivemcp_client_id, settings.gdrivemcp_client_secret,
         ["openid", "email", "https://www.googleapis.com/auth/drive.readonly"]),
        # Read-focused GitHub access: repo + org + user identity. An empty scope yields a
        # token the GitHub MCP server rejects with 403, so request what the resource needs.
        # (GitHub's `repo` scope is read/write — there is no read-only private-repo scope.)
        (settings.github_resource_url, settings.github_client_id, settings.github_client_secret,
         ["repo", "read:org", "read:user"]),
    ]
    registry: dict[str, SourceConfig] = {}
    for resource_url, client_id, client_secret, scopes in declared:
        if resource_url and client_id:
            registry[normalize_url(resource_url)] = SourceConfig(
                client_id=client_id,
                client_secret=client_secret or None,
                scopes=scopes,
                offline=True,
            )
    return registry
