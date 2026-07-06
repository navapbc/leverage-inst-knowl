"""Shared test fixtures and safety guards.

The DB-name guard refuses to run the suite against any database whose name does not end
in ``_test`` — the suite truncates tables, so pointing it at a real DB would wipe data.
"""

import os

import pytest

from lik_ui.settings import Settings


def pytest_configure(config):
    db_name = os.environ.get("LIK_UI_DB_NAME", "likuidb_test")
    if not db_name.endswith("_test"):
        raise pytest.UsageError(
            f"LIK_UI_DB_NAME={db_name!r} must end in '_test'. The suite truncates tables; "
            "refusing to run against a non-test database."
        )


@pytest.fixture
def settings() -> Settings:
    """Default local settings; individual tests override fields as needed."""
    return Settings(env="test")
