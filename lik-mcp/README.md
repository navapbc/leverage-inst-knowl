# lik-mcp

The Discovery Layer's service-fronted store: an MCP service in front of a Postgres
database holding the **Catalog** and **Confirmation signals** (v0.4 architecture). The
AI never touches the database directly — it calls a fixed menu of intent-named tools,
and the service does the database work and enforces the rules.

Scope and decisions: [../docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md](../docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md)
and [../docs/brainstorms/2026-06-24-01-catalog-confirmations-mcp-service-requirements.md](../docs/brainstorms/2026-06-24-01-catalog-confirmations-mcp-service-requirements.md).

## Tools

- `register_catalog_entry(entry)` — register a Catalog row; a skill upserts its own row on `(entry_type, subject, computed_by)`, a human-owned row inserts a new pointer (duplicates on a key coexist).
- `lookup_catalog_entry(entry_type, subject)` — resolve the key to all matching pointers, ranked best-first (the top row is the default); an empty result is a clean miss.
- `list_catalog_entries(entry_type)` — every Catalog row for one `entry_type`, ordered by subject; bounded by the discovery key, not a free-form predicate.
- `confirm_source(citation)` — record a confirmation; rejects unresolvable citations, one row per user per source (re-confirming updates the stored content-state marker).
- `read_confirmations(citation, current_source_state=None)` — accumulated confirmations for one cited source, one row per user; pass the live marker to flag each row's `edited_since`.

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

## Test

Start just Postgres (the test suite doesn't need the server), then run the suite:

```sh
docker compose up -d db       # just Postgres (postgres:18.4, applies db/init.sql)
uv run pytest
```

(`docker compose up -d` with no service also starts the MCP server — see "Local database
and server" below. For the suite you only need `db`.)

The suite `TRUNCATE`s the tables, so it **refuses to run unless `LIK_DB_NAME` ends in
`_test`** — a deployed DB like `likdb` can never be hit. It skips if no database is reachable.

## Local database and server (for manual testing)

`docker compose up` starts Postgres **and** the lik-mcp HTTP server, and on the first run
auto-creates a persistent `likdb_local` — separate from the disposable `likdb_test` the suite
`TRUNCATE`s, so your manual-testing data survives:

```sh
docker compose up -d          # Postgres + lik-mcp server on 127.0.0.1:8000
```

The server listens over HTTP (the MCP "streamable-http" transport — a long-lived server you
connect to by URL, rather than one each client launches itself) at `http://127.0.0.1:8000/mcp`.
It runs with `LIK_ENV=local` (stub identity — self-asserted, not real trust) and points at
`likdb_local`.
Verify it's up with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
against that URL, or any MCP client.

If your data volume predates this and `likdb_local` is missing, create it once by hand:

```sh
docker compose exec db createdb -U lik likdb_local
LIK_DB_NAME=likdb_local uv run python scripts/init_db.py   # apply schema
```

### Clear the local data

To start manual testing from a clean slate, empty the tables but keep the schema:

```sh
docker compose exec db psql -U lik -d likdb_local -c "TRUNCATE catalog, confirmations RESTART IDENTITY"
```

This is the same reset the test suite does to `likdb_test`. To instead drop everything
(both databases) and re-create from scratch, remove the volume — destructive, and you'll
re-run the first-volume init:

```sh
docker compose down -v        # deletes the Postgres volume: likdb_local AND likdb_test
docker compose up -d          # re-creates both with fresh schema
```

### Connect the service to your agent

**Claude Desktop** — Desktop's custom connectors **can't reach `localhost`**: it hands the
connector URL to Anthropic's cloud, which opens the connection from its own servers, so a
`http://127.0.0.1:8000/mcp` connector silently fails. Use the `mcp-remote` stdio→HTTP bridge in
`claude_desktop_config.json` instead (Settings → Developer → Edit Config; on macOS it's
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "lik-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp"]
    }
  }
}
```

This needs Node/`npx`. Restart Claude Desktop to load it. (Do **not** add the raw URL as a
custom connector — that's the path that can't reach localhost.)

To get the skills (`lik-sync-catalog-from-project-indexes`, `lik-query-project-index`) loaded
automatically, run **Claude Code** against the `ik-arch` folder from within Claude Desktop.
**Claude Cowork** does **not** load the skills.

**Claude CLI** — the CLI connects from your machine, so the URL works directly:

```sh
claude mcp add --transport http lik-mcp http://127.0.0.1:8000/mcp
```

**No-Docker alternative (stdio)** — skip the container and let the client spawn the server over
stdio, pinned to `likdb_local` (run from the `lik-mcp` folder):

```sh
claude mcp add lik-mcp -- \
  env LIK_ENV=local LIK_DB_NAME=likdb_local uv run python -m lik_mcp
```

The skills also call the Atlassian (Confluence) MCP tools, so connect that server too. The
lik-mcp tools (`register_catalog_entry`, `lookup_catalog_entry`, `list_catalog_entries`,
`confirm_source`, `read_confirmations`) should now show up in the agent.

### Populate the Catalog

The Catalog starts empty. Run the **`lik-sync-catalog-from-project-indexes`** skill — it crawls
every Confluence page tagged `project-index` and upserts one Catalog row per page via
`register_catalog_entry`. It's idempotent, so re-running just updates rows in place. It writes
to whatever DB lik-mcp points at, so confirm the server is on `likdb_local` (not `likdb_test`)
first. Expect a summary like `Synced N project-index pages … X inserted, Y updated`.

> **Tip:** To limit a run for testing, tell the skill how many pages to process when you
> invoke it — e.g. `lik-sync-catalog-from-project-indexes` *"only process the latest 5
> project-index pages"*. Re-running later picks up the rest.

### Query the Catalog

With rows in place, run the **`lik-query-project-index`** skill and pass a project question (e.g.
*"what has Nava done with Medicaid?"*). It escalates through exact lookup → list-and-scan →
bounded Confluence search, **asking before it widens scope** at each step, then ranks the cited
pages by their confirmation signals (`read_confirmations`) and offers to record your own
(`confirm_source`). Because `LIK_ENV=local` uses the stub verifier, confirmations are attributed
to whatever email you pass as the token — fine for testing, not real trust.

## Initialize a deployed database

The Docker entrypoint only initializes the local `likdb_test` and `likdb_local` databases.
For any other database, apply the (idempotent) schema with the service's own config:

```sh
uv run python scripts/init_db.py                           # uses .env / env vars
LIK_DB_HOST=prod-db LIK_DB_SSLMODE=require uv run python scripts/init_db.py
```

Schema only — never drops or truncates. Grant the app role membership in the
`*_writer` / `dl_reader` roles per your governed-writer policy.

## Deploy as a Docker container

The same `Dockerfile` that backs local testing is the deploy artifact — one image, its
behavior set entirely by environment variables at run time. Its defaults are already
deploy-shaped: the long-lived HTTP transport, a bind on all interfaces
(`LIK_HTTP_HOST=0.0.0.0`) so the published port is reachable, and `LIK_ENV=prod`, which
fails closed until real auth is configured. The `docker compose` setup above only overrides
those for loopback-only local use; a deploy keeps the defaults and supplies its own config.

Build the image:

```sh
docker build -t lik-mcp .
```

**1. Initialize the database first.** The image's entrypoint only creates the local
`likdb_test` / `likdb_local` databases. Point at your real database and apply the schema
once before serving — see [Initialize a deployed database](#initialize-a-deployed-database)
above.

**2. Run the container with a deploy config.** Any `LIK_ENV` other than `local`/`test`
turns on real Google token verification, and the server refuses to start unless the OAuth
variables are set. Supply, at minimum:

| Variable | Purpose |
| --- | --- |
| `LIK_ENV` | Anything but `local`/`test` (e.g. `dev`, `prod`) — enables real auth. |
| `LIK_DB_HOST`, `LIK_DB_NAME`, `LIK_DB_USER`, `LIK_DB_PASSWORD`, `LIK_DB_SSLMODE` | Where the real database lives; use `require` SSL for a remote DB. |
| `LIK_OAUTH_CLIENT_ID` | The Google OAuth client id incoming tokens must be minted for (their `aud`). |
| `LIK_RESOURCE_SERVER_URL` | This server's own public URL, including the `/mcp` path. |
| `LIK_HTTP_ALLOWED_HOSTS` | Must include the public host clients reach it by. The bind is `0.0.0.0`, so this list — not the bind — is the DNS-rebinding guard. |

```sh
source .env
export LIK_DB_HOST LIK_DB_NAME LIK_DB_SSLMODE LIK_DB_USER LIK_DB_PASSWORD LIK_OAUTH_CLIENT_ID LIK_RESOURCE_SERVER_URL LIK_HTTP_ALLOWED_HOSTS
docker run -p 8000:8000 -e LIK_DB_HOST -e LIK_DB_NAME -e LIK_DB_SSLMODE -e LIK_DB_USER -e LIK_DB_PASSWORD -e LIK_OAUTH_CLIENT_ID -e LIK_RESOURCE_SERVER_URL -e LIK_HTTP_ALLOWED_HOSTS lik-mcp
```

Terminate TLS at whatever fronts the container (load balancer, reverse proxy, or tunnel);
the server itself speaks plain HTTP on 8000. The untracked `docker-compose.override.yml` is
a working reference for this shape — it exposes the local build through an ngrok tunnel with
real Google auth on, and shows exactly which keys change from the local config.

## Help

### Update the containers after code or schema changes

App code (`src/`) is baked into the `lik-mcp` image, so rebuild it after editing:

```sh
docker compose up -d --build lik-mcp
```

`db/init.sql` is applied only on **first** volume init, so an already-created database
won't pick up edits. Either re-apply the schema in place (`scripts/init_db.py`, see
"Initialize a deployed database"), or drop and re-create from scratch (destructive —
deletes `likdb_local` and `likdb_test`):

```sh
docker compose down -v && docker compose up --build -d
```

### New MCP tools not showing up in Claude Desktop

`mcp-remote` caches the tool list from the server. After deploying new tools, restart Claude Desktop to force a fresh tool-list fetch.

## TODO

A local/test harness with throwaway data, not yet a production service. Real Google token
verification is wired (`LIK_ENV` outside `local`/`test`), but enforced access has not
landed — so do not load real or restricted data yet:

**Current limits (do not treat these as done):**

- **Identity is only verified on a real deploy.** In `local`/`test` the stub treats the
  token as the caller's email, so `confirmed_by` / `updated_by` are effectively
  self-asserted and confirmations accumulated this way are not real trust. A deploy
  (`LIK_ENV=dev`/`prod` with the OAuth vars set) verifies a real Google token per request.
- **No access control.** There is no Group → Postgres-role RLS yet; reads return
  rows with **no `access_groups` filtering**. Do **not** load real or restricted
  data into any instance.
- **Citations aren't really resolved.** `ShapeResolver` only checks well-formedness
  and a known `store_kind` — it does not confirm the cited source exists/reaches.
- **No governed-writer security or durability.** Keyless/rotated credentials, audit
  logging, and confirmation backup/retention are unbuilt.

**Deferred work that lifts the limits (see the plan's scope boundaries):**

- Google-Group → Postgres-role RLS bridge (enforces `access_groups` on reads).
- Real per-store citation resolution (behind the existing `CitationResolver` seam).
- Governed-writer controls: keyless/rotated credentials, least privilege, audit logging.
- Confirmation backup/retention, plus rate-limiting / minimum-distinct-confirmer thresholds.
- The producer (DL-creation) and Query skills that call this service.

**Confirmation table maintenance/management**

- Age out old confirmations for scalability.
- Migrate/Capture trustworthiness in original DS records and archive confirmation signals for scalability.
- Correct DS record for negative confirmations where `reason`=`wrong-content`.

**Catalog table maintenance/management**

- Age out old rows.
