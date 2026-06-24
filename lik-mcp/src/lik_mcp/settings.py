from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection + environment config. All fields come from LIK_-prefixed env vars
    (see .env.example), so test -> prod is a credentials change, not a code change."""

    model_config = SettingsConfigDict(env_prefix="LIK_", env_file=".env", extra="ignore")

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "likdb_test"
    db_user: str = "lik"
    db_password: str = "lik"
    db_sslmode: str = "prefer"

    # local | test -> StubVerifier; anything else (incl. a cloud `dev`) -> fail-closed.
    env: str = "local"

    # How the server is exposed. "stdio" (default) is spawned per-session by an MCP
    # client; "streamable-http" runs a long-lived HTTP listener (used by the container).
    # FastMCP's own host/port/path come from FASTMCP_-prefixed env vars.
    transport: str = "stdio"

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password} sslmode={self.db_sslmode}"
        )
