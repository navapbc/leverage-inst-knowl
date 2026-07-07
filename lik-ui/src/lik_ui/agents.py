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
        """Return the agent's details in a single lookup: ``{"name": str | None,
        "servers": [{"name", "url"}, ...], "system": str | None, "model": str | None,
        "skills": [{"id", "type", "version"}, ...]}``."""
        ...

    def describe_skill(self, skill_id: str, version: str) -> dict:
        """Return a skill version's human-readable details: ``{"name": str, "description": str}``.
        The agent definition only carries a skill's id/version; its name and description live on
        the skill version and are fetched on demand. (Full instructions/SKILL.md are not shown yet
        — see the README TODO on the download credential limitation.)"""
        ...


class AnthropicAgentsClient:
    """Real ``AgentsClient`` backed by the Anthropic SDK's Managed Agents API."""

    def __init__(self, api_key: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def describe(self, agent_id: str) -> dict:
        agent = self._client.beta.agents.retrieve(agent_id)
        return {
            "name": agent.name,
            "servers": [{"name": s.name, "url": s.url} for s in (agent.mcp_servers or [])],
            "system": agent.system,
            "model": getattr(agent.model, "id", None),
            "skills": [
                {"id": s.skill_id, "type": s.type, "version": s.version} for s in (agent.skills or [])
            ],
        }

    def describe_skill(self, skill_id: str, version: str) -> dict:
        # An agent may pin a skill to "latest" rather than a concrete version, but the version
        # lookup (which carries name/description) requires a numeric timestamp, so resolve it.
        if not version.isdigit():
            version = self._client.beta.skills.retrieve(skill_id).latest_version
        v = self._client.beta.skills.versions.retrieve(version, skill_id=skill_id)
        return {"name": v.name, "description": v.description}


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
    from fastapi.responses import HTMLResponse, JSONResponse

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
            {
                "user": user,
                "agent": agent,
                "agent_label": described["name"] or agent.agent_id,
                "connections": conns,
                "all_connected": all(c["connected"] for c in conns),
                "system_prompt": described["system"],
                "skills": described.get("skills", []),
            },
        )

    @app.get("/connections/skill")
    async def skill_details(request: Request, skill_id: str, version: str):
        require_user(request)  # gate behind login, same as the connections page
        try:
            details = request.app.state.agents_client.describe_skill(skill_id, version)
        except Exception as exc:  # noqa: BLE001 - surface SDK errors as JSON, not a 500
            return JSONResponse({"detail": f"Could not load skill: {exc}"}, status_code=502)
        return JSONResponse(details)
