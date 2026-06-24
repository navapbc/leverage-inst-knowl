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

    # dev | test -> StubVerifier; anything else -> fail-closed (no real verifier built yet).
    env: str = "dev"

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password} sslmode={self.db_sslmode}"
        )
