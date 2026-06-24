#!/usr/bin/env python3
"""Apply db/init.sql to the configured database.

Reads the same LIK_-prefixed config the service uses (env vars or .env), so it
targets whatever DB `settings.py` resolves. The schema is idempotent, so this is
safe to re-run. Use it to initialize a deployed DB that never ran the Docker
entrypoint:

    python scripts/init_db.py
    LIK_DB_HOST=prod-db ... LIK_DB_SSLMODE=require python scripts/init_db.py

It only creates schema (tables, indexes, roles); it never drops or truncates.
"""

import pathlib
import sys

import psycopg

# Make `lik_mcp` importable whether or not the package is installed.
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lik_mcp.settings import Settings  # noqa: E402

INIT_SQL = ROOT / "db" / "init.sql"


def main() -> int:
    settings = Settings()
    print(f"Applying {INIT_SQL.name} to {settings.db_user}@{settings.db_host}:"
          f"{settings.db_port}/{settings.db_name} (sslmode={settings.db_sslmode})")

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
