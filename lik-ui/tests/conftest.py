"""Shared test fixtures and safety guards.

The DB-name guard refuses to run the suite against any database whose name does not end
in ``_test`` — the suite truncates tables, so pointing it at a real DB would wipe data.
"""

import pathlib

import pytest

from lik_ui.db import Database, Store
from lik_ui.settings import Settings

INIT_SQL = pathlib.Path(__file__).resolve().parents[1] / "db" / "init.sql"

_TABLES = "users, user_vaults, sessions"


def pytest_configure(config):
    # Tests must not read the developer's .env — otherwise real agent/source/production
    # config leaks into Settings(env="test") and breaks the "unconfigured" assertions. Test
    # config comes from explicit LIK_UI_* env vars (see README) or the field defaults.
    Settings.model_config["env_file"] = None

    if not Settings().db_name.endswith("_test"):
        raise pytest.UsageError(
            f"LIK_UI_DB_NAME={Settings().db_name!r} must end in '_test'. The suite truncates "
            "tables; refusing to run against a non-test database."
        )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(env="test")


@pytest.fixture(scope="session")
def db(settings):
    """Connect to the test Postgres and apply the idempotent schema. Skips the suite
    (rather than erroring) when no DB is reachable, with a hint to start Docker."""
    try:
        database = Database(settings.conninfo)
        with database.connection() as conn:
            conn.execute(INIT_SQL.read_text())
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - any connection/setup failure -> skip
        pytest.skip(f"Test Postgres not reachable ({exc}). Run `docker compose up -d db` first.")
    yield database
    database.close()


@pytest.fixture(autouse=True)
def clean(db, settings):
    assert settings.db_name.endswith("_test")  # defense in depth
    with db.connection() as conn:
        conn.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
        conn.commit()
    yield


@pytest.fixture
def store(db) -> Store:
    return Store(db)
