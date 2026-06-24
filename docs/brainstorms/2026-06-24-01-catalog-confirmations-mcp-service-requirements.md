---
date: 2026-06-24
topic: catalog-confirmations-mcp-service
---

# Catalog + Confirmations MCP Service — First Implementation Slice

## Summary

Build the first piece of the Discovery Layer: an MCP service fronting a Postgres database that holds the **Catalog** and **Confirmation signals** — the only two DL outputs that live in a service-fronted store ([v0.4/07-storage.md](../../v0.4/07-storage.md#L42-L44)). The service exposes a fixed menu of intent-named tools (never raw SQL), enforces write-time rules itself, and ships with a Dockerized test database, a swappable credentials file, a schema-init script, and unit tests that prove the tools work against a real Postgres.

---

## Problem Frame

The Discovery Layer keeps almost everything as recomputable material in the source systems, but two outputs can't live there: the **Catalog** (one keyed directory of `where each output lives`) needs keyed lookup at a well-known address, and **Confirmation signals** (people vouching a source was right) are non-recomputable and need write-time enforcement plus their own backup ([v0.4/05-architecture.md](../../v0.4/05-architecture.md#L18-L22)). A Confluence page can't give either one keyed lookup or enforcement at the moment of writing, so both must move behind a service that owns the database and exposes only safe, specific actions.

Nothing of this service exists yet. The only prior artifact, [docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md](../../docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md), predates the v0.4 architecture: it still cites removed filenames (`lik-4-strategy.md`) and models a third Postgres table ("machine retrieval signals") that v0.4 reclassifies as DS records or Catalog columns, not a separate store. That stale plan needs to be superseded by this work.

---

## Actors

- A1. **DL-creation skill (producer)** — a service identity that registers Catalog rows. Writes under its own identity, no end user in the loop.
- A2. **Query skill (consumer)** — runs at question time; looks up Catalog rows and reads confirmations to shape ranking.
- A3. **Confirming user** — a person vouching that a cited source was right; the service writes the confirmation under this person's verified identity (`confirmed_by`), never lets them write directly.
- A4. **The MCP service** — owns every read and write, enforces the rules, is the only thing that touches Postgres.

---

## Key Flows

- F1. **Register a Catalog entry**
  - **Trigger:** a producer skill (A1) finishes computing an output and needs to record where it lives.
  - **Actors:** A1, A4
  - **Steps:** producer calls `register_catalog_entry` with `(entry_type, subject, location, …)` → service validates inputs → upserts on the `(entry_type, subject)` key → stamps audit columns.
  - **Outcome:** one row maps the key to its location; a later call on the same key updates in place rather than duplicating.
  - **Covered by:** R3, R4, R5, R11

- F2. **Look up a Catalog entry**
  - **Trigger:** a consumer skill (A2) needs to find where an output lives.
  - **Actors:** A2, A4
  - **Steps:** consumer calls `lookup_catalog_entry(entry_type, subject)` → service runs an exact-match keyed query → returns the row or an explicit "not found".
  - **Outcome:** one lookup resolves the pointer; a missing row is a clean cache-miss signal, not an error.
  - **Covered by:** R6, R12

- F3. **Confirm a source**
  - **Trigger:** a user (A3) signals that a cited source was right.
  - **Actors:** A3, A4
  - **Steps:** caller passes the citation `(store_kind + location + locator + version)` and the verified `confirmed_by` → service rejects a citation that doesn't resolve → records the confirmation with the confirmed version → dedupes against an existing confirmation by the same user for the same source-version.
  - **Outcome:** a durable, attributed confirmation exists; duplicates and unresolvable citations are refused.
  - **Covered by:** R7, R8, R9, R13, R14

- F4. **Read confirmations**
  - **Trigger:** a consumer skill (A2) wants accumulated trust for a cited pointer.
  - **Actors:** A2, A4
  - **Steps:** consumer calls `read_confirmations(citation)` → service returns the confirmations and/or a count for that source-version.
  - **Outcome:** the consumer can annotate "confirmed by N people" and apply staleness-aware weighting.
  - **Covered by:** R10

---

## Requirements

**Service surface**
- R1. The service speaks MCP, built in **Python with FastMCP**, and is the only component that connects to Postgres.
- R2. The service exposes **only** these intent-named tools — no generic query/`run_sql` tool ever: `register_catalog_entry`, `lookup_catalog_entry`, `confirm_source`, `read_confirmations`. Each validates its own inputs and runs fixed, parameterized queries.

**Catalog**
- R3. `register_catalog_entry` writes a Catalog row keyed on `(entry_type, subject)`, upserting in place on key collision.
- R4. A Catalog row carries at least the v0.4 schema columns: `entry_type`, `subject`, `location`, `store_kind`, `locator`, `provenance`, `verification`, `freshness`, `source_refs`, `last_computed_at`, `last_validated_at`, `access_groups`, `sensitivity`, `category`, `computed_by`, `row_provenance`, plus `created_at` / `updated_at` / `updated_by` audit columns ([v0.4/05-architecture.md](../../v0.4/05-architecture.md#L52-L77)).
- R5. The `(entry_type, subject)` pair has a uniqueness constraint; `access_groups` is indexed (GIN) for later query-time filtering.
- R6. `lookup_catalog_entry` does exact-match lookup on the keys only (no semantic search) and returns an explicit not-found result rather than erroring when no row matches.

**Confirmations**
- R7. `confirm_source` records a confirmation against a cited source identified by `store_kind + location + locator + version`, attributed to a verified `confirmed_by` identity.
- R8. The service **rejects a confirmation whose citation does not resolve** to a real, reachable source.
- R9. The service stores the **version of the confirmed source** so a later edit doesn't silently inherit earned trust, and **dedupes** to at most one confirmation per user per cited source-version.
- R10. `read_confirmations` returns the confirmations (and/or a count) for a given citation so a consumer can annotate and weight by trust.
- R11. Confirmation and Catalog data live in **separate tables with separate database roles**, so a compromise of one writer path is contained.

**Identity (thin pluggable seam)**
- R12. Every tool requires a caller identity provided through an **auth interface**; the production verifier (real Google OIDC) is *not* built in this slice, but the seam is present so it can be dropped in later without changing tool signatures.
- R13. Catalog tools run in **service-only** writer mode (producer's service identity); `confirm_source` runs in **service + user-assertion** mode (service performs the write, records the user's verified `confirmed_by`).
- R14. A **stub/injectable verifier** lets the test suite supply identities without Google, so write-time rules can be exercised end to end.

**Operability deliverables**
- R15. A **Dockerfile / compose** stands up `postgres:18.4` (matching the deployed DB) for local testing.
- R16. A **single config file** holds the DB location and credentials, env-driven and typed, structured so swapping the test DB for the real one is a credentials change, not a code change.
- R17. A **schema-init script** creates the Catalog and Confirmation tables, constraints, indexes, and roles from scratch on an empty database.
- R18. A **pytest unit suite** runs the tools against a real ephemeral Postgres (the Docker DB or testcontainers), covering the acceptance examples below.

---

## Acceptance Examples

- AE1 — **Re-registering the same key updates in place.** Calling `register_catalog_entry` twice with the same `(entry_type, subject)` leaves exactly one row, with the second call's values and a refreshed `updated_at`. *Covers: R3.*
- AE2 — **Unresolvable citation is refused.** `confirm_source` with a citation that points to nothing returns a rejection and writes no row. *Covers: R8.*
- AE3 — **Duplicate confirmation is deduped.** The same user confirming the same source-version twice yields one stored confirmation, not two. *Covers: R9.*
- AE4 — **Edited-since does not inherit trust.** A confirmation recorded against version `v5` is not counted for `v7` of the same source. *Covers: R9.*
- AE5 — **Missing Catalog row is a clean miss.** `lookup_catalog_entry` for an absent key returns a not-found result, not an exception. *Covers: R6.*
- AE6 — **No raw-SQL surface.** The advertised tool list contains only the four intent-named tools; there is no general query tool. *Covers: R2.*

---

## Success Criteria

- `docker compose up` (or equivalent) brings up `postgres:18.4`; the init script creates the schema on it cleanly; the pytest suite passes against it.
- All six acceptance examples pass as automated tests.
- Pointing the config file at a different Postgres (location + credentials) runs the same suite with no code change.
- The service advertises exactly the four scoped tools and no raw-query escape hatch.

---

## Scope Boundaries

- **In:** the MCP service, the four scoped tools, Catalog + Confirmation schema/roles, the auth *seam* (with a stub verifier), Dockerized `postgres:18.4`, swappable config, init script, unit tests.
- **Deferred for later:** real Google OIDC token verification; the Google-Group→Postgres-role RLS bridge; governed-writer credential mechanics (WIF, rotation, audit-log shipping); backup/retention automation for confirmations; the producer and Query skills themselves; rate-limiting and minimum-distinct-confirmer thresholds (stub the hook, don't tune it); back-propagation and age-out (§3.3).
- **Out (not this store at all):** machine-retrieval-signal tables (v0.4 puts these in DS records / Catalog columns, not Postgres); the BigQuery reporting warehouse.

---

## Key Decisions

- **Python + FastMCP** — concise scoped-tool definitions, strong Postgres + pytest ergonomics.
- **Thin pluggable auth seam** — build the interface and a stub now; defer real Google OIDC + RLS. Follows v0.4's "earn each step": a test-DB slice shouldn't carry full identity infrastructure.
- **Catalog + Confirmations only** — confirmed against the v0.4 docs themselves; "machine retrieval signals" as a third Postgres table is a stale pre-v0.4 idea.
- **`postgres:18.4`** — pinned to match the deployed DB.
- **Tests hit a real Postgres, not mocks** — write-time enforcement is the entire reason the store exists, so it must be exercised against a real engine.

---

## Dependencies / Assumptions

- The deployed DB is Postgres 18.4; the test image matches it.
- Citation resolution (R8) needs *some* way to check a source is reachable. **Assumption:** for this slice, "resolves" can be a pluggable check (e.g., a stub that validates citation shape/known store_kinds), with real per-store resolution deferred alongside the connectors — flagged as an outstanding question below.
- The stale [docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md](../../docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md) should be superseded/updated to match v0.4 (two output types, not three) as part of this work.

---

## Outstanding Questions

- **Citation resolution depth:** does AE2's "citation resolves" mean full live resolution against the target store (Confluence/Drive/etc.), or shape/known-store validation for this slice? (Leaning: shape-validation now, pluggable for real resolution later.)
- **Confirmation dedup key precision:** is the unique key `(confirmed_by, store_kind, location, locator, version)`, or should `locator` be normalized/optional in the key?
- **Schema-init delivery:** plain `.sql` run on container start vs. a migration tool (e.g., Alembic). For a first slice, a single idempotent `.sql` is simplest — confirm before adding a migration dependency.
