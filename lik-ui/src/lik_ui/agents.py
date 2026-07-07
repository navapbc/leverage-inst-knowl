"""Agent selection and required-connection resolution.

The set of connections a session needs is not hardcoded — it is read from the selected
agent's own definition via the Claude SDK (its declared MCP servers). lik-ui compares that
required set against the credentials already in the user's vault to show connected/missing
status and drive the connect action for each missing source.
"""

from typing import Protocol

from .settings import Settings
from .vault import VaultClient, ensure_user_vault


class AgentsClient(Protocol):
    def describe(self, agent_id: str) -> dict:
        """Return the agent's details in a single lookup:
        ``{"servers": [{"name", "url"}, ...], "system": str | None, "model": str | None}``."""
        ...


class AnthropicAgentsClient:
    """Real ``AgentsClient`` backed by the Anthropic SDK's Managed Agents API."""

    def __init__(self, api_key: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def describe(self, agent_id: str) -> dict:
        agent = self._client.beta.agents.retrieve(agent_id)
        return {
            "servers": [{"name": s.name, "url": s.url} for s in (agent.mcp_servers or [])],
            "system": agent.system,
            "model": getattr(agent.model, "id", None),
        }


def build_agents_client(settings: Settings) -> AgentsClient | None:
    if settings.is_stub:
        return None
    return AnthropicAgentsClient(settings.anthropic_api_key)


def resolve_connections(servers: list[dict], connected_urls: set[str]) -> list[dict]:
    """For each server the agent declares, mark whether the user's vault already has a
    matching credential (exact URL match, as the platform requires)."""
    return [{"name": d["name"], "url": d["url"], "connected": d["url"] in connected_urls} for d in servers]


def register_agent_routes(app) -> None:
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    from .app import templates
    from .app_auth import require_user

    @app.get("/connections", response_class=HTMLResponse)
    async def connections(request: Request, agent_id: str):
        user = require_user(request)
        settings: Settings = request.app.state.settings
        agent = next((a for a in settings.agents if a.agent_id == agent_id), None)
        if not agent:
            return HTMLResponse("Unknown agent.", status_code=404)

        try:
            vault_id = ensure_user_vault(request.app.state.store, request.app.state.vault_client, user)
            vault_client: VaultClient | None = request.app.state.vault_client
            described = request.app.state.agents_client.describe(agent_id)
            connected = vault_client.list_credential_urls(vault_id) if vault_client else set()
            conns = resolve_connections(described["servers"], connected)
        except Exception as exc:  # noqa: BLE001 - surface SDK/agent/vault errors as a page, not a 500
            return HTMLResponse(f"Could not load the agent's required connections: {exc}", status_code=502)

        return templates.TemplateResponse(
            request,
            "connections.html",
            {"user": user, "agent": agent, "connections": conns, "system_prompt": described["system"]},
        )
