"""Entrypoint: ``python -m lik_ui`` serves the app with uvicorn.

Settings are read once and the same object configures both the bind address and the app,
so the transport selection and the server share one config (mirrors lik-mcp).
"""

import uvicorn

from .agents import build_agents_client
from .app import build_app
from .app_auth import GoogleOidcClient
from .chat import build_sessions_client
from .db import Database, Store
from .oauth_connector import OAuthConnector
from .settings import Settings
from .sources import build_source_registry
from .vault import build_vault_client


def build_production_app(settings: Settings):
    """Construct the app with real collaborators wired from settings."""
    store = Store(Database(settings.conninfo))
    app_oidc = GoogleOidcClient(
        client_id=settings.app_oauth_client_id,
        client_secret=settings.app_oauth_client_secret,
        discovery_url=settings.app_oidc_discovery_url,
        redirect_uri=f"{settings.app_base_url}/auth/callback",
    )
    vault_client = build_vault_client(settings)
    connector = OAuthConnector(
        store,
        build_source_registry(settings),
        redirect_uri=f"{settings.app_base_url}/connections/callback",
    )
    agents_client = build_agents_client(settings)
    sessions_client = build_sessions_client(settings)
    return build_app(
        settings,
        store=store,
        app_oidc=app_oidc,
        vault_client=vault_client,
        connector=connector,
        agents_client=agents_client,
        sessions_client=sessions_client,
    )


def main() -> None:
    settings = Settings()
    app = build_production_app(settings)
    uvicorn.run(app, host=settings.http_host, port=settings.http_port)


if __name__ == "__main__":
    main()
