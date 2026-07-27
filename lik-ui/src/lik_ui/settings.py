"""Configuration for lik-ui. Everything is driven by ``LIK_UI_``-prefixed environment
variables through a single pydantic ``Settings`` object, mirroring lik-mcp's convention:
swapping test for a real deployment is a credentials change here, not a code change.

Secrets (client secrets, session key, API key) live only in the environment and are
never logged. See ``settings.require_production_config`` for the fail-closed guard that
refuses to start a real deployment with auth/vault config missing.
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# The roster file ships inside this package (see pyproject package-data), so resolving it
# relative to this module works both from source (tests) and from the installed package
# (the pip-installed container). Overridable via LIK_UI_AGENTS_CONFIG_PATH.
_DEFAULT_AGENTS_CONFIG_PATH = Path(__file__).parent / "agents.toml"

# The FAQ content ships inside this package the same way (see pyproject package-data), so the
# app can go private without a runtime GitHub fetch. Overridable via LIK_UI_FAQ_PATH (tests
# point it at a temp file).
_DEFAULT_FAQ_PATH = Path(__file__).parent / "faq.md"


class SectionDef(BaseModel):
    """One picker section declared at the top of the roster. The declaration order of these
    blocks is the order sections render in the picker. ``is_management`` marks a section whose
    agents write shared data and are therefore hidden by default (revealed by the per-user
    "show management agents" preference). This is a usability guardrail, not access control."""

    name: str
    is_management: bool = False


class AgentRosterEntry(BaseModel):
    """One roster line: which agent to offer and which environment its sessions run in, both by
    *name*. No platform ids live in the repo — GitHub is the source of truth for agents/environments
    (see docs/plans/2026-07-24-001-...), and names survive re-initializing into a new workspace
    without any id rewrite. Names are resolved to ids once at startup (see ``agents.resolve_agent_options``).

    ``section`` is the picker section this agent belongs to (empty ⇒ the default group).
    ``is_management`` is derived from the section's declaration and cached here so downstream code
    need not re-consult the section table."""

    agent_name: str
    environment_name: str
    section: str = ""
    is_management: bool = False


class AgentOption(BaseModel):
    """One selectable agent, pairing an agent id with the environment its sessions run in — the
    *resolved* form of an :class:`AgentRosterEntry` after startup name→id resolution.

    The human-readable label is not stored here — it is read from the agent's own definition
    via the Claude SDK. The user picks one of these; lik-ui then queries the agent for the MCP
    servers it declares (the required connections). The list shape lets more agents be added
    via configuration without code changes.

    ``section``/``is_management`` are display metadata carried through from the roster so the
    picker can group agents and hide management sections without a second roster read.
    """

    agent_id: str
    environment_id: str
    section: str = ""
    is_management: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIK_UI_", env_file=".env", extra="ignore")

    # --- Postgres (own store, not shared with lik-mcp) ----------------------------
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "likuidb_test"  # the test suite refuses any name not ending in _test
    db_user: str = "lik"
    db_password: str = "lik"
    db_sslmode: str = "prefer"

    # local | test -> stubbed identity/vault (no real auth). Anything else requires the
    # real app-login / vault / agent config below and refuses to start without it.
    env: str = "local"

    # --- HTTP serving --------------------------------------------------------------
    http_host: str = "127.0.0.1"
    http_port: int = 8001  # lik-mcp owns 8000; keep them distinct for local side-by-side
    http_allowed_hosts: str = "localhost,localhost:*,127.0.0.1,127.0.0.1:*"
    # Public base URL clients reach lik-ui at; OAuth callback URLs are built from this.
    app_base_url: str = "http://localhost:8001"
    # Signs the session cookie. Must be set to a strong random value outside local/test.
    session_secret: str = ""

    # --- App login: identity-only Google OIDC client (separate from data sources) --
    app_oauth_client_id: str = ""
    app_oauth_client_secret: str = ""
    # Google's OIDC discovery document; endpoints are read from it rather than hardcoded.
    app_oidc_discovery_url: str = "https://accounts.google.com/.well-known/openid-configuration"

    # --- lik-mcp data connection: pre-configured Google client (no DCR) ------------
    # Reuse the SAME client id lik-mcp validates as the token audience; a different client
    # produces a silent 401 at the server. Secret supplied via env, never in code.
    likmcp_client_id: str = ""
    likmcp_client_secret: str = ""
    # Must exactly equal lik-mcp's LIK_RESOURCE_SERVER_URL; the vault credential is keyed
    # by this URL and a mismatch means the token is silently not injected.
    likmcp_resource_url: str = ""

    # --- Google Drive data connection: pre-configured Google client (no DCR) -------
    # Same shape as the lik-mcp connection: Google is the authorization server and has no
    # dynamic client registration, so the client is pre-configured and keyed by the MCP
    # server URL the agent declares. Must exactly equal that declared URL.
    gdrivemcp_client_id: str = ""
    gdrivemcp_client_secret: str = ""
    gdrivemcp_resource_url: str = ""

    # --- GitHub data connection: pre-configured OAuth app (no DCR) -----------------
    # GitHub is the authorization server and offers no dynamic client registration, so
    # the client is pre-configured and keyed by the MCP server URL the agent declares.
    # Must exactly equal that declared URL.
    github_client_id: str = ""
    github_client_secret: str = ""
    github_resource_url: str = ""

    # --- Slack data connection: pre-configured OAuth app (no DCR) ------------------
    # Slack is the authorization server and offers no dynamic client registration, so the
    # client is pre-configured and keyed by the MCP server URL the agent declares. Must
    # exactly equal that declared URL (https://mcp.slack.com/mcp).
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_resource_url: str = ""

    # --- Anthropic / Managed Agents ------------------------------------------------
    anthropic_api_key: str = ""
    # How long (seconds) to cache each agent's SDK ``describe`` result. The picker and
    # connections page fetch one agent definition per load, but definitions only change on
    # redeploy, so a short cache collapses bursts of loads into one fetch per agent. 0 disables
    # caching (always fetch). A redeploy restarts the process and clears the cache regardless.
    agent_describe_ttl: int = 60

    # --- Repo links (GitHub "view on GitHub" affordance) ---------------------------
    # The repo slug + ref used to build blob URLs for the connections page's skill links
    # and the FAQ source link. Nothing is fetched from GitHub at runtime — these only
    # construct human-facing links (which resolve for viewers with repo access, so the
    # repo can be private). Point at a fork/branch to link a preview without a code change.
    skills_repo: str = "navapbc/leverage-inst-knowl"
    skills_ref: str = "main"

    # The bundled FAQ content, read locally at request time (see _DEFAULT_FAQ_PATH). Tests
    # override it with a temp file.
    faq_path: Path = _DEFAULT_FAQ_PATH

    # --- Agent registry ------------------------------------------------------------
    # Agents to offer live in a checked-in TOML file (``[[agents]]`` blocks), exposed as a
    # name roster via ``agent_roster``. Entries name the agent and its environment; the ids are
    # resolved from those names at startup (``agents.resolve_agent_options``), so no platform ids
    # live in the repo. Each agent's label is read from its own definition via the SDK. The path
    # defaults to the packaged ``agents.toml``; tests override it with a temp file.
    agents_config_path: Path = _DEFAULT_AGENTS_CONFIG_PATH

    @property
    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.http_allowed_hosts.split(",") if h.strip()]

    def _roster_data(self) -> dict:
        """Load and parse the roster TOML once. A missing file yields ``{}`` (the production guard
        turns an empty roster into a loud startup failure); malformed TOML raises."""
        path = Path(self.agents_config_path)
        if not path.is_file():
            return {}
        with path.open("rb") as fh:
            return tomllib.load(fh)

    @property
    def agent_sections(self) -> list[SectionDef]:
        """The picker sections declared at the top of the roster, in declaration order (which is
        also their display order). Empty when the roster declares no ``[[sections]]`` — agents then
        all fall into the default group."""
        sections = []
        for section in self._roster_data().get("sections", []):
            name = str(section.get("name", "")).strip()
            if name:
                sections.append(SectionDef(name=name, is_management=bool(section.get("management", False))))
        return sections

    @property
    def agent_roster(self) -> list[AgentRosterEntry]:
        """Parse the roster TOML into ``AgentRosterEntry``s (names, not ids). A top-level
        ``default_environment`` applies to any agent that omits its own ``environment``. Each agent's
        ``section`` maps to a top-level ``[[sections]]`` block; ``is_management`` is copied from that
        block (an agent whose section is undeclared falls into the default group, non-management).
        A missing file yields an empty list (the production guard turns that into a loud startup
        failure); malformed TOML raises. Name→id resolution happens later, at startup, via the SDK."""
        data = self._roster_data()
        default_env = str(data.get("default_environment", "")).strip()
        management_sections = {s.name for s in self.agent_sections if s.is_management}
        entries = []
        for entry in data.get("agents", []):
            agent_name = str(entry.get("agent", "")).strip()
            environment_name = str(entry.get("environment", "")).strip() or default_env
            section = str(entry.get("section", "")).strip()
            if agent_name:
                entries.append(AgentRosterEntry(
                    agent_name=agent_name,
                    environment_name=environment_name,
                    section=section,
                    is_management=section in management_sections,
                ))
        return entries

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password} sslmode={self.db_sslmode}"
        )

    @property
    def is_stub(self) -> bool:
        """True in local/test, where identity and vault access are stubbed."""
        return self.env in {"local", "test"}

    def require_production_config(self) -> None:
        """Fail closed: outside local/test, refuse to start when the auth, vault, or agent
        config a real deployment needs is missing — rather than silently running open."""
        if self.is_stub:
            return
        missing = [
            name
            for name, value in {
                "LIK_UI_SESSION_SECRET": self.session_secret,
                "LIK_UI_APP_OAUTH_CLIENT_ID": self.app_oauth_client_id,
                "LIK_UI_APP_OAUTH_CLIENT_SECRET": self.app_oauth_client_secret,
                "LIK_UI_ANTHROPIC_API_KEY": self.anthropic_api_key,
            }.items()
            if not value
        ]
        if not self.agent_roster:
            missing.append(f"a non-empty agent roster in {self.agents_config_path}")
        if missing:
            raise RuntimeError(
                f"LIK_UI_ENV={self.env!r} requires {', '.join(missing)} to be set. "
                "Refusing to start without real auth/vault/agent config."
            )
