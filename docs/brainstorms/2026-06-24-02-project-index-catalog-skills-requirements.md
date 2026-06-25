---
date: 2026-06-24
topic: project-index-catalog-skills
---

# Project-Index Catalog Skills — Sync + Query

## Summary

Two agent skills that exercise the [lik-mcp](../../lik-mcp/README.md) Catalog end-to-end for manual testing, plus the one MCP tool they need:

1. **`lik-sync-catalog-from-project-indexes`** (DL-creation skill) — fetches every Confluence page tagged `project-index` and registers one Catalog row per page in Postgres via `register_catalog_entry`. Same source-of-truth and one-row-per-page model as the existing [discovery-catalog-sync/SKILL.md](../../discovery-catalog-sync/SKILL.md), but the sink is Postgres-behind-MCP, not a Confluence table.
2. **`lik-query-project-index`** (Query skill) — answers a user's question from the Catalog using a three-level, user-gated escalation: exact-match lookup → (on miss) list-and-scan → Confluence fallback. It **ranks cited sources by their confirmation count** (`read_confirmations`) and lets the user **confirm a cited source** (`confirm_source`) after answering.
3. **`list_catalog_entries(entry_type)`** — a new intent-named MCP tool in lik-mcp, required by the query skill's Level 2. Bounded by `entry_type`; no free-form filtering.

The point is dogfooding: prove the register → lookup → confirm round-trip exercises all four lik-mcp tools against a real Postgres, the way the README's deferred "producer and Query skills that call this service" anticipated.

---

## Problem Frame

The lik-mcp service is built and tested, but nothing calls it the way a real producer or consumer would. The README lists "the producer (DL-creation) and Query skills that call this service" as deferred work. These two skills are that work, scoped down to manual testing.

The load-bearing constraint: the Catalog exposes exactly one read tool, `lookup_catalog_entry(entry_type, subject)` — an **exact-match** lookup — and the README states "There is no generic query tool by design." The existing Confluence catalog ([discovery-catalog-sync/SKILL.md](../../discovery-catalog-sync/SKILL.md)) sidestepped this because the whole table renders on one page an agent reads top-to-bottom. Postgres-behind-MCP gives point lookups only. So a query skill works trivially only when the question names one project; enumeration/search questions ("which projects use React?") have no path. That gap is what the three-level escalation resolves.

---

## Actors

- **A1. Tester (you)** — runs the skills by hand against the dockerized `likdb_test` DB in `LIK_ENV=local`/`test`, to verify the round-trip; also the **confirming user** whose verified identity (`confirmed_by`, stubbed in local/test) is recorded when confirming a cited source.
- **A2. `lik-sync-catalog-from-project-indexes`** — the producer skill; reads Confluence, writes Catalog rows under its own service identity (`computed_by`).
- **A3. `lik-query-project-index`** — the consumer skill; reads the Catalog and, when needed, Confluence, to answer a question; reads confirmations to rank sources and records the user's confirmations.
- **A4. lik-mcp service** — owns Postgres; exposes `register_catalog_entry`, `lookup_catalog_entry`, the new `list_catalog_entries`, plus `confirm_source` / `read_confirmations`.
- **A5. Confluence (Rovo MCP)** — the data source; `searchConfluenceUsingCql` / `getConfluencePage`.

---

## Key Flows

### F1. Sync the catalog from project-index pages
- **Trigger:** tester runs `lik-sync-catalog-from-project-indexes` ("sync project indexes into the catalog").
- **Steps:**
  1. `searchConfluenceUsingCql` with `cql: label = "project-index" AND type = page`, limit 250.
  2. For each result, build a `CatalogEntry`:
     - `entry_type = "index"`
     - `subject = "project: <title>"`
     - `location = webUrl`
     - `store_kind = "confluence"`
     - `locator = <Confluence page ID>` (so a consumer can `getConfluencePage` directly)
     - `source_refs = [{ id: <pageId>, version: <lastModified or version> }]`
     - `computed_by = "lik-sync-catalog-from-project-indexes"`, `row_provenance = "skill"`
     - leave provenance/verification/freshness/sensitivity at schema defaults
  3. Call `register_catalog_entry(entry)` per page (upsert on the key — re-running updates in place, never duplicates).
  4. Report a summary: N pages seen, X inserted, Y updated.
- **Outcome:** one Catalog row per project-index page, keyed `(index, project: <title>)`, pointing at the live Confluence page.
- **Covered by:** R1, R2, R3, R7

### F2. Query — Level 1: exact-match Catalog lookup
- **Trigger:** tester asks a question that names a project ("tell me about the Atlas project").
- **Steps:** derive `subject = "project: <name>"` from the question → `lookup_catalog_entry("index", subject)` → on hit, `getConfluencePage` at the row's `location`/`locator` → answer from that page, citing it.
- **Outcome:** answer grounded in the one vetted page, reached in a single lookup.
- **Covered by:** R4, R5

### F3. Query — Level 2: list-and-scan (user-gated, on a Level 1 miss)
- **Trigger:** Level 1 misses, or the question doesn't name a single project.
- **Steps:** skill **pauses and asks the user**: "No exact catalog match. List all project-index entries and scan them, or search Confluence directly?" → if list: `list_catalog_entries("index")` → scan returned rows in-agent (match keywords against `subject`/`category`), follow the most relevant pointers, answer.
- **Outcome:** enumeration/fuzzy questions answered from Catalog rows without hitting Confluence search.
- **Covered by:** R4, R6, R8

### F4. Query — Level 3: Confluence fallback (user-gated)
- **Trigger:** user chooses to skip to Confluence at the Level 2 prompt, or the list-scan finds nothing.
- **Steps:** `searchConfluenceUsingCql` with `label = "project-index" AND text ~ "<terms>"` → read top matches → answer, and note the answer came from a bounded fan-out, not the Catalog.
- **Outcome:** the documented "cache miss → bounded fan-out" degradation ([v0.4/05-architecture.md](../../v0.4/05-architecture.md#L79-L89)); never errors, just costs a search.
- **Covered by:** R4, R6

### F5. Rank and present cited sources by trust (every level)
- **Trigger:** any of F2–F4 produced one or more candidate source pages to cite.
- **Steps:** for each candidate, build a `Citation` `{store_kind:"confluence", location:webUrl, locator:pageId, version:<page version>}` → call `read_confirmations(citation)` → use the returned `count` to rank/weight sources (more confirmations = more trusted) → present the answer with each citation annotated by its confirmation count.
- **Outcome:** the user sees not just sources but how vouched-for each one is; ranking reflects accumulated human trust.
- **Covered by:** R10

### F6. Confirm a cited source (user-gated, after answering)
- **Trigger:** after the answer, the skill offers "confirm any of these sources as correct?"; the user picks one.
- **Steps:** reuse the same `Citation` (identical `version`) → `confirm_source(citation)` → report `recorded` / `duplicate` / `rejected`. The confirming identity comes from the verified token (stubbed in local/test), never self-asserted in the payload.
- **Outcome:** a confirmation row accumulates against that source-version; a re-confirm by the same user is a clean `duplicate`. Exercises the write path that F5's ranking later reads.
- **Covered by:** R11

---

## Requirements

- **R1.** `lik-sync-catalog-from-project-indexes` fetches project-index pages via the same canonical CQL as `discovery-catalog-sync` (`label = "project-index"`).
- **R2.** It registers exactly one Catalog row per page, keyed `(entry_type="index", subject="project: <title>")`, via `register_catalog_entry`; re-running is idempotent (upsert), reported as inserted vs. updated.
- **R3.** Each row carries enough to be followed and freshness-checked later: `location` (webUrl), `store_kind="confluence"`, `locator` (page ID), and `source_refs` with the page ID + version/lastModified.
- **R4.** `lik-query-project-index` runs the three-level escalation in order, and **requires explicit user confirmation before leaving Level 1 for Level 2, and before Level 2 reaches Level 3**.
- **R5.** Level 1 maps the question to a `subject` and does one `lookup_catalog_entry`; on hit it follows the pointer and answers from the page.
- **R6.** Level 3 falls back to Confluence CQL search over project-index pages; a Catalog miss or a dangling pointer never errors — it degrades to fallback.
- **R7.** Manual-testing runs target a **persistent local database (`likdb_local`)**, not the disposable `likdb_test`; both skills assume `LIK_ENV=local` with the stub verifier, no real identity/ACL/prod. The synced Catalog must survive `pytest` runs (which `TRUNCATE`), so it cannot live in the test DB.
- **R12.** Provision `likdb_local` as a second database in the same Postgres container: create it, then apply the schema with `scripts/init_db.py` (schema-only, never drops/truncates). The MCP server used for manual testing runs with `LIK_DB_NAME=likdb_local`; the test suite keeps `LIK_DB_NAME=likdb_test`. The existing `_test`-suffix gate already guarantees the suite can never truncate `likdb_local`. `lik-sync-catalog-from-project-indexes` is run on demand only (it's an expensive Confluence crawl); `lik-query-project-index` reads whatever the last sync left in `likdb_local`.
- **R8.** New MCP tool `list_catalog_entries(entry_type)`: returns all rows for one `entry_type`, no free-form predicate, reads stay open, miss returns an empty list (not an error). Added to `catalog.py` + `server.py` with a unit test mirroring the existing catalog tests.
- **R9.** Both skills are self-contained `SKILL.md` files at repo root (siblings of the existing two); `lik-query-project-index` does **not** use the live-instructions-from-Confluence indirection that `dl-project-index-query` uses.
- **R10.** Before presenting an answer, `lik-query-project-index` calls `read_confirmations` for each cited source and uses the `count` to rank/weight sources, displaying the count alongside each citation. Citation `version` must match the page version the row was built from (carried in the row's `source_refs`), since confirmations are version-specific.
- **R11.** After answering, the skill offers to confirm a cited source and, on the user's pick, calls `confirm_source` with the same `Citation` (same `version`); it reports `recorded` / `duplicate` / `rejected` without retrying. Identity is taken from the verified token, never placed in the payload.

---

## Key Decisions

- **K1. Three-level user-gated escalation** (your call) over catalog-only or auto-fallback. Keeps the Catalog primary, makes each widening of scope a deliberate user choice, and reaches Confluence only as a last resort.
- **K2. Add `list_catalog_entries(entry_type)` rather than reuse lookup or add generic search.** It's intent-named and bounded by the discovery key, so it honors the "no generic SQL" rule while enabling Level 2. This is a code change to lik-mcp, scoped to one tool + test.
- **K3. `entry_type = "index"`** for project-index pages — the literal v0.4 enum match (these pages *are* curated indexes), distinct from the `project-summary` rows in the existing tests.
- **K4. Manual-test framing.** Optimize for a working round-trip a person drives, not production hardening.
- **K5. The query skill exercises all four lik-mcp tools.** Beyond catalog lookup it reads confirmations to rank sources and writes confirmations on user request — so one skill run tests the full service surface. The trade-off: `version` must be threaded consistently from the catalog row's `source_refs` into every `Citation`, or `read_confirmations` and `confirm_source` silently key against different source-versions and the round-trip looks broken when it isn't.

## Dependencies / Assumptions

- Atlassian Rovo MCP (`searchConfluenceUsingCql`, `getConfluencePage`) is connected in the testing environment. *(Verified available per [mcp-availability.md](../../mcp-availability.md#L11).)*
- lik-mcp is registered as an MCP server in the agent environment and pointed at a running `likdb_local` (`LIK_DB_NAME=likdb_local`, `LIK_ENV=local`). *(Assumption — not verified in this brainstorm; confirm before testing.)* Switching the server between `likdb_local` and `likdb_test` is an env/credentials change, not a code change ([settings.py](../../lik-mcp/src/lik_mcp/settings.py)).
- Level 2 returns all `index` rows unfiltered by `access_groups` (ACL not yet built per the README). Acceptable only for the throwaway test DB; do not load restricted data.

## Out of Scope

- Real Google OIDC / verified identity and Group→role ACL enforcement (the confirming identity stays stubbed; confirmations recorded this way are not real trust).
- Confirmation backup/retention, rate-limiting, and minimum-distinct-confirmer thresholds.
- Scheduled runs, dangling-pointer reconciliation, and freshness re-derivation.
- Any change to the Catalog write rules or the other three MCP tools.
