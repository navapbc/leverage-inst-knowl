---
title: "feat: Catalog fuzzy & partial query"
type: feat
status: active
date: 2026-06-25
origin: docs/brainstorms/2026-06-25-01-catalog-fuzzy-partial-query-requirements.md
---

# feat: Catalog fuzzy & partial query

## Summary

Add a new `search_catalog_entries` MCP tool that does server-side partial + fuzzy
matching on `subject` (via Postgres `pg_trgm`), returning a bounded, ranked candidate
set. Wire it into `lik-query-project-index` Level 1 as a fuzzy fallback after the exact
lookup. Exact-match `lookup_catalog_entry` and the Level 2/3 escalation are unchanged.

---

## Problem Frame

The Catalog only does exact-match lookup on `(entry_type, subject)`. The sole fallback
today is `list_catalog_entries` (pull every row for a type, scan in-memory in the skill),
which won't scale to the thousands-of-rows-across-many-entry_types the Catalog is expected
to hold. See origin for full framing.

---

## Requirements

- R1. A server-side query takes `entry_type` + a query term and returns ranked candidate
  rows matched by **partial** comparison on `subject`.
- R2. The same query matches **fuzzy** — typos, reordered or near-miss terms.
- R3. Results are **bounded and ranked** (top-N with match scores), never the full table.
- R4. An optional `category` filter narrows before matching.
- R5. Exact-match `lookup_catalog_entry` behavior is unchanged.
- R6. `lik-query-project-index` Level 1 calls the new query on an exact miss (no widening
  prompt) and answers from a candidate hit; Level 2 and Level 3 unchanged.

**Origin acceptance examples:** none defined in origin (requirements doc used Success
Criteria, traced above as R1–R6).

---

## Scope Boundaries

- No semantic / conceptual search inside the Catalog.
- No abbreviation↔full-name resolution (e.g. "CMS" ↔ "Centers for Medicare").
- No full-text / tsvector machinery.
- No change to exact-match `lookup_catalog_entry` or to Level 2/3 of the skill.
- No new ACL/access_groups filtering — search matches the **existing** no-filter parity
  of `lookup`/`list` (query-time ACL is a separate deferred slice, `db/init.sql:33`).

### Deferred to Follow-Up Work

- Alias/synonym data to bridge abbreviations: future effort (origin Non-Goals).
- Similarity-threshold tuning against real catalog data: implementation-time, then revisit.

---

## Context & Research

### Relevant Code and Patterns

- `lik-mcp/src/lik_mcp/catalog.py` — `lookup_catalog_entry` / `list_catalog_entries`
  (lines 105-126) are the function shape to mirror: `db.connection()`, parameterized SQL,
  `_serialize(row)`, return a Pydantic `*Result` model. `ListResult` (56-58) is the model
  shape to mirror for a ranked result.
- `lik-mcp/src/lik_mcp/server.py` — `_lookup_catalog_entry` / `_list_catalog_entries`
  (79-98): `@mcp.tool(name=...)`, request log, `_authorize(tool, token)`, result log.
- `lik-mcp/db/init.sql` — table + `catalog_access_groups_gin` GIN index (34); idempotent
  `CREATE … IF NOT EXISTS` convention and the inline ALTER migration pattern (53-55).
- `lik-mcp/tests/test_catalog.py` — `_entry(**overrides)` helper + `db` fixture style.
- `lik-mcp/tests/test_surface.py` — asserts the exact set of advertised tool names.
- `lik-mcp/tests/conftest.py` — `db` fixture applies `init.sql`; suite TRUNCATEs between tests.

### Institutional Learnings

- `docs/solutions/` not searched in depth; no prior pg_trgm learning expected. Skip.

### External References

- None. `pg_trgm` is standard Postgres contrib; local patterns cover the rest.

---

## Key Technical Decisions

- **New tool `search_catalog_entries`, not an extension of `list`/`lookup`**: keeps each
  tool's intent crisp and the surface assertion in `test_surface.py` honest. (origin Open
  Questions)
- **`pg_trgm` with a GIN trigram index on `subject`**: one extension, one index; delivers
  partial + fuzzy in a single mechanism (see origin: approaches table).
- **Match predicate = substring OR trigram similarity, ranked by similarity**: `ILIKE
  '%term%'` catches partial/substring matches that fall below the trigram floor; the
  trigram `%` operator catches typos/reorders. Order by `similarity(subject, term)` DESC.
  This keeps both R1 (partial) and R2 (fuzzy) in one query. Exact predicate/threshold
  values are implementation-time.
- **`category` is an optional equality pre-filter, not trigram-indexed**: it narrows the
  candidate set before matching; it is not itself fuzzy-matched. (origin Open Questions)
  **Note:** `category` is an undefined free-text field (`text` nullable, no enum/CHECK;
  `v0.4/05-architecture.md:71` calls it a descriptive classification + ACL-mapping input).
  The only current writer, `lik-sync-catalog-from-project-indexes`, does **not** set it, so
  every `entry_type="index"` row has `category = NULL`. The filter is therefore **inert
  for the skill's current use** — kept as a cheap, forward-looking capability for future
  entry_types that populate category. Do not wire it into `lik-query-project-index` expecting
  it to match anything today.
- **No ACL filtering**: parity with existing `lookup`/`list`. Adding it here would diverge
  from current behavior and belongs in the separate query-time-ACL slice.

---

## Open Questions

### Resolved During Planning

- New tool vs. extend → **new tool** `search_catalog_entries`.
- `category` trigram-indexed vs. equality filter → **equality pre-filter only**.
- Default top-N → **`limit` param, default 10**; caller may override.

### Deferred to Implementation

- Exact minimum similarity threshold (and whether to expose it as a tool param vs. set the
  `pg_trgm.similarity_threshold` GUC) — tune against real data once rows exist.
- Whether to also return the trigram score in each entry or as a sibling field — settle
  when writing `SearchResult`.

---

## Implementation Units

- U1. **Enable pg_trgm + trigram index on subject**

**Goal:** Make trigram matching available and indexed so search is fast at scale.

**Requirements:** R2, R3

**Dependencies:** None

**Files:**
- Modify: `lik-mcp/db/init.sql`

**Approach:**
- Add `CREATE EXTENSION IF NOT EXISTS pg_trgm;` near the top (idempotent, matches the
  file's existing convention).
- Add `CREATE INDEX IF NOT EXISTS catalog_subject_trgm ON catalog USING GIN (subject gin_trgm_ops);`
  alongside the existing `catalog_access_groups_gin`.
- This is the conftest-applied schema, so the test DB picks it up automatically.

**Patterns to follow:**
- `db/init.sql:34` GIN index; the `IF NOT EXISTS` idempotency throughout the file.

**Test scenarios:**
- Test expectation: none — pure schema/scaffolding. Exercised indirectly by U2's search
  tests (which fail if the extension/index is absent). Note: the deploy role may need
  CREATE privilege for the extension; flag if the test DB can't create it.

**Verification:**
- `init.sql` applies cleanly on a fresh DB and is re-runnable without error; U2 tests pass.

---

- U2. **`search_catalog_entries` query function + result model**

**Goal:** Server-side ranked partial+fuzzy search over `subject`, optionally filtered by
`category`, bounded by `limit`.

**Requirements:** R1, R2, R3, R4

**Dependencies:** U1

**Files:**
- Modify: `lik-mcp/src/lik_mcp/catalog.py` (add `SearchResult` model + `search_catalog_entries`)
- Test: `lik-mcp/tests/test_catalog.py`

**Approach:**
- New `SearchResult(BaseModel)` mirroring `ListResult` (`count`, `entries`), with each
  entry carrying its match score (field name settled in impl).
- New `search_catalog_entries(db, entry_type, query, *, category=None, limit=10)`:
  one parameterized SELECT — `WHERE entry_type = %s AND (subject ILIKE %s OR subject % %s)`,
  optional `AND category = %s`, `ORDER BY similarity(subject, %s) DESC LIMIT %s`.
  Reuse `_serialize` for each row.
- A no-match query is a clean empty result, never an error (mirror `list`).

**Technical design:** *(directional guidance, not implementation spec)*

```
search_catalog_entries(db, entry_type, query, category=None, limit=10):
    SELECT *, similarity(subject, :query) AS score
    FROM catalog
    WHERE entry_type = :entry_type
      AND (subject ILIKE '%' || :query || '%' OR subject % :query)
      [AND category = :category]
    ORDER BY score DESC
    LIMIT :limit
    -> SearchResult(count, entries=[serialized rows incl. score])
```

**Patterns to follow:**
- `catalog.py:117-126` `list_catalog_entries` (connection, serialize, Result model).

**Test scenarios:**
- Happy path: partial substring of a subject returns the matching row(s). (R1)
- Happy path: a typo'd query (e.g. "Atals" for "Atlas") returns "Atlas" via trigram. (R2)
- Happy path: reordered words match (e.g. "Medicare Centers" finds "Centers for Medicare"). (R2)
- Edge case: results ordered by descending similarity — closest match first. (R3)
- Edge case: `limit` caps the number of rows returned. (R3)
- Edge case: query matching nothing returns `count == 0`, `entries == []`, no error.
- Edge case: `category` filter excludes rows of other categories that otherwise match. (R4)
- Edge case: search is scoped to `entry_type` — rows of other types never returned.

**Verification:**
- `uv run pytest tests/test_catalog.py` passes; ranked, bounded, type-scoped results.

---

- U3. **Expose `search_catalog_entries` as an MCP tool**

**Goal:** Advertise the new query as an intent-named, authorized MCP tool.

**Requirements:** R1, R3, R5

**Dependencies:** U2

**Files:**
- Modify: `lik-mcp/src/lik_mcp/server.py` (import + `@mcp.tool` wrapper)
- Modify: `lik-mcp/tests/test_surface.py` (add the new name to the expected set)
- Test: `lik-mcp/tests/test_catalog.py` covers the function; surface test covers exposure.

**Approach:**
- Add `_search_catalog_entries(entry_type, query, category=None, limit=10, token=None)`
  mirroring `_list_catalog_entries`: request log, `_authorize("search_catalog_entries",
  token)`, call the function, result-count log.
- Import `SearchResult` / `search_catalog_entries` from `.catalog`.
- `lookup_catalog_entry` wrapper untouched (R5).

**Patterns to follow:**
- `server.py:90-98` `_list_catalog_entries` — logging + `_authorize` shape.

**Test scenarios:**
- Surface: `test_only_intent_named_tools` expects the set plus `search_catalog_entries`;
  no raw-SQL tool introduced. (R5 — existing names preserved)
- Happy path (optional, if a server-level test is added): an authorized call returns a
  `SearchResult`; an unverified token is denied (mirror existing auth behavior).

**Verification:**
- `uv run pytest tests/test_surface.py tests/test_catalog.py` passes; tool listed.

---

- U4. **Wire the new tool into lik-query-project-index Level 1**

**Goal:** On an exact Level 1 miss, call `search_catalog_entries` (no widening prompt)
before falling to Level 2.

**Requirements:** R6

**Dependencies:** U3

**Files:**
- Modify: `.claude/skills/lik-query-project-index/SKILL.md` (Level 1 section, currently lines 24-31)

**Approach:**
- Extend "Level 1 — exact Catalog lookup": on a miss, call `search_catalog_entries` with
  `entry_type = "index"` and the question's key terms as `query`. On candidate hit(s),
  follow the pointer(s) (`getConfluencePage`) and answer → Rank & present.
- State explicitly that this fuzzy lookup is a bounded keyed lookup and runs **without**
  the "ask before widening" prompt (cite `v0.4/04-strategy.md:124`).
- Only on a fuzzy miss (no candidates) fall through to Level 2 — leave Level 2 (33-45) and
  Level 3 (47-54) text unchanged.

**Patterns to follow:**
- Existing Level 1/2/3 prose and the "ask the user first" gating used at Levels 2-3.

**Test scenarios:**
- Test expectation: none — skill is a Markdown instruction doc, no automated test harness.
  Verify by reading: Level 1 now has exact→fuzzy→(miss)→Level 2 ordering; the fuzzy step
  carries no widening prompt; Level 2/3 wording is byte-for-byte unchanged.

**Verification:**
- SKILL.md Level 1 describes the fuzzy fallback and its no-prompt rationale; Levels 2-3 intact.

---

## System-Wide Impact

- **API surface parity:** adds one tool; `lookup`/`list`/`register`/confirmations tools
  unchanged. `test_surface.py` is the guardrail and is updated in U3.
- **Unchanged invariants:** exact `lookup_catalog_entry` (R5); no ACL filtering added —
  search returns the same rows `lookup`/`list` would, preserving current blast radius.
- **Error propagation:** a no-match search is a clean empty result, mirroring `list` — no
  new error paths into the skill.
- **State lifecycle risks:** none — read-only query, no writes.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Deploy DB role lacks privilege to `CREATE EXTENSION pg_trgm` | `IF NOT EXISTS` is idempotent; flag in U1 — extension may need a one-time superuser/admin step in the real deploy. Test DB (docker) runs as a privileged role. |
| Trigram threshold too high → fuzzy misses; too low → noise | ILIKE-substring OR keeps partial matches regardless of score; threshold tuning deferred to impl against real data. |
| Large catalog: search latency | GIN trigram index (U1) keeps `ILIKE`/`%` fast; `LIMIT` bounds result size. |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-25-01-catalog-fuzzy-partial-query-requirements.md](docs/brainstorms/2026-06-25-01-catalog-fuzzy-partial-query-requirements.md)
- Related code: `lik-mcp/src/lik_mcp/catalog.py`, `lik-mcp/src/lik_mcp/server.py`, `lik-mcp/db/init.sql`
- Strategy: `v0.4/04-strategy.md:120` (permits partial/fuzzy on keys), `:124` (targeted keyed lookup)
