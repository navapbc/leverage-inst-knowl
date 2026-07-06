"""FastAPI application factory. Wires middleware, templates, and routers.

Routers for the individual concerns (app login, connections, agents, chat) are added by
their own modules in later units; this factory is the single place they are mounted.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .settings import Settings

_PKG_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _PKG_DIR / "templates"
STATIC_DIR = _PKG_DIR / "static"

# Shared template renderer. Modules import this to render their pages so every page uses
# one Jinja environment rooted at the package's templates/ directory.
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.require_production_config()

    app = FastAPI(title="lik-ui")
    app.state.settings = settings

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

    return app
