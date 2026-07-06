"""Entrypoint: ``python -m lik_ui`` serves the app with uvicorn.

Settings are read once and the same object configures both the bind address and the app,
so the transport selection and the server share one config (mirrors lik-mcp).
"""

import uvicorn

from .app import build_app
from .settings import Settings


def main() -> None:
    settings = Settings()
    app = build_app(settings)
    uvicorn.run(app, host=settings.http_host, port=settings.http_port)


if __name__ == "__main__":
    main()
