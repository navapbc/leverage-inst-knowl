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
- `list_catalog_entries(entry_type)` — every Catalog row for one `entry_type`, ordered by subject; bounded by the discovery key, not a free-form predicate.
- `confirm_source(citation)` — record a confirmation; rejects unresolvable citations, dedupes per user per source-version.
- `read_confirmations(citation)` — accumulated confirmations for one cited source-version.

There is **no** generic query tool by design.

## Set up

```sh
uv venv                        # creates .venv
uv pip install -e ".[dev]"
```

Run everything through `uv run` (it uses `.venv` automatically — no activation needed).

## Configuration

Copy `.env.example` to `.env` and edit. `LIK_ENV=local|test` uses a stub identity
verifier; any other value — including cloud `dev`/`prod` — fails closed (real Google OIDC
is a later slice). Swapping databases is a credentials change here, never code.

## Run the test database

```sh
docker compose up -d          # postgres:18.4, applies db/init.sql
```

## Test

```sh
uv run pytest
```

The suite `TRUNCATE`s the tables, so it **refuses to run unless `LIK_DB_NAME` ends in
`_test`** — a deployed DB like `likdb` can never be hit. It skips if no database is reachable.

## Local database (for manual testing)

Manual testing needs data that survives the `TRUNCATE` above, so use a separate, persistent
`likdb_local` (the `_test` guard keeps the suite from touching it). Create it once, then
point the server at it:

```sh
docker compose exec db createdb -U lik likdb_local
LIK_DB_NAME=likdb_local uv run python scripts/init_db.py   # apply schema
LIK_ENV=local LIK_DB_NAME=likdb_local uv run python -m lik_mcp   # foreground boot check
```

That last line runs the server on stdio in the foreground — useful to confirm it boots, but
an agent spawns its own copy. The skills below drive the service through an agent (Claude
Code), so connect it there instead of running it by hand.

### Connect the service to your agent

Register lik-mcp as an MCP server, pinned to `likdb_local`.

**Claude CLI** — from the `lik-mcp` folder:

```sh
claude mcp add lik-mcp -- \
  env LIK_ENV=local LIK_DB_NAME=likdb_local uv run python -m lik_mcp
```

**Claude Desktop** — it doesn't inherit your shell or working directory, so use absolute
paths. Edit `claude_desktop_config.json` (Settings → Developer → Edit Config; on macOS it's
`~/Library/Application Support/Claude/claude_desktop_config.json`) and add:

```json
{
  "mcpServers": {
    "lik-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/ik-arch/lik-mcp", "python", "-m", "lik_mcp"],
      "env": { "LIK_ENV": "local", "LIK_DB_NAME": "likdb_local" }
    }
  }
}
```

Use the absolute path to your checkout, and if `uv` isn't on Desktop's `PATH`, give its full
path (`which uv`) as `command`. Restart Claude Desktop to load the server.

The skills also call the Atlassian (Confluence) MCP tools, so connect that server too. The
lik-mcp tools (`register_catalog_entry`, `lookup_catalog_entry`, `list_catalog_entries`,
`confirm_source`, `read_confirmations`) should now show up in the agent.

### Populate the Catalog

The Catalog starts empty. Run the **`sync-catalog-from-project-indexes`** skill — it crawls
every Confluence page tagged `project-index` and upserts one Catalog row per page via
`register_catalog_entry`. It's idempotent, so re-running just updates rows in place. It writes
to whatever DB lik-mcp points at, so confirm the server is on `likdb_local` (not `likdb_test`)
first. Expect a summary like `Synced N project-index pages … X inserted, Y updated`.

### Query the Catalog

With rows in place, run the **`query-project-index`** skill and pass a project question (e.g.
*"what has Nava done with Medicaid?"*). It escalates through exact lookup → list-and-scan →
bounded Confluence search, **asking before it widens scope** at each step, then ranks the cited
pages by their confirmation signals (`read_confirmations`) and offers to record your own
(`confirm_source`). Because `LIK_ENV=local` uses the stub verifier, confirmations are attributed
to whatever email you pass as the token — fine for testing, not real trust.

## Initialize a deployed database

The Docker entrypoint only initializes the local test DB. For any other database, apply
the (idempotent) schema with the service's own config:

```sh
uv run python scripts/init_db.py                           # uses .env / env vars
LIK_DB_HOST=prod-db LIK_DB_SSLMODE=require uv run python scripts/init_db.py
```

Schema only — never drops or truncates. Grant the app role membership in the
`*_writer` / `dl_reader` roles per your governed-writer policy.

## TODO

A local/test harness with throwaway data, not a production service. Until real serving
(verified identities, enforced access) lands:

**Current limits (do not treat these as done):**

- **Prod is inert.** With `LIK_ENV=prod` the fail-closed verifier rejects *every*
  tool call. The service runs but answers nobody until real OIDC lands.
- **Identity is not verified.** In `local`/`test` the stub treats the token as the
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
