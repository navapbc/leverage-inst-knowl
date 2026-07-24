"""FastAPI application factory. Wires middleware, templates, and routers.

Routers for the individual concerns (app login, connections, agents, chat) are added by
their own modules in later units; this factory is the single place they are mounted.
"""

import logging
import traceback as traceback_mod
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .settings import Settings

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _PKG_DIR / "templates"
STATIC_DIR = _PKG_DIR / "static"

# Shared template renderer. Modules import this to render their pages so every page uses
# one Jinja environment rooted at the package's templates/ directory.
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def build_app(
    settings: Settings | None = None,
    *,
    store=None,
    app_oidc=None,
    vault_client=None,
    connector=None,
    agents_client=None,
    sessions_client=None,
) -> FastAPI:
    """Build the FastAPI app. Collaborators are injected so tests can substitute fakes;
    ``__main__`` wires the real ones."""
    settings = settings or Settings()
    settings.require_production_config()

    app = FastAPI(title="lik-ui")
    app.state.settings = settings
    app.state.store = store
    app.state.app_oidc = app_oidc
    app.state.vault_client = vault_client
    app.state.connector = connector
    app.state.agents_client = agents_client
    app.state.sessions_client = sessions_client

    # Session cookie holds the signed app identity + transient OAuth flow state. Outside
    # local/test the secret is required (enforced by require_production_config above); the
    # dev fallback keeps local boot frictionless without shipping a real key.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret or "dev-insecure-session-key",
        same_site="lax",
        https_only=not settings.is_stub,
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception):
        """Replace Starlette's opaque "Internal Server Error" with a descriptive page.

        The full traceback is always logged server-side; it is shown in the browser only in
        local/test, where there are no real secrets to leak, so a developer sees the cause
        without reading the server logs."""
        logger.exception("Unhandled error serving %s %s", request.method, request.url.path)
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "error_type": type(exc).__name__,
                "error_message": str(exc) or "(no message)",
                "traceback": (
                    "".join(traceback_mod.format_exception(exc)) if settings.is_stub else None
                ),
            },
            status_code=500,
        )

    # Register feature routers. Imported here (not at module top) to keep the import graph
    # acyclic — these modules import `templates` from this module.
    from .account import register_account_routes
    from .agents import register_agent_routes
    from .app_auth import register_auth_routes
    from .chat import register_chat_routes
    from .faq import register_faq_routes
    from .oauth_connector import register_connection_routes

    register_auth_routes(app)
    register_connection_routes(app)
    register_agent_routes(app)
    register_chat_routes(app)
    register_account_routes(app)
    register_faq_routes(app)

    return app
