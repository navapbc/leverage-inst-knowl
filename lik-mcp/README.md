# lik-mcp

The Discovery Layer's service-fronted store: an MCP service in front of a Postgres
database holding the **Catalog** and **Confirmation signals** (v0.4 architecture). The
AI never touches the database directly — it calls a fixed menu of intent-named tools,
and the service does the database work and enforces the rules.

Scope and decisions: [../docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md](../docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md)
and [../docs/brainstorms/2026-06-24-01-catalog-confirmations-mcp-service-requirements.md](../docs/brainstorms/2026-06-24-01-catalog-confirmations-mcp-service-requirements.md).

## Tools

- `register_catalog_entry(entry)` — upsert a Catalog row on `(entry_type, subject)`.
- `lookup_catalog_entry(entry_type, subject)` — one exact-match lookup; a miss is a clean not-found.
- `confirm_source(citation)` — record a confirmation; rejects unresolvable citations, dedupes per user per source-version.
- `read_confirmations(citation)` — accumulated confirmations for one cited source-version.

There is **no** generic query tool by design.

## Set up

Create and activate a virtual environment, then install the package:

```sh
uv venv                        # creates .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Run the test database

```sh
docker compose up -d          # starts postgres:18.4 and applies db/init.sql
```

## Local dev database (for manual testing)

The test DB (`likdb_test`) is `TRUNCATE`d between test runs. For manual testing —
exercising the catalog/query skills against data that should survive `pytest` — use a
separate, persistent `likdb_dev` in the same container. Create it once:

```sh
docker compose exec db createdb -U lik likdb_dev          # one-time
LIK_DB_NAME=likdb_dev python scripts/init_db.py           # apply the schema
```

Then run the MCP server against it:

```sh
LIK_ENV=dev LIK_DB_NAME=likdb_dev python -m lik_mcp
```

`pytest` keeps pointing at `likdb_test`; the `_test`-suffix guard (below) means the
suite can never truncate `likdb_dev`. Switching the server between the two databases
is an env change, not a code change.

## Initialize a deployed database

The Docker entrypoint only runs `db/init.sql` for the local test DB. For any other
database, apply the (idempotent) schema once with the same config the service reads:

```sh
python scripts/init_db.py                                  # uses .env / env vars
LIK_DB_HOST=prod-db LIK_DB_SSLMODE=require python scripts/init_db.py
```

It creates schema only — never drops or truncates. Grant the deployed app role
membership in the `*_writer` / `dl_reader` roles per your governed-writer policy.

## Test

```sh
pytest
```

It `TRUNCATE`s the tables between tests, so it must point at a disposable database.
As a guardrail the suite **refuses to run unless `LIK_DB_NAME` ends in `_test`** (the
docker compose DB is `likdb_test`); a deployed DB like `likdb` can never be hit. It
skips with a hint if no database is reachable.

## Configuration

Copy `.env.example` to `.env` and edit. Swapping the test DB for the real one is a
credentials change here, not a code change. `LIK_ENV=dev|test` uses a stub identity
verifier; any other value fails closed (real Google OIDC is a later slice).

## TODO

This is a dev/test harness with throwaway data, not a production service. "Full
serving" — real callers in prod with verified identities and enforced access — is
not built yet. Until it is:

**Current limits (do not treat these as done):**

- **Prod is inert.** With `LIK_ENV=prod` the fail-closed verifier rejects *every*
  tool call. The service runs but answers nobody until real OIDC lands.
- **Identity is not verified.** In `dev`/`test` the stub treats the token as the
  caller's email, so `confirmed_by` / `updated_by` are effectively self-asserted.
  Confirmations accumulated this way are not real trust.
- **No access control.** There is no Group → Postgres-role RLS yet; reads return
  rows with **no `access_groups` filtering**. Do **not** load real or restricted
  data into any instance.
- **Citations aren't really resolved.** `ShapeResolver` only checks well-formedness
  and a known `store_kind` — it does not confirm the cited source exists/reaches.
- **No governed-writer security or durability.** Keyless/rotated credentials, audit
  logging, and confirmation backup/retention are unbuilt.

**Deferred work that lifts the limits (see the plan's scope boundaries):**

- Real Google OIDC token verification (replaces the stub verifier).
- Google-Group → Postgres-role RLS bridge (enforces `access_groups` on reads).
- Real per-store citation resolution (behind the existing `CitationResolver` seam).
- Governed-writer controls: keyless/rotated credentials, least privilege, audit logging.
- Confirmation backup/retention, plus rate-limiting / minimum-distinct-confirmer thresholds.
- The producer (DL-creation) and Query skills that call this service.
