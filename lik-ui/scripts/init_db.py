#!/usr/bin/env python3
"""Apply db/init.sql to the configured lik-ui database.

Reads the same LIK_UI_-prefixed config the app uses (env vars or .env), so it targets whatever
settings.py resolves. The schema — including the non-destructive auto_delete_at migration — is
idempotent, so this is safe to re-run. Use it to initialize/migrate a deployed DB that never ran
the Docker entrypoint (e.g. the managed prod Postgres):

    uv run python scripts/init_db.py
    LIK_UI_DB_HOST=prod-db ... LIK_UI_DB_SSLMODE=require uv run python scripts/init_db.py

It only creates schema and applies non-destructive ALTERs; it never drops or truncates.
"""

import pathlib
import sys

import psycopg

from lik_ui.settings import Settings

INIT_SQL = pathlib.Path(__file__).resolve().parents[1] / "db" / "init.sql"


def main() -> int:
    settings = Settings()
    print(
        f"Applying {INIT_SQL.name} to {settings.db_user}@{settings.db_host}:"
        f"{settings.db_port}/{settings.db_name} (sslmode={settings.db_sslmode})"
    )
    try:
        with psycopg.connect(settings.conninfo, autocommit=True, connect_timeout=10) as conn:
            conn.execute(INIT_SQL.read_text())  # multi-statement: simple-query protocol
            tables = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print("Schema applied. Public tables: " + ", ".join(t[0] for t in tables))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
