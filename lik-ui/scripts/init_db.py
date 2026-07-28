#!/usr/bin/env python3
"""Apply db/init.sql to the configured lik-ui database.

The schema — including the non-destructive auto_delete_at migration — is idempotent, so this is
safe to re-run. It only creates schema and applies non-destructive ALTERs; it never drops or
truncates. Two ways to point it at a database:

1. LIK_UI_ env vars / .env (default): targets whatever settings.py resolves, e.g.

       uv run python scripts/init_db.py
       LIK_UI_DB_HOST=prod-db ... LIK_UI_DB_SSLMODE=require uv run python scripts/init_db.py

2. --ssm-prefix: resolve the prod connection with (almost) no env vars. The DB master password
   is read from SSM (<prefix>/shared/DB_MASTER_PASSWORD) and host/port/user are discovered from
   the Lightsail database; only the two resource names have defaults you can override. Needs AWS
   credentials + the aws CLI on PATH (run under `AWS_PROFILE=lik mise exec -- ...`):

       AWS_PROFILE=lik mise exec -- uv run python scripts/init_db.py --ssm-prefix /ik-arch/prod
"""

import argparse
import os
import pathlib
import subprocess
import sys

import psycopg

from lik_ui.settings import Settings

INIT_SQL = pathlib.Path(__file__).resolve().parents[1] / "db" / "init.sql"


def _run_aws(args: list[str], region: str) -> str:
    """Run a read-only aws CLI command and return its stdout, failing loudly on error."""
    try:
        proc = subprocess.run(
            ["aws", *args, "--region", region, "--output", "text"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        raise SystemExit("[init_db] aws CLI not found on PATH — run under `mise exec -- uv run python ...`.")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"[init_db] `aws {' '.join(args)}` failed: {(exc.stderr or '').strip() or exc}")
    return proc.stdout.strip()


def _resolve_from_ssm(prefix: str, region: str, db_instance: str, db_name: str) -> dict:
    """Password from SSM (<prefix>/shared/DB_MASTER_PASSWORD); host/port/user discovered from the
    Lightsail relational database. Returns psycopg.connect keyword args (sslmode=require, since
    the prod endpoint is public and enforces TLS)."""
    password = _run_aws(
        ["ssm", "get-parameter", "--name", f"{prefix}/shared/DB_MASTER_PASSWORD",
         "--with-decryption", "--query", "Parameter.Value"],
        region,
    )
    endpoint = _run_aws(
        ["lightsail", "get-relational-database", "--relational-database-name", db_instance,
         "--query", "relationalDatabase.[masterEndpoint.address,masterEndpoint.port,masterUsername]"],
        region,
    )
    parts = endpoint.split()
    if len(parts) != 3:
        raise SystemExit(f"[init_db] unexpected Lightsail response for {db_instance!r}: {endpoint!r}")
    host, port, user = parts
    return {"host": host, "port": int(port), "dbname": db_name, "user": user,
            "password": password, "sslmode": "require"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply lik-ui db/init.sql (schema + migrations).")
    parser.add_argument(
        "--ssm-prefix",
        help="Resolve the prod connection from SSM + Lightsail instead of LIK_UI_ env vars "
             "(e.g. /ik-arch/prod). Reads the DB password from <prefix>/shared/DB_MASTER_PASSWORD.",
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"),
                        help="AWS region for SSM/Lightsail lookups (default: %(default)s).")
    parser.add_argument("--db-instance", default="lik-prod-db",
                        help="Lightsail relational database name to discover host/port/user from "
                             "(default: %(default)s). Only used with --ssm-prefix.")
    parser.add_argument("--db-name", default="likuidb",
                        help="Database on the instance to apply the schema to (default: %(default)s). "
                             "Only used with --ssm-prefix.")
    args = parser.parse_args()

    if args.ssm_prefix:
        conn_kwargs = _resolve_from_ssm(args.ssm_prefix, args.region, args.db_instance, args.db_name)
        source = f"via SSM prefix {args.ssm_prefix} + Lightsail {args.db_instance}"
    else:
        settings = Settings()
        conn_kwargs = {"conninfo": settings.conninfo}
        source = "via LIK_UI_ settings"

    # Describe the target without ever printing the password.
    if "conninfo" in conn_kwargs:
        s = Settings()
        target = f"{s.db_user}@{s.db_host}:{s.db_port}/{s.db_name} (sslmode={s.db_sslmode})"
    else:
        target = (f"{conn_kwargs['user']}@{conn_kwargs['host']}:{conn_kwargs['port']}"
                  f"/{conn_kwargs['dbname']} (sslmode={conn_kwargs['sslmode']})")
    print(f"Applying {INIT_SQL.name} to {target} [{source}]")

    try:
        with psycopg.connect(**conn_kwargs, autocommit=True, connect_timeout=10) as conn:
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
