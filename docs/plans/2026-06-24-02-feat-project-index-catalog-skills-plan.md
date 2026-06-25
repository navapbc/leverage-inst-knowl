---
title: "feat: Project-index catalog skills (sync + query) over lik-mcp"
type: feat
status: active
date: 2026-06-24
origin: docs/brainstorms/2026-06-24-02-project-index-catalog-skills-requirements.md
---

# feat: Project-index catalog skills (sync + query) over lik-mcp

## Summary

Stand up the two agent skills the lik-mcp README lists as deferred — a DL-creation skill that crawls Confluence `project-index` pages and registers one Catalog row each in Postgres, and a Query skill that answers questions from the Catalog with a user-gated escalation (lookup → list → Confluence) and exercises the confirmations flow. One supporting code change (`list_catalog_entries` MCP tool) and one ops step (a persistent `likdb_local`) make the round-trip manually testable end to end.

---

## Problem Frame

lik-mcp is built and tested, but nothing calls it the way a real producer or consumer would, so the register → lookup → confirm round-trip has never run end to end. The catalog also exposes only exact-match `lookup_catalog_entry`, which has no path for enumeration/search questions. See origin Problem Frame ([origin](../brainstorms/2026-06-24-02-project-index-catalog-skills-requirements.md)).

---

## Requirements

- R1. `lik-sync-catalog-from-project-indexes` fetches project-index pages via the canonical CQL (`label = "project-index"`) and registers one Catalog row per page, idempotently.
- R2. Rows are keyed `(entry_type="index", subject="project: <title>")`, `store_kind="confluence"`, with `location`, `locator` (page ID), and `source_refs` (page ID + version) populated.
- R3. `lik-query-project-index` runs the three-level escalation in order, requiring explicit user confirmation before Level 1→2 and before 2→3.
- R4. The query skill ranks cited sources by `read_confirmations` count and offers `confirm_source` after answering; citation `version` is sourced consistently within a run.
- R5. New intent-named MCP tool `list_catalog_entries(entry_type)`: returns all rows for one `entry_type`, no free-form predicate, miss returns empty list, reads stay open.
- R6. A persistent `likdb_local` holds the synced catalog and survives `pytest` (which truncates `likdb_test`); switching the server between the two is env-only.
- R7. Both skills are self-contained `SKILL.md` files at repo root; the query skill does not use Confluence live-instructions indirection.
- R8. A Catalog miss or dangling pointer never errors — it degrades to the next level / a bounded fan-out.
- R9. `read_confirmations` returns confirmations across **all versions** of a cited source (matched on `store_kind` + `location` + `locator`), each row carrying its own `version`, so the consumer can use the latest version's trust or weigh prior-version trust. `confirm_source` is unchanged — it still records and dedups per exact source-version. **Redefines origin AE4** (which asserted version-bound counting at the service); that capability is preserved as a client-side filter on the returned rows.

**Origin actors:** A1 (Tester / confirming user), A2 (sync skill / producer), A3 (query skill / consumer), A4 (lik-mcp service), A5 (Confluence Rovo MCP).
**Origin flows:** F1 (sync), F2 (query L1 lookup), F3 (query L2 list-and-scan), F4 (query L3 Confluence fallback), F5 (rank by trust), F6 (confirm a source).

---

## Scope Boundaries

- Real Google OIDC / verified identity and Group→role ACL enforcement (confirming identity stays stubbed).
- Confirmation backup/retention, rate-limiting, minimum-distinct-confirmer thresholds.
- Scheduled runs, dangling-pointer reconciliation, freshness re-derivation.
- Any change to the Catalog write rules, `confirm_source`'s per-version dedup, or the remaining three MCP tools. (`read_confirmations` read semantics *are* in scope — see U5/R9.)
- Automatic provisioning of `likdb_local` inside the Docker entrypoint (entrypoint init scripts only run on a fresh volume) — provisioning is a documented one-time manual step instead.

---

## Context & Research

### Relevant Code and Patterns

- [lik-mcp/src/lik_mcp/catalog.py](../../lik-mcp/src/lik_mcp/catalog.py) — `CatalogEntry`, `register_catalog_entry`, `lookup_catalog_entry`, the `_serialize` helper, and the `LookupResult` shape `list_catalog_entries` should mirror.
- [lik-mcp/src/lik_mcp/server.py](../../lik-mcp/src/lik_mcp/server.py) — `build_server`, the `@mcp.tool` registration pattern, `verifier.verify(token)` on every tool.
- [lik-mcp/src/lik_mcp/confirmations.py](../../lik-mcp/src/lik_mcp/confirmations.py) / [citations.py](../../lik-mcp/src/lik_mcp/citations.py) — `confirm_source` / `read_confirmations`, the `Citation` shape `{store_kind, location, locator, version}`, version-specific dedup.
- [lik-mcp/tests/test_catalog.py](../../lik-mcp/tests/test_catalog.py) — the `_entry(**overrides)` + `db` fixture test style to mirror for the new tool's test.
- [lik-mcp/tests/test_surface.py](../../lik-mcp/tests/test_surface.py) — asserts the **exact** tool set; must move from four to five and keep the "no raw-SQL" intent in its docstring.
- [lik-mcp/scripts/init_db.py](../../lik-mcp/scripts/init_db.py) — schema-only initializer keyed off `LIK_DB_NAME`; applies to an existing DB, does not create one.
- [lik-mcp/src/lik_mcp/__main__.py](../../lik-mcp/src/lik_mcp/__main__.py) / [settings.py](../../lik-mcp/src/lik_mcp/settings.py) / [auth.py](../../lik-mcp/src/lik_mcp/auth.py) — server launch; `LIK_ENV=local/test`→`StubVerifier` (token treated as caller email); DB selected by `LIK_DB_NAME`.
- [discovery-catalog-sync/SKILL.md](../../discovery-catalog-sync/SKILL.md) — the CQL crawl + one-row-per-page model to mirror for the sync skill.
- [dl-project-index-query/SKILL.md](../../dl-project-index-query/SKILL.md) — the live-instructions pattern the query skill deliberately does **not** copy; frontmatter/trigger style to reuse.

### Institutional Learnings

- None — `docs/solutions/` does not exist in this repo.

### External References

- None used — internal, well-patterned work (MCP tool + test pattern, SKILL.md pattern both exist locally).

---

## Key Technical Decisions

- **`list_catalog_entries` stays intent-named, bounded by `entry_type`.** It does not reintroduce a generic query tool — it filters on a discovery key and returns whole rows, no caller-supplied predicate. The tool count moving 4→5 is a deliberate, scoped exception to AE6's literal "four tools," not a relaxation of the "no raw-SQL escape hatch" rule. (see origin: K2)
- **`entry_type = "index"`** for project-index pages — the literal v0.4 enum match, distinct from the `project-summary` rows used in existing tests. (see origin: K3)
- **Cross-version reads, per-version writes.** `read_confirmations` aggregates across all versions of a source so a query never silently sees count=0 just because the page was edited since it was confirmed (this is what makes the K5 concern from origin tractable). `confirm_source` still writes per exact version — a confirmation is a statement about the version someone actually saw. The Query skill uses the live page `version` to label which returned confirmations are "current" vs "prior," and weighs accordingly. (see origin: K5; supersedes the earlier same-version-only approach)
- **`confirm_source` passes the user's email as the token** so `confirmed_by` is the real confirmer, not the default `service@navapbc.com` — the StubVerifier treats the token as the caller email in local/test.
- **`likdb_local` provisioned manually, once.** `createdb likdb_local` then `init_db.py` against it; documented in the README rather than wired into docker-compose, because entrypoint init scripts only fire on a fresh volume. The existing `_test`-suffix gate guarantees the suite can never truncate `likdb_local`. (see origin: R12)

---

## Open Questions

### Resolved During Planning

- How should the query skill enumerate when no single project is named? — Three-level user-gated escalation; Level 2 uses the new `list_catalog_entries`. (origin K1)
- Where does the synced catalog live so it survives tests? — A persistent `likdb_local`, separate from disposable `likdb_test`. (origin R12)

### Deferred to Implementation

- Exact `subject` derivation heuristic from a free-text question in the query skill (how to turn "the Atlas project" into `project: Atlas`) — refine during manual runs against real page titles.
- Whether `list_catalog_entries` should also accept an optional `category` filter — add only if Level 2 scans prove too coarse in practice; out of scope for now.

---

## Implementation Units

- U1. **Provision a persistent `likdb_local`**

**Goal:** A durable local database holding the synced catalog, separate from the disposable test DB, with the setup documented so it's reproducible.

**Requirements:** R6

**Dependencies:** None

**Files:**
- Modify: `lik-mcp/README.md` (add a "Local database" subsection: `docker compose exec db createdb -U lik likdb_local`, then `LIK_DB_NAME=likdb_local uv run python scripts/init_db.py`; note the manual MCP server runs `LIK_ENV=local LIK_DB_NAME=likdb_local`).
- Modify: `lik-mcp/.env.example` (document `likdb_local` as the manual-testing target alongside the existing `likdb_test` note).

**Approach:**
- Reuse `scripts/init_db.py` unchanged — it already targets whatever `LIK_DB_NAME` resolves to and only creates schema. The only new artifact is the `createdb` step plus docs.
- Make clear in the README that pytest stays pointed at `likdb_test` and the manual MCP server at `likdb_local`; switching is env-only, no code change.

**Patterns to follow:**
- The existing README "Initialize a deployed database" section already shows the `LIK_DB_*` override idiom — extend it, don't reinvent.

**Test scenarios:**
- Test expectation: none — ops/docs only; verified by the manual smoke check in Verification.

**Verification:**
- `docker compose exec db createdb -U lik likdb_local` succeeds; `LIK_DB_NAME=likdb_local uv run python scripts/init_db.py` prints both `catalog` and `confirmations` as public tables.
- `uv run pytest` still runs against `likdb_test` and leaves `likdb_local` untouched.

---

- U2. **Add the `list_catalog_entries(entry_type)` MCP tool**

**Goal:** A fifth intent-named tool that returns all catalog rows for one `entry_type`, powering the query skill's Level 2.

**Requirements:** R5

**Dependencies:** None (independent of U1)

**Files:**
- Modify: `lik-mcp/src/lik_mcp/catalog.py` (add a `ListResult` model and `list_catalog_entries(db, entry_type)` function).
- Modify: `lik-mcp/src/lik_mcp/server.py` (register the `list_catalog_entries` tool; `verifier.verify(token)` then delegate).
- Modify: `lik-mcp/tests/test_catalog.py` (new test for list-by-type and empty-miss).
- Modify: `lik-mcp/tests/test_surface.py` (expected tool set 4→5; update docstring to keep the "no raw-SQL escape hatch" intent explicit).

**Approach:**
- Mirror `lookup_catalog_entry`'s structure: a `SELECT * FROM catalog WHERE entry_type = %s ORDER BY subject`, serialize each row with the existing `_serialize`, return `ListResult(count, entries)`.
- No `category`/text predicate — bounded purely by the `entry_type` discovery key (Key Technical Decisions).
- A type with no rows returns `count=0, entries=[]`, never an error (parallels lookup's clean miss).

**Technical design:** *(directional guidance, not implementation specification)*
- `ListResult(BaseModel)`: `count: int`, `entries: list[dict]`.
- `list_catalog_entries(db, entry_type) -> ListResult` alongside the existing catalog functions; tool wrapper in `server.py` matching the other four.

**Patterns to follow:**
- `lookup_catalog_entry` (catalog.py) for the read/serialize shape; the `@mcp.tool(name=...)` wrappers in server.py for registration and token verification.

**Test scenarios:**
- Happy path: register three rows (two `entry_type="index"`, one `"project-summary"`) → `list_catalog_entries("index")` returns exactly the two index rows, ordered by `subject`.
- Edge case: `list_catalog_entries("no-such-type")` returns `count=0`, `entries=[]` (clean, not an error) — parallels `test_lookup_miss_returns_not_found`.
- Integration / surface: `server.list_tools()` returns exactly the five intent-named tools including `list_catalog_entries` and still no generic SQL tool (update `test_only_four_tools` accordingly, including its name/docstring).

**Verification:**
- `uv run pytest` green, including the updated surface test asserting five tools.
- The tool is callable via the running MCP server and returns rows written by the sync skill.

---

- U3. **`lik-sync-catalog-from-project-indexes` skill (DL-creation)**

**Goal:** A self-contained skill that crawls Confluence project-index pages and registers one Catalog row each via `register_catalog_entry`, idempotently.

**Requirements:** R1, R2, R7

**Dependencies:** U1 (a DB to write to for a real run); conceptually independent of U2.

**Files:**
- Create: `lik-sync-catalog-from-project-indexes/SKILL.md`

**Approach:**
- Mirror `discovery-catalog-sync/SKILL.md`'s structure and canonical CQL, but swap the Confluence-table sink for per-page `register_catalog_entry` calls.
- Frontmatter `name` + `description` with triggers ("sync project indexes into the catalog", "refresh the project-index catalog").
- Step 1 — `searchConfluenceUsingCql` with `cql: label = "project-index" AND type = page`, limit 250; collect `title`, `webUrl`, `space.name`, `summary`, `version`/`lastModified`, page ID, `author`.
- Step 2 — per page, build the `CatalogEntry`: `entry_type="index"`, `subject="project: <title>"`, `location=webUrl`, `store_kind="confluence"`, `locator=<pageId>`, `source_refs=[{id:<pageId>, version:<version>}]`, `category`/`access_groups` left default, `computed_by="lik-sync-catalog-from-project-indexes"`, `row_provenance="skill"`; call `register_catalog_entry(entry)`.
- Step 3 — tally `RegisterResult.status` (`inserted` vs `updated`) and report `N pages seen, X inserted, Y updated`.
- Notes — idempotent upsert on the key (re-runs update in place); run on demand only; writes to whatever DB the MCP server points at (`likdb_local` for manual testing); the CQL is the canonical source of truth.

**Patterns to follow:**
- `discovery-catalog-sync/SKILL.md` Steps 1 & 5 (CQL, summary block); `CatalogEntry` field names from catalog.py.

**Test scenarios:**
- Test expectation: none — natural-language skill procedure with no automated harness; its purpose is manual testing. Verified by the end-to-end run below.

**Verification:**
- Running the skill against `likdb_local` populates one `index` row per project-index page; a second run reports rows as `updated`, not duplicated (`SELECT count(*)` stable).
- Spot-check a row via `lookup_catalog_entry("index", "project: <known title>")` returns the expected `location`/`locator`.

---

- U5. **Make `read_confirmations` cross-version**

**Goal:** `read_confirmations` returns confirmations for all versions of a cited source, each row carrying its version, so the consumer decides how to weigh current vs prior trust.

**Requirements:** R9

**Dependencies:** None (independent code change; U4 consumes it)

**Files:**
- Modify: `lik-mcp/src/lik_mcp/confirmations.py` (drop `version` from the `_SELECT` WHERE; match on `store_kind` + `location` + `locator`; keep `version` in the returned columns; order by `version`, `created_at`).
- Modify: `lik-mcp/tests/test_confirmations.py` (rewrite `test_version_bound_trust` to assert cross-version aggregation; keep `test_duplicate_deduped` and `test_unresolvable_citation_rejected` intact).

**Approach:**
- Only the read changes. `confirm_source` and the `confirmations_unique` constraint (per `confirmed_by, store_kind, location, locator, version`) are untouched — writes stay per-version.
- The `Citation` input shape is unchanged; `version` is simply ignored in the read's WHERE clause (the caller still passes a well-formed citation). No tool signature change, so `test_surface.py` is unaffected by this unit.

**Patterns to follow:**
- The existing `_SELECT` / `read_confirmations` structure in confirmations.py; the `_citation(**overrides)` test helper.

**Test scenarios:**
- Happy path: confirm the same source at `version="v5"` and `version="v7"` (same `store_kind`/`location`/`locator`) → `read_confirmations` with any version returns `count=2`, with both versions present in `confirmations`.
- Edge case (redefines AE4): confirm only `v5` → `read_confirmations` with a `v7` citation returns `count=1` and the row's `version` is `"v5"` (previously this returned 0). Update the docstring to describe the new cross-version semantics.
- Regression: `test_duplicate_deduped` still yields `count=1` for one user confirming one source-version twice; unresolvable citation still writes nothing.

**Verification:**
- `uv run pytest` green with the rewritten confirmations test.
- A query run shows a source's confirmations even after its page version changed since the confirmation.

---

- U4. **`lik-query-project-index` skill (Query + confirmations)**

**Goal:** A self-contained skill that answers project questions from the Catalog via the three-level user-gated escalation, ranks cited sources by confirmation trust (current and prior version), and lets the user confirm a source.

**Requirements:** R3, R4, R7, R8, R9

**Dependencies:** U2 (Level 2 needs `list_catalog_entries`); U5 (cross-version ranking); U3 + U1 for a populated DB to query in a real run.

**Files:**
- Create: `lik-query-project-index/SKILL.md`

**Approach:**
- Self-contained (no live-instructions fetch). Frontmatter `name` + `description` with triggers like the existing `dl-project-index-query` description, minus the Step 0 indirection.
- Level 1 — derive `subject = "project: <name>"` from the question → `lookup_catalog_entry("index", subject)` → on hit, `getConfluencePage` at `location`/`locator` → answer from that page.
- On miss — **pause and ask the user**: list all project-index entries, or skip to Confluence search?
- Level 2 — `list_catalog_entries("index")` → scan returned `subject`/`category` in-agent against the question terms → follow the most relevant `location` pointers → answer. If nothing relevant, ask before Level 3.
- Level 3 — `searchConfluenceUsingCql` with `label = "project-index" AND text ~ "<terms>"` → read top matches → answer, noting it came from a bounded fan-out.
- Rank (F5) — for each cited page build `Citation{store_kind:"confluence", location:webUrl, locator:pageId, version:<live page version>}` → `read_confirmations(citation)` returns confirmations across all versions → split into current-version vs prior-version (compare each row's `version` to the live page version), display both beside the citation, and weight ranking with current-version trust counting more than prior.
- Confirm (F6) — offer to confirm a cited source; on the user's pick, `confirm_source(citation)` **passing the user's email as the token** so `confirmed_by` is real, using the live page `version` so the confirmation attaches to the current version → report `recorded`/`duplicate`/`rejected`.
- Notes — a miss or dangling pointer is a cache miss, never an error; because `read_confirmations` is cross-version (U5), a page edited since it was confirmed still surfaces its prior-version trust rather than silently reading zero.

**Technical design:** *(directional guidance, not implementation specification)*
```
ask(question):
  hit = lookup_catalog_entry("index", subject_of(question))
  if hit.found: sources = [follow(hit)]
  else if user_confirms("list catalog?"):
        rows = list_catalog_entries("index"); sources = follow(scan(rows, question))
  if not sources and user_confirms("search Confluence?"):
        sources = follow(cql_search(question))
  for s in sources:
      rows = read_confirmations(citation(s)).confirmations   # all versions
      s.current = count(rows where version == s.live_version)
      s.prior   = count(rows where version != s.live_version)
  answer(rank_by_trust(sources))                              # current weighed over prior
  if user picks a source: confirm_source(citation(s), token=user_email)  # live version
```

**Patterns to follow:**
- `dl-project-index-query/SKILL.md` frontmatter/trigger phrasing; `Citation` field names from citations.py; tool names from server.py.

**Test scenarios:**
- Test expectation: none — natural-language skill procedure with no automated harness; its purpose is manual testing. Verified by the end-to-end runs below.

**Verification:**
- Named-project question → Level 1 hit, answer cites the right page with a confirmation count shown.
- Enumeration question ("which projects mention X") → Level 1 miss → user-gated Level 2 lists and scans → answer; choosing "skip" instead routes to Level 3 Confluence search.
- After answering, confirming a source records it (`recorded`); re-confirming the same source-version returns `duplicate`; a subsequent query shows the incremented count and ranks that source higher.

---

## System-Wide Impact

- **API surface parity:** `list_catalog_entries` is the only *tool-set* change; `test_surface.py` is the contract test and must move 4→5 in lockstep (U2). `read_confirmations` changes its read semantics but not its signature (U5), so the surface test is unaffected by U5.
- **Interaction graph:** the query skill is the first caller to chain `lookup`/`list` → Confluence read → `read_confirmations` → `confirm_source` in one flow; the sync skill is the first real `register_catalog_entry` producer.
- **State lifecycle risks:** confirmations are still *written* per version (dedup intact), but *read* across versions (U5) — so a page edited between confirm and query surfaces prior-version trust instead of reading zero. The query skill labels current vs prior so prior trust isn't mistaken for current.
- **Unchanged invariants:** write rules, upsert-on-key semantics, `confirm_source`'s per-version dedup constraint, the `_test`-suffix truncate gate, and `LIK_ENV` fail-closed behavior are all unchanged.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Adding a 5th tool silently breaks `test_surface.py` (exact-set assertion). | U2 explicitly updates that test and its docstring; surface test is a verification gate. |
| Version mismatch makes confirmations look broken (count 0). | U5 makes `read_confirmations` cross-version, so prior-version trust always surfaces; the skill labels current vs prior rather than hiding either. |
| Cross-version read silently changes AE4's meaning, surprising a reader of the old test. | U5 rewrites `test_version_bound_trust` with a docstring describing the new semantics; R9 records the redefinition explicitly. |
| Confluence Rovo MCP or lik-mcp not actually connected in the test env. | Origin lists both as unverified assumptions; confirm connectivity before the manual run (U1 verification touches lik-mcp; sync touches Confluence). |
| Manual MCP server accidentally pointed at `likdb_test`, losing synced data on next `pytest`. | README documents the env split; `_test` gate prevents the reverse (suite truncating dev). |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-24-02-project-index-catalog-skills-requirements.md](../brainstorms/2026-06-24-02-project-index-catalog-skills-requirements.md)
- Related code: [lik-mcp/src/lik_mcp/catalog.py](../../lik-mcp/src/lik_mcp/catalog.py), [server.py](../../lik-mcp/src/lik_mcp/server.py), [confirmations.py](../../lik-mcp/src/lik_mcp/confirmations.py)
- Related skills: [discovery-catalog-sync/SKILL.md](../../discovery-catalog-sync/SKILL.md), [dl-project-index-query/SKILL.md](../../dl-project-index-query/SKILL.md)
- Prior plan (predates v0.4): [docs/plans/2026-06-24-01-postgres-mcp-connector-plan.md](2026-06-24-01-postgres-mcp-connector-plan.md)
