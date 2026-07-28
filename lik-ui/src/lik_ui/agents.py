"""Agent selection and required-connection resolution.

The set of connections a session needs is not hardcoded — it is read from the selected
agent's own definition via the Claude SDK (its declared MCP servers). lik-ui compares that
required set against the credentials already in the user's vault to show connected/missing
status and drive the connect action for each missing source.
"""

import threading
import time
from typing import Protocol

from .settings import AgentOption, Settings
from .skill_docs import skill_source_url
from .sources import normalize_url
from .vault import VaultClient, ensure_user_vault


class AgentsClient(Protocol):
    def resolve_agent_id(self, name: str) -> str:
        """Return the platform id of the agent whose name equals ``name``. Raises if there is no
        match or more than one — by-name resolution must be unambiguous."""
        ...

    def resolve_environment_id(self, name: str) -> str:
        """Return the platform id of the environment whose name equals ``name``. Raises if there is
        no match or more than one."""
        ...

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
    def _resolve_id_by_name(items, name: str, kind: str) -> str:
        """Return the single item's id whose ``name`` equals ``name``. Raises on zero or multiple
        matches — by-name resolution must be unambiguous, and a silent miss would blank the picker."""
        matches = [it for it in items if getattr(it, "name", None) == name]
        if not matches:
            raise ValueError(f"no {kind} named {name!r} on the platform — deploy it first")
        if len(matches) > 1:
            raise ValueError(f"multiple {kind}s named {name!r} on the platform — names must be unique")
        return matches[0].id

    def resolve_agent_id(self, name: str) -> str:
        return self._resolve_id_by_name(list(self._client.beta.agents.list()), name, "agent")

    def resolve_environment_id(self, name: str) -> str:
        return self._resolve_id_by_name(list(self._client.beta.environments.list()), name, "environment")

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


class CachingAgentsClient:
    """Wraps an ``AgentsClient`` and memoizes ``describe(agent_id)`` for a short TTL.

    The home picker and connections page call ``describe`` on every load — one SDK ``retrieve``
    per configured agent — but an agent's definition only changes on redeploy, so the repeated
    lookups are almost entirely redundant. This decorator collapses a burst of loads into at most
    one underlying fetch per agent per TTL window. Every other method delegates straight through;
    only ``describe`` is cached. A ``ttl_seconds`` of 0 disables caching (always fetch), preserving
    the pre-cache behavior. Expiry keys off ``time.monotonic()`` so a wall-clock adjustment can't
    skew it. A redeploy restarts the process and empties the cache, so there is no manual bust."""

    def __init__(self, delegate: AgentsClient, ttl_seconds: int):
        self._delegate = delegate
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # agent_id -> (value, expires_at monotonic seconds)
        self._cache: dict[str, tuple[dict, float]] = {}

    def resolve_agent_id(self, name: str) -> str:
        return self._delegate.resolve_agent_id(name)

    def resolve_environment_id(self, name: str) -> str:
        return self._delegate.resolve_environment_id(name)

    def describe(self, agent_id: str) -> dict:
        if self._ttl <= 0:
            return self._delegate.describe(agent_id)
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(agent_id)
            if entry is not None and entry[1] > now:
                return entry[0]
        # Fetch outside the lock so a slow SDK call doesn't serialize every describe. Callers treat
        # the returned dict as read-only, so the shared instance is safe to hand back uncopied.
        value = self._delegate.describe(agent_id)
        with self._lock:
            self._cache[agent_id] = (value, time.monotonic() + self._ttl)
        return value

    def describe_skill(self, skill_id: str, version: str) -> dict:
        return self._delegate.describe_skill(skill_id, version)


def build_agents_client(settings: Settings) -> AgentsClient | None:
    if settings.is_stub:
        return None
    delegate = AnthropicAgentsClient(settings.anthropic_api_key)
    return CachingAgentsClient(delegate, settings.agent_describe_ttl)


def resolve_agent_options(settings: Settings, agents_client: AgentsClient | None) -> list[AgentOption]:
    """Resolve the name roster (``settings.agent_roster``) into ``AgentOption``s with concrete
    platform ids, once at startup. Returns an empty list when there is no client (local/test stub),
    so the app still boots. Any unresolved name raises — in production that surfaces as a loud
    startup failure rather than a silently empty agent picker. Downstream code (routes, session
    creation) consumes the resulting ids exactly as before."""
    if agents_client is None:
        return []
    options: list[AgentOption] = []
    for entry in settings.agent_roster:
        agent_id = agents_client.resolve_agent_id(entry.agent_name)
        environment_id = agents_client.resolve_environment_id(entry.environment_name)
        options.append(AgentOption(
            agent_id=agent_id,
            environment_id=environment_id,
            section=entry.section,
            is_management=entry.is_management,
            user_prompt=entry.user_prompt,
            agent_name=entry.agent_name,
            schedulable=entry.schedulable,
            auto_approve=entry.auto_approve,
            max_runtime=entry.max_runtime,
        ))
    return options


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
        # Resolved at startup (name→id); the URL surface is still keyed by the concrete agent_id.
        agent = next((a for a in request.app.state.agents if a.agent_id == agent_id), None)
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
                "agent_version": described.get("version"),
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
        # The full instructions are not shown in-app; instead we surface source_url — the blob link
        # to the skill's SKILL.md in the repo (the "view on GitHub" affordance). The linked source is
        # the repo copy and may not exactly match what is currently deployed to the running agent.
        settings: Settings = request.app.state.settings
        details["source_url"] = skill_source_url(details["name"], settings)
        return JSONResponse(details)
