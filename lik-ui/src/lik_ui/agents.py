"""Agent selection and required-connection resolution.

The set of connections a session needs is not hardcoded — it is read from the selected
agent's own definition via the Claude SDK (its declared MCP servers). lik-ui compares that
required set against the credentials already in the user's vault to show connected/missing
status and drive the connect action for each missing source.
"""

from typing import Protocol

from .settings import Settings
from .skill_docs import fetch_skill_instructions, skill_source_url
from .sources import normalize_url
from .vault import VaultClient, ensure_user_vault


class AgentsClient(Protocol):
    def describe(self, agent_id: str) -> dict:
        """Return the agent's details in a single lookup: ``{"name": str | None,
        "servers": [{"name", "url", "permission_policy"}, ...], "system": str | None,
        "model": str | None, "skills": [{"id", "type", "version"}, ...], "version": str | None}``.
        ``permission_policy`` is the server-side gate the agent applies to that MCP's calls
        (e.g. "always_allow", "ask"), or ``None`` when unknown."""
        ...

    def describe_skill(self, skill_id: str, version: str) -> dict:
        """Return a skill version's human-readable details: ``{"name": str, "description": str}``.
        The agent definition only carries a skill's id/version; its name and description live on
        the skill version and are fetched on demand. (The full SKILL.md is not part of this
        lookup — the ``/skill-details`` endpoint fetches it from the public GitHub repo by
        skill name; see ``skill_docs.py``.)"""
        ...


class AnthropicAgentsClient:
    """Real ``AgentsClient`` backed by the Anthropic SDK's Managed Agents API."""

    def __init__(self, api_key: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    @staticmethod
    def _server_policies(agent) -> dict:
        """Map each MCP server name to its toolset's default permission-policy type (e.g.
        "always_allow", "ask"). The policy lives on the agent's ``mcp_toolset`` tools, keyed by
        ``mcp_server_name`` — not on the ``mcp_servers`` list itself."""
        policies: dict[str, str | None] = {}
        for t in getattr(agent, "tools", None) or []:
            name = getattr(t, "mcp_server_name", None)
            if getattr(t, "type", None) == "mcp_toolset" and name:
                policy = getattr(getattr(t, "default_config", None), "permission_policy", None)
                policies[name] = getattr(policy, "type", None)
        return policies

    def describe(self, agent_id: str) -> dict:
        agent = self._client.beta.agents.retrieve(agent_id)
        policies = self._server_policies(agent)
        return {
            "name": agent.name,
            "servers": [
                {"name": s.name, "url": s.url, "permission_policy": policies.get(s.name)}
                for s in (agent.mcp_servers or [])
            ],
            "system": agent.system,
            "model": getattr(agent.model, "id", None),
            "skills": [
                {"id": s.skill_id, "type": s.type, "version": s.version} for s in (agent.skills or [])
            ],
            "version": getattr(agent, "version", None),
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
    matching credential. Compare on the normalized URL: the vault platform stores the
    server URL with a trailing slash stripped, so a slash-terminated declared URL (e.g.
    GitHub's ``.../mcp/``) would never match its stored form under a raw equality check."""
    connected_norm = {normalize_url(u) for u in connected_urls}
    return [
        {"name": d["name"], "url": d["url"], "connected": normalize_url(d["url"]) in connected_norm}
        for d in servers
    ]


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

    @app.get("/skill-details")
    async def skill_details(request: Request, skill_id: str, version: str):
        require_user(request)  # gate behind login, same as the connections page
        try:
            details = request.app.state.agents_client.describe_skill(skill_id, version)
        except Exception as exc:  # noqa: BLE001 - surface SDK errors as JSON, not a 500
            return JSONResponse({"detail": f"Could not load skill: {exc}"}, status_code=502)
        # The full SKILL.md is read from the public GitHub repo by skill name (which equals the
        # skill's directory). source_url is always present (the "view on GitHub" affordance and
        # the fallback link); instructions is None when the fetch failed — the page degrades to
        # the fallback rather than erroring.
        settings: Settings = request.app.state.settings
        details["source_url"] = skill_source_url(details["name"], settings)
        details["instructions"] = await fetch_skill_instructions(details["name"], settings)
        return JSONResponse(details)
