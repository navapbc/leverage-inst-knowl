from .auth import FailClosedVerifier, StubVerifier
from .citations import ShapeResolver
from .db import Database
from .server import build_server
from .settings import Settings


def make_server():
    settings = Settings()
    db = Database(settings.conninfo)
    # Fail closed unless explicitly in dev/test: the stub must never authenticate in prod.
    verifier = StubVerifier() if settings.env in {"dev", "test"} else FailClosedVerifier()
    return build_server(db, verifier, ShapeResolver())


if __name__ == "__main__":
    make_server().run()
