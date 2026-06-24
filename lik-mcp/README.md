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

## Run the test database

```sh
docker compose up -d          # starts postgres:18.4 and applies db/init.sql
```

## Test

```sh
pip install -e ".[dev]"
pytest
```

Tests run against the Docker Postgres (or any DB the env points at) and exercise the
real write-time rules. They skip with a hint if no database is reachable.

## Configuration

Copy `.env.example` to `.env` and edit. Swapping the test DB for the real one is a
credentials change here, not a code change. `LIK_ENV=dev|test` uses a stub identity
verifier; any other value fails closed (real Google OIDC is a later slice).

## Not yet built (deferred)

Real Google OIDC verification, the Google-Group → Postgres-role RLS bridge,
governed-writer credential rotation, confirmation backup/retention, rate-limiting
thresholds, and the producer/Query skills. See the plan's scope boundaries.
