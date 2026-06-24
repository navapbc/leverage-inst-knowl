import pathlib

import pytest

from lik_mcp.auth import StubVerifier
from lik_mcp.citations import ShapeResolver
from lik_mcp.db import Database
from lik_mcp.server import build_server
from lik_mcp.settings import Settings

INIT_SQL = pathlib.Path(__file__).resolve().parents[1] / "db" / "init.sql"


def pytest_configure(config):
    """Hard gate: the suite TRUNCATEs catalog/confirmations, so the target database
    must identify itself as disposable. LIK_DB_NAME must end in '_test' — the deployed
    DB (e.g. 'likdb') can never match, no matter how LIK_ENV is set."""
    settings = Settings()
    if not settings.db_name.endswith("_test"):
        raise pytest.UsageError(
            f"Refusing to run tests against LIK_DB_NAME={settings.db_name!r}: this "
            "suite TRUNCATEs catalog and confirmations, so the database name must end "
            "in '_test' to mark it disposable. Point LIK_DB_* at a throwaway DB "
            "(e.g. the docker compose one) — never the deployed DB."
        )


@pytest.fixture(scope="session")
def settings():
    return Settings()


@pytest.fixture(scope="session")
def db(settings):
    """Connect to the test Postgres and apply the idempotent schema. Skips the suite
    (rather than erroring) when no DB is reachable, with a hint to start Docker."""
    try:
        database = Database(settings.conninfo)
        with database.connection() as conn:
            conn.execute(INIT_SQL.read_text())  # multi-statement: simple-query protocol
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - any connection/setup failure -> skip
        pytest.skip(f"Test Postgres not reachable ({exc}). Run `docker compose up -d` first.")
    yield database
    database.close()


@pytest.fixture(autouse=True)
def clean(db, settings):
    assert settings.db_name.endswith("_test")  # defense in depth: only TRUNCATE a disposable DB
    with db.connection() as conn:
        conn.execute("TRUNCATE catalog, confirmations RESTART IDENTITY")
        conn.commit()
    yield


@pytest.fixture
def verifier():
    return StubVerifier()


@pytest.fixture
def resolver():
    return ShapeResolver()


@pytest.fixture
def server(db, verifier, resolver):
    return build_server(db, verifier, resolver)
