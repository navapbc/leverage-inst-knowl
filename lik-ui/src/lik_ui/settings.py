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


class AgentOption(BaseModel):
    """One selectable agent, pairing an agent id with the environment its sessions run in.

    The human-readable label is not stored here — it is read from the agent's own definition
    via the Claude SDK. The user picks one of these; lik-ui then queries the agent for the MCP
    servers it declares (the required connections). The list shape lets more agents be added
    via configuration without code changes.
    """

    agent_id: str
    environment_id: str


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

    # --- Skill instructions source (public GitHub repo) ----------------------------
    # A skill's full SKILL.md is fetched from this repo's raw content by skill name;
    # the repo is public, so no token is needed. Point at a fork/branch to preview
    # without a code change. The path is always .claude/skills/<name>/SKILL.md.
    skills_repo: str = "navapbc/leverage-inst-knowl"
    skills_ref: str = "main"

    # --- Agent registry ------------------------------------------------------------
    # Agents to offer live in a checked-in TOML file (``[[agents]]`` blocks), exposed as a
    # list via ``agents``. Each agent's label is read from its own definition via the SDK.
    # The path defaults to the packaged ``agents.toml``; tests override it with a temp file.
    agents_config_path: Path = _DEFAULT_AGENTS_CONFIG_PATH

    @property
    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.http_allowed_hosts.split(",") if h.strip()]

    @property
    def agents(self) -> list[AgentOption]:
        """Parse the roster TOML into ``AgentOption``s. A top-level ``default_environment_id``
        applies to any agent that omits its own ``environment_id``. A missing file yields an
        empty list (the production guard turns that into a loud startup failure); malformed
        TOML raises."""
        path = Path(self.agents_config_path)
        if not path.is_file():
            return []
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        default_env = str(data.get("default_environment_id", "")).strip()
        options = []
        for entry in data.get("agents", []):
            agent_id = str(entry.get("agent_id", "")).strip()
            environment_id = str(entry.get("environment_id", "")).strip() or default_env
            if agent_id:
                options.append(AgentOption(agent_id=agent_id, environment_id=environment_id))
        return options

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
        if not self.agents:
            missing.append(f"a non-empty agent roster in {self.agents_config_path}")
        if missing:
            raise RuntimeError(
                f"LIK_UI_ENV={self.env!r} requires {', '.join(missing)} to be set. "
                "Refusing to start without real auth/vault/agent config."
            )
