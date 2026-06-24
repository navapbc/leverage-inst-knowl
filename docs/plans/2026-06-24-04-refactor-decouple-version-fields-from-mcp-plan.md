---
title: "refactor: Decouple version fields from MCP capabilities"
type: refactor
status: completed
date: 2026-06-24
origin: docs/brainstorms/2026-06-24-04-decouple-version-fields-from-mcp-requirements.md
---

# refactor: Decouple version fields from MCP capabilities

## Summary

Two fields in the Discovery Layer store require version numbers that the Confluence MCP connector cannot provide, rendering the staleness and trust-weighing machinery inoperable. This refactor makes `confirmations.version` optional (empty-string default, mirroring the existing `locator` sentinel pattern), introduces a typed `SourceRef` model for `catalog.source_refs`, and adds a `fetched_at` timestamp as a proxy staleness signal when a real version is unavailable. No new columns are needed for confirmation recency — `created_at` already exists and is already returned.

---

## Problem Frame

`confirmations.version` and `catalog.source_refs[].version` are both `NOT NULL` today and hardcoded to `"1"` by skills because the Confluence MCP tools return no page version number. Until these fields are optional, skills cannot record honest confirmation or staleness signals for Confluence sources. See origin doc for full context.

---

## Requirements

- R1. A skill can call `confirm_source` without providing a version string and receive `status: recorded`.
- R2. `read_confirmations` returns rows with `created_at`, allowing a consumer to rank by recency.
- R3. A sync skill can register a `source_refs` entry without a version number and the row is accepted.
- R4. `source_refs[].fetched_at` is populated at sync time and is visible to reconciliation logic.
- R5. Dedup is not regressed: the same user cannot double-confirm the same Confluence source in a single run.
- R6. The `version` column is preserved in both `confirmations` and `source_refs` so stores that expose real versions can use it without another migration.

---

## Scope Boundaries

- No changes to the `last_validated_at` pipeline or reconciliation pass.
- No changes to store kinds other than Confluence.
- No real version-based drift detection (blocked on MCP; deferred).
- No changes to `catalog.locator` (already correctly optional with `NOT NULL DEFAULT ''`).

### Deferred to Follow-Up Work

- Real version-based drift detection when/if Confluence MCP exposes version numbers.
- Per-store version resolution strategy for GDocs, GSheets, BigQuery.
- Creating a `docs/solutions/` entry capturing the empty-string-sentinel / UNIQUE-constraint pattern (recommended once this lands; zero risk to defer).

---

## Context & Research

### Relevant Code and Patterns

- `lik-mcp/db/init.sql:42` — `locator text NOT NULL DEFAULT ''` with comment: "NOT NULL DEFAULT '' so the dedup key is reliable (a NULL never equals a NULL in UNIQUE)." This is the exact pattern to mirror for `version`.
- `lik-mcp/src/lik_mcp/citations.py:14-21` — `locator: str = ""` with a `@field_validator("locator", mode="before")` normalizing `None`/falsy to `""`. Mirror this for `version`.
- `lik-mcp/src/lik_mcp/citations.py:33-38` — `ShapeResolver.resolve()` currently gates on `bool(citation.version.strip())`. This check must be removed.
- `lik-mcp/src/lik_mcp/catalog.py:24` — `source_refs: list[Any]`. Introducing a typed `SourceRef` model here replaces the untyped list.
- `lik-mcp/src/lik_mcp/catalog.py:82` — `Json(params["source_refs"])` — if `source_refs` becomes `list[SourceRef]`, the serialization path must emit plain dicts (not Pydantic objects) before the `Json()` call.

### Institutional Learnings

- No `docs/solutions/` exists yet. Relevant patterns live directly in the codebase (see above).

---

## Key Technical Decisions

- **Empty string, not NULL, for `confirmations.version`:** NULL breaks the UNIQUE constraint dedup semantics (`NULL != NULL` in Postgres). Mirror `locator`: `NOT NULL DEFAULT ''`. (see origin: `docs/brainstorms/2026-06-24-04-decouple-version-fields-from-mcp-requirements.md`)
- **`Optional[str] = None` for `SourceRef.version` and `SourceRef.fetched_at`:** `source_refs` entries written before this change have no `fetched_at` key. A required field would break deserialization of legacy rows. Both fields are nullable.
- **Typed `SourceRef` model introduced:** `catalog.py`'s `list[Any]` is replaced with `list[SourceRef]` to enforce the new shape at the service boundary. This is additive — no breaking change to the DB column type (still `jsonb`).
- **Serialization: use `model_dump(mode="json")` per entry:** When iterating `source_refs` before the `Json()` call in `register_catalog_entry`, call `.model_dump(mode="json")` on each `SourceRef`. This handles `None` → JSON `null` and emits plain dicts that `json.dumps` can serialize. Do not update `_serialize` — it only iterates top-level row keys and would require a recursive rewrite to handle nested JSONB.
- **`fetched_at` must be typed `Optional[str]`, not `Optional[datetime]`:** `_serialize` does not recurse into JSONB fields. Storing a `datetime` object would produce non-serializable output. Skills pass an ISO 8601 string directly.
- **Legacy rows serialize with explicit `null` fields:** `model_dump(mode="json")` emits `{"id": "p1", "version": null, "fetched_at": null}` for a legacy entry with no `fetched_at`. Tests should assert `== None`, not "absent".

---

## Open Questions

### Resolved During Planning

- *Should `version` use NULL or empty string?* Empty string — required by the UNIQUE constraint semantics already established by `locator`.
- *Does `fetched_at` need a new DB column?* No — `source_refs` is already untyped `jsonb`; the field is added inside the JSON object with no DDL change.
- *Is `created_at` sufficient for confirmation recency?* Yes — it already exists on `confirmations` and is already returned by `read_confirmations`.

### Deferred to Implementation

- Whether to update `limitations.md` to note the partial resolution of the Confluence MCP version gap — low-stakes, implementer's judgment.
- Sort order side-effect: `_SELECT` in `confirmations.py` orders by `(version, created_at)`. With `version=""`, empty-string rows sort lexicographically before versioned rows. Not a correctness bug — callers should not assume the last row is the "latest version." No change needed; note for future query callers.

---

## Implementation Units

- U1. **Make `confirmations.version` optional in the DB schema**

**Goal:** Drop the `NOT NULL` hard requirement on `version` by adding an empty-string default, so the column can accept `""` without a value being supplied at insert time.

**Requirements:** R1, R5, R6

**Dependencies:** None

**Files:**
- Modify: `lik-mcp/db/init.sql`

**Approach:**
- Change line 43 from `version text NOT NULL` to `version text NOT NULL DEFAULT ''`.
- The unique constraint at line 48 is unchanged — `""` participates correctly (unlike NULL).
- `db/init.sql` uses `CREATE TABLE IF NOT EXISTS` and will not alter existing tables when run against a deployed DB. Add an idempotent `ALTER TABLE confirmations ALTER COLUMN version SET DEFAULT ''` statement after the `CREATE TABLE` block so the change also applies to existing instances.
- No data migration needed for rows — existing rows already have an explicit `version` value; the default only affects future inserts.

**Patterns to follow:**
- `lik-mcp/db/init.sql:42` — `locator text NOT NULL DEFAULT ''`

**Test scenarios:**
- Test expectation: none — pure DDL change; behavioral coverage lives in U2 and U4.

**Verification:**
- Running `psql "$CONNINFO" -f db/init.sql` on a fresh DB produces a `confirmations` table where inserting a row without `version` succeeds and stores `""`.

---

- U2. **Make `version` optional in `Citation` and relax `ShapeResolver`**

**Goal:** Allow `Citation` to carry an empty-string version so that tools (confirm_source, read_confirmations) accept Confluence-sourced citations without a version.

**Requirements:** R1, R2, R5

**Dependencies:** U1

**Files:**
- Modify: `lik-mcp/src/lik_mcp/citations.py`

**Approach:**
- Add `version: str = ""` default to `Citation` (currently `version: str`, required).
- Add a `@field_validator("version", mode="before")` that normalizes `None`/falsy to `""`, mirroring the existing `locator` validator.
- In `ShapeResolver.resolve()`, remove `and bool(citation.version.strip())`. The resolver should accept a citation as valid when `store_kind` is known and `location` is non-empty — `version` is no longer a validity gate.

**Patterns to follow:**
- `lik-mcp/src/lik_mcp/citations.py:14-21` — `locator` field and normalizing validator.

**Test scenarios:**
- Happy path: `Citation(store_kind="confluence", location="https://…", locator="123")` resolves without error (version defaults to `""`).
- Happy path: `Citation(store_kind="confluence", location="https://…", version="")` resolves (empty string explicit).
- Happy path: `Citation(store_kind="confluence", location="https://…", version="v5")` still resolves (non-empty version still accepted).
- Edge case: `Citation(store_kind="confluence", location="https://…", version=None)` normalizes to `""` and resolves.
- Error path: `Citation(store_kind="unknown_store", location="https://…")` is still rejected by `ShapeResolver` (store_kind check is the gate).
- Error path: `Citation(store_kind="confluence", location="")` is still rejected (empty location).

**Verification:**
- `uv run pytest tests/test_citations.py` (or equivalent) passes with all new scenarios green.
- `confirm_source` called with a version-free Confluence citation returns `status: recorded`, not `status: rejected`.

---

- U3. **Introduce `SourceRef` model and `fetched_at` support in `catalog.py`**

**Goal:** Replace `list[Any]` in `CatalogEntry.source_refs` with a typed `SourceRef` model that accepts an optional `version` and a new optional `fetched_at` timestamp. Fix the serialization path so Pydantic objects are emitted as plain dicts before the `Json()` adapter.

**Requirements:** R3, R4, R6

**Dependencies:** None (independent of U1/U2)

**Files:**
- Modify: `lik-mcp/src/lik_mcp/catalog.py`

**Approach:**
- Define a `SourceRef` Pydantic model:
  - `id: str` — required
  - `version: Optional[str] = None` — nullable; stores that expose a real version populate it
  - `fetched_at: Optional[str] = None` — ISO 8601 string; skills populate at sync time; `None` for legacy rows
- Change `CatalogEntry.source_refs` from `list[Any]` to `list[SourceRef]`.
- In `register_catalog_entry`, serialize each `SourceRef` to a plain dict via `.model_dump(mode="json")` before the `Json()` wrapping. This is required — passing `SourceRef` instances directly to `Json()` will raise `TypeError: Object of type SourceRef is not JSON serializable`.

**Patterns to follow:**
- `lik-mcp/src/lik_mcp/citations.py:9-21` — Pydantic model with optional fields and defaults.
- `lik-mcp/src/lik_mcp/catalog.py:75-82` — `_serialize` and `Json()` usage.

**Test scenarios:**
- Happy path: `register_catalog_entry` with `source_refs=[{"id": "123", "version": null, "fetched_at": "2026-06-24T19:48:40Z"}]` succeeds and the row round-trips correctly.
- Happy path: `source_refs=[{"id": "123"}]` (legacy shape — no `version`, no `fetched_at`) is accepted; round-trip returns `source_refs[0]["version"] == None` and `source_refs[0]["fetched_at"] == None` (explicit null, not absent key).
- Happy path: `source_refs` with non-null version — `source_refs=[{"id": "123", "version": "v5"}]` — round-trips with `version == "v5"` preserved (R6).
- Happy path: `source_refs=[{"id": "123", "version": "v5", "fetched_at": null}]` — version present, fetched_at absent — accepted.
- Edge case: `source_refs=[]` (empty list) accepted — existing behavior preserved.
- Integration: after `register_catalog_entry`, `list_catalog_entries` returns the row with the correct `source_refs` shape including `fetched_at`.

**Verification:**
- `uv run pytest tests/test_catalog.py` passes with new `source_refs` scenarios green.
- A round-trip via MCP tool calls (`register_catalog_entry` → `list_catalog_entries`) returns `fetched_at` in the `source_refs` of the registered row.

---

- U4. **Update test coverage for version-optional confirmations and typed source_refs**

**Goal:** Update existing confirmation tests to cover the `version=""` case and add new catalog tests for `source_refs` with `fetched_at`.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** U1, U2, U3

**Files:**
- Modify: `lik-mcp/tests/test_confirmations.py`
- Modify: `lik-mcp/tests/test_catalog.py`

**Approach:**
- In `test_confirmations.py`:
  - Add a `_citation_no_version()` fixture (or parametrize) that omits version, so tests exercise `version=""`.
  - `test_read_is_cross_version`: add a case confirming with `version=""` and verifying it appears in `read_confirmations` results alongside versioned rows. Also add the reverse: confirm with `version="v5"`, read with `version=""`, assert count includes that row (cross-version read is symmetric).
  - `test_duplicate_deduped`: add a case confirming the same source twice with `version=""` returns `duplicate` on the second call.
  - Add an end-to-end test: call `confirm_source` with `version=None` (not `""`), assert `status: recorded` (exercises the normalizing validator through the full call path, not just `ShapeResolver`).
  - Add assertion in `test_read_is_cross_version` that `read_confirmations` results include a `created_at` field in ISO 8601 format (R2).
- In `test_catalog.py`:
  - Add `test_source_refs_with_fetched_at`: register with `source_refs=[{"id": "p1", "fetched_at": "2026-06-24T00:00:00Z"}]`, assert `list_catalog_entries` returns the row with `fetched_at == "2026-06-24T00:00:00Z"`.
  - Add `test_source_refs_legacy_shape`: register with `source_refs=[{"id": "p1"}]`, assert the row is accepted and `source_refs[0]["fetched_at"] == None` (explicit null — not absent — after `model_dump(mode="json")` serialization).
  - Add `test_source_refs_version_preserved`: register with `source_refs=[{"id": "p1", "version": "v5"}]`, assert `source_refs[0]["version"] == "v5"` (R6 round-trip).

**Patterns to follow:**
- `lik-mcp/tests/test_confirmations.py:8-11` — `_citation()` fixture pattern.
- `lik-mcp/tests/conftest.py:51-53` — `clean` fixture TRUNCATEs tables per test; no additional teardown needed.

**Test scenarios:**
- (All scenarios are themselves the test scenarios for this unit — see Approach above.)

**Verification:**
- `uv run pytest` passes with zero regressions across all existing and new tests.

---

- U5. **Type `ConfirmationsResult` so skills know which fields to use when `version` is empty**

**Goal:** Replace `list[dict]` in `ConfirmationsResult.confirmations` with a typed `ConfirmationRow` model that explicitly surfaces `created_at` as the recency signal. This makes the MCP tool response schema self-documenting and lets a skill confidently use `created_at` for weighing when `version` is `""`.

**Requirements:** R2

**Dependencies:** U2

**Files:**
- Modify: `lik-mcp/src/lik_mcp/confirmations.py`

**Approach:**
- Define a `ConfirmationRow` Pydantic model:
  - `id: int`
  - `confirmed_by: str`
  - `version: str` — will be `""` for Confluence sources after this refactor
  - `created_at: str` — ISO 8601; use for recency weighing when `version` is empty
- Change `ConfirmationsResult.confirmations` from `list[dict]` to `list[ConfirmationRow]`.
- `read_confirmations` already returns `created_at` in the per-row dict; no query change needed — only the return type changes.
- The MCP server's `read_confirmations` tool docstring should note that `created_at` is the recency signal when `version` is `""`.

**Patterns to follow:**
- `lik-mcp/src/lik_mcp/citations.py:9-21` — typed Pydantic model for a data-transfer object.
- `lik-mcp/src/lik_mcp/confirmations.py:14-16` — `ConfirmationsResult`.

**Test scenarios:**
- Happy path: `read_confirmations` returns `ConfirmationsResult` where each row has `id`, `confirmed_by`, `version`, and `created_at` as string fields (not absent).
- Edge case: when `version=""`, `created_at` is present and non-empty in the returned row — a skill can rank by it.

**Verification:**
- `ConfirmationsResult.confirmations` is typed as `list[ConfirmationRow]`, not `list[dict]`.
- A `read_confirmations` call against a Confluence-sourced confirmation returns a row where `version == ""` and `created_at` is a parseable ISO 8601 string.

---

- U6. **Update skill documentation to reflect new `source_refs` shape**

**Goal:** Update the `sync-catalog-from-project-indexes` SKILL.md so future skill invocations populate `fetched_at` and omit the hardcoded `version: "1"` that triggered this refactor.

**Requirements:** R3, R4

**Dependencies:** U3

**Files:**
- Modify: `.claude/skills/sync-catalog-from-project-indexes/SKILL.md`

**Approach:**
- In Step 2 ("Register one Catalog row per page"), update the `source_refs` example from `[{ "id": "<pageId>", "version": "<version>" }]` to `[{ "id": "<pageId>", "fetched_at": "<ISO 8601 timestamp at time of sync>" }]`.
- Remove the instruction to collect `version` from the CQL result (Step 1) — the Confluence MCP connector does not expose it, as verified in this session.
- Add a note that if a store does expose a real version, it can be included as `version` alongside `fetched_at`.

**Test scenarios:**
- Test expectation: none — documentation change; behavioral coverage lives in U3/U4.

**Verification:**
- SKILL.md instructs the skill to omit `version` or leave it null, and to populate `fetched_at` with the current timestamp.

---

## System-Wide Impact

- **Interaction graph:** `confirm_source` and `read_confirmations` MCP tools both pass through `ShapeResolver.resolve()`. Relaxing the version check affects both paths identically.
- **Error propagation:** A citation with `version=""` that previously returned `status: rejected` will now return `status: recorded` or `status: duplicate`. Callers expecting rejection for empty-version citations will see different behavior — but no current caller relies on that rejection (all were passing `"1"` to avoid it).
- **State lifecycle risks:** Existing rows in `confirmations` all have explicit `version` values. The `NOT NULL DEFAULT ''` change does not touch them. New rows written with `version=""` participate correctly in the unique constraint.
- **API surface parity:** The `Citation` Pydantic model is the shared type for both `confirm_source` and `read_confirmations`. Making `version` optional affects both tools symmetrically.
- **Unchanged invariants:** The unique constraint key `(confirmed_by, store_kind, location, locator, version)` is unchanged. Dedup semantics for non-empty `version` values are identical to today.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Serialization break: `list[SourceRef]` passed to `Json()` as Pydantic objects | Serialize each entry via `.model_dump(mode="json")` before `Json()` wrapping. Covered by U3 integration test. |
| Legacy `source_refs` rows (no `fetched_at`) fail to deserialize after `SourceRef` model is introduced | `fetched_at: Optional[str] = None` — absent key is tolerated; `model_dump(mode="json")` emits explicit `null`, not absent key. |
| `ShapeResolver` change silently allows malformed citations | `store_kind` (must be known) and `location` (must be non-empty) gates remain. U2 test scenarios cover the edge cases. |
| `init.sql` `CREATE TABLE IF NOT EXISTS` does not alter existing deployed DBs | Add idempotent `ALTER TABLE confirmations ALTER COLUMN version SET DEFAULT ''` in U1 (see approach). |
| SKILL.md still instructs skills to pass `version: "1"`, so `fetched_at` is never populated | U6 updates SKILL.md. Without this, R4 passes in tests but fails in practice. |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-24-04-decouple-version-fields-from-mcp-requirements.md](docs/brainstorms/2026-06-24-04-decouple-version-fields-from-mcp-requirements.md)
- Schema: `lik-mcp/db/init.sql`
- Citations model: `lik-mcp/src/lik_mcp/citations.py`
- Confirmations logic: `lik-mcp/src/lik_mcp/confirmations.py`
- Catalog logic: `lik-mcp/src/lik_mcp/catalog.py`
- Confirmation tests: `lik-mcp/tests/test_confirmations.py`
- Catalog tests: `lik-mcp/tests/test_catalog.py`
