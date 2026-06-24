---
date: 2026-06-24
topic: catalog-confirmations-mcp-service
supersedes: the 2026-06-18 draft of this file, which predated the v0.4 architecture
requirements: ../brainstorms/2026-06-24-01-catalog-confirmations-mcp-service-requirements.md
---

# Implementation Plan — Catalog + Confirmations MCP Service

The HOW for the first Discovery Layer slice. The WHAT, scope, and acceptance criteria live in the
[requirements doc](../brainstorms/2026-06-24-01-catalog-confirmations-mcp-service-requirements.md); this plan turns
those into a file layout, schema, tool signatures, and a build sequence.

Aligned to v0.4: the service-fronted Postgres store holds exactly the **Catalog** and **Confirmation
signals** ([v0.4/07-storage.md](../../v0.4/07-storage.md#L42-L44)). The earlier version of this file
modeled a third "machine retrieval signals" table — v0.4 reclassifies those as DS records / Catalog
columns, so they are not in this store and not in this plan.

---

## 1. What we're building, in plain terms

A small **service** sits in front of a Postgres database and speaks MCP — the same interface agents
already use to reach Google Drive and Confluence. It offers a short, fixed menu of actions ("register
where this output lives", "record this confirmation") and does the database work itself. The AI never
talks to the database directly and there is no general "run this query" action. This slice runs against
a **test database in Docker**; pointing it at the real DB is a credentials change.

---

## 2. Decisions locked for this slice

From the requirements doc — inputs, not open questions:

- **Python + FastMCP**, the only component that touches Postgres.
- **Four scoped tools, no raw SQL:** `register_catalog_entry`, `lookup_catalog_entry`,
  `confirm_source`, `read_confirmations`.
- **Catalog + Confirmations only**, separate tables, separate DB roles.
- **Thin pluggable auth seam** — an interface plus a stub verifier; real Google OIDC + Group→role RLS
  deferred.
- **`postgres:18.4`**, matching the deployed DB.
- **Tests hit a real ephemeral Postgres**, not mocks.

### Three open questions — resolved with defaults for this slice

- **Citation resolution (R8):** shape + known-`store_kind` validation now, behind a `CitationResolver`
  interface so real per-store resolution drops in later. The stub rejects unknown store kinds and
  malformed citations; a later real resolver checks the target is reachable.
- **Confirmation dedup key (R9):** unique on `(confirmed_by, store_kind, location, locator, version)`,
  with `locator` normalized to `''` when absent so the constraint is reliable.
- **Schema-init delivery (R17):** a single idempotent `init.sql` (`CREATE TABLE IF NOT EXISTS`, etc.),
  no migration tool yet. Revisit Alembic only when the schema starts changing in production.

---

## 3. Project layout

```
lik-mcp/
  pyproject.toml            # deps: mcp[cli] (FastMCP), psycopg[binary], pydantic, pytest, pytest-asyncio
  README.md
  docker-compose.yml        # postgres:18.4 for local/test
  Dockerfile                # the MCP service image (later deploy; DB uses the official image)
  config/
    settings.py             # typed, env-driven config (pydantic-settings)
    .env.example            # test DB location + credentials template (the swappable file)
  db/
    init.sql                # idempotent schema: tables, constraints, indexes, roles
  src/lik_mcp/
    __init__.py
    server.py               # FastMCP app; registers the four tools
    db.py                   # connection pool, parameterized query helpers
    auth.py                 # Verifier interface + StubVerifier (seam for real OIDC later)
    citations.py            # Citation model + CitationResolver interface + ShapeResolver stub
    catalog.py              # register_catalog_entry / lookup_catalog_entry logic
    confirmations.py        # confirm_source / read_confirmations logic
  tests/
    conftest.py             # spins up / connects to the test Postgres, applies init.sql, stub verifier
    test_catalog.py         # AE1, AE5, AE6
    test_confirmations.py   # AE2, AE3, AE4
    test_surface.py         # AE6: only the four tools are advertised
```

---

## 4. Schema (`db/init.sql`)

Two table groups, two roles.

**`catalog`** — columns from [v0.4/05-architecture.md §3](../../v0.4/05-architecture.md#L52-L77):
`entry_type`, `subject`, `location`, `store_kind`, `locator` (null), `provenance`, `verification`,
`verified_by`, `verified_at`, `freshness`, `source_refs` (jsonb), `last_computed_at`,
`last_validated_at`, `access_groups` (text[]), `sensitivity`, `category`, `computed_by`,
`row_provenance`, plus `created_at` / `updated_at` / `updated_by`.
- `UNIQUE (entry_type, subject)` — the upsert target (R3, R5).
- `CREATE INDEX … USING GIN (access_groups)` for later query-time filtering (R5).

**`confirmations`** — `id`, citation columns (`store_kind`, `location`, `locator` default `''`,
`version`), `confirmed_by`, `created_at`, plus room for the deferred lifecycle fields (window/archive)
as nullable columns.
- `UNIQUE (confirmed_by, store_kind, location, locator, version)` — dedup (R9, AE3, AE4).

**Roles:** `catalog_writer` (write `catalog`), `confirmations_writer` (write `confirmations`), a
read role for both (R11). The service connects with the least-privilege role per action.

---

## 5. Tool signatures (FastMCP)

All four take an `identity` resolved through the auth seam (R12). Catalog tools = service-only mode;
`confirm_source` = service + user assertion (R13).

- `register_catalog_entry(entry: CatalogEntry) -> RegisterResult` — upsert on `(entry_type, subject)`,
  stamp audit columns (F1, R3).
- `lookup_catalog_entry(entry_type: str, subject: str) -> LookupResult` — exact-match; returns a
  found/not-found result object, never raises on miss (F2, R6, AE5).
- `confirm_source(citation: Citation, confirmed_by: str) -> ConfirmResult` — resolve citation (reject
  if it doesn't), record with version, dedup (F3, R7–R9, AE2–AE4).
- `read_confirmations(citation: Citation) -> ConfirmationsResult` — confirmations + count for a
  source-version (F4, R10).

Pydantic models (`CatalogEntry`, `Citation`, result types) give each tool a validated schema and keep
the queries parameterized. No tool issues SQL from caller input (AE6, R2).

---

## 6. Auth and citation seams

- **`auth.Verifier`** — `verify(token) -> Identity`. `StubVerifier` returns a test identity for tests
  and local runs (R14). Real `GoogleOIDCVerifier` is a later, drop-in implementation; tool signatures
  don't change when it lands (R12).
- **`citations.CitationResolver`** — `resolve(citation) -> bool`. `ShapeResolver` (this slice) checks
  citation shape + known `store_kind`. Real per-store resolution is deferred with the connectors.

Both are injected at server construction so tests substitute stubs cleanly.

---

## 7. Docker, config, init

- **`docker-compose.yml`** — `postgres:18.4` with a named volume, healthcheck, and `db/init.sql`
  mounted to `/docker-entrypoint-initdb.d/` so a fresh container self-initializes (R15, R17).
- **`config/settings.py`** + **`.env.example`** — host, port, db, user, password, sslmode, read as
  env vars; the only thing to change for test→prod is the env file (R16). `.env` is gitignored.
- **`db/init.sql`** — idempotent; also runnable by hand against any empty Postgres (R17).

---

## 8. Tests (pytest, real Postgres)

`conftest.py` connects to the compose DB (or a testcontainers Postgres), applies `init.sql`, truncates
between tests, and wires the `StubVerifier` + `ShapeResolver`. Coverage maps to the acceptance examples:

| Test | Acceptance example | Proves |
|---|---|---|
| `test_catalog::test_reregister_upserts` | AE1 | same key → one row, updated values |
| `test_catalog::test_lookup_miss_returns_not_found` | AE5 | missing key → clean miss, no raise |
| `test_confirmations::test_unresolvable_citation_rejected` | AE2 | bad citation → rejected, no row |
| `test_confirmations::test_duplicate_deduped` | AE3 | same user+source-version → one row |
| `test_confirmations::test_version_bound_trust` | AE4 | v5 confirmation not counted for v7 |
| `test_surface::test_only_four_tools` | AE6 | advertised tools = the four; no query tool |

---

## 9. Build sequence

1. **Skeleton + DB up.** Project scaffold, `docker-compose.yml`, `init.sql`, `settings.py`. *Done when*
   a fresh container comes up with the schema and the service connects.
2. **Catalog tools.** `register_catalog_entry` + `lookup_catalog_entry`; tests AE1, AE5, AE6.
3. **Confirmation tools.** `confirm_source` + `read_confirmations` with resolver + dedup; tests
   AE2–AE4.
4. **Green suite + README.** Full pytest pass against the Docker DB; README documents run/test and the
   test→prod config swap.

Deferred (tracked in the requirements doc's Scope Boundaries): real OIDC, Group→role RLS, governed-writer
credentials, backup/retention, rate-limiting thresholds, the producer/Query skills.

---

## 10. Risks to watch

- **Tool creep toward generic writes** — the moment a "run this query" convenience appears, the
  enforcement guarantee is gone. Keep tools intent-named and parameterized (R2, AE6).
- **Auth stub leaking into prod** — the seam must fail closed when no real verifier is configured, so a
  deploy can't accidentally run with `StubVerifier`. Add an explicit guard before any non-test deploy.
- **Confirmations are non-recomputable** — even in this slice, treat the dedup/version logic as the
  load-bearing part; it's what later backup protects.
