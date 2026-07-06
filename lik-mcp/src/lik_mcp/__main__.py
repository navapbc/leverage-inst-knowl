from mcp.server.fastmcp import FastMCP

from .auth import FailClosedVerifier, StubVerifier
from .citations import ShapeResolver
from .db import Database
from .server import build_server
from .settings import Settings


def make_server(settings: Settings | None = None) -> FastMCP:
    settings = settings or Settings()
    db = Database(settings.conninfo)
    # Fail closed unless explicitly in local/test: the stub must never authenticate in a
    # real deployment (incl. a cloud `dev` environment).
    verifier = StubVerifier() if settings.env in {"local", "test"} else FailClosedVerifier()
    return build_server(
        db,
        verifier,
        ShapeResolver(),
        host=settings.http_host,
        port=settings.http_port,
        allowed_hosts=settings.allowed_hosts,
    )


if __name__ == "__main__":
    # Read settings once so the transport selection and the server share one config.
    settings = Settings()
    make_server(settings).run(settings.transport)
