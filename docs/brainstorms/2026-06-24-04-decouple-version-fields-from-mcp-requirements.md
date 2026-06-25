# Decouple version fields from MCP capabilities

**Date:** 2026-06-24
**Status:** Draft

## Problem

Two fields in the Discovery Layer store embed a version identifier that the Confluence MCP connector cannot provide:

- `confirmations.version` — intended to scope a confirmation to an exact content-state of the cited source. Currently hardcoded to `"1"` by skills because the Confluence MCP tools (`getConfluencePage`, `searchConfluenceUsingCql`) do not return a page version number.
- `catalog.source_refs[].version` — intended to detect content drift (the output was computed from source `v5` but the source is now `v7`). Same gap: hardcoded to `"1"` at sync time.

As long as these fields are required and MCP cannot supply them, the architecture's staleness and trust-weighing machinery cannot function as designed.

## Goals

1. Allow skills to record confirmations without providing a meaningful version number.
2. Allow sync skills to record `source_refs` without a real version, while still capturing *when* the source was fetched.
3. Enable Query skills to weigh confirmations by recency using `confirmed_at` / `created_at` rather than exact version match.
4. Preserve the `version` column in both places so that stores which do expose real version numbers (or future MCP upgrades) can use it without a second migration.

## Non-goals

- Implementing real version-based staleness detection (blocked on MCP capability; deferred).
- Changes to store kinds other than Confluence.
- Changes to the `last_validated_at` pipeline or the owner-agnostic reconciliation pass.

## Proposed changes

### 1. `confirmations.version` — make optional

**Current:** `version text NOT NULL`, required in `Citation`, checked non-empty by `ShapeResolver`.

**Change:** Allow `version` to be empty. Default to `""` (consistent with `locator`). The unique constraint `(confirmed_by, store_kind, location, locator, version)` becomes `(confirmed_by, store_kind, location, locator)` in practice when version is always `""` for Confluence sources — one confirmation per user per source, which is the correct dedup behavior given we can't distinguish content states.

`confirmations.created_at` already exists and is already returned by `read_confirmations`. Query skills use it for recency weighing with no further schema change.

**Migration surface:**
- `db/init.sql`: drop `NOT NULL` on `version`, default `''`.
- `citations.py`: make `version` optional (`str = ""`), relax `ShapeResolver` check to allow empty.
- `lik-sync-catalog-from-project-indexes` skill: stop passing `version: "1"` (or omit the field).

### 2. `catalog.source_refs[].version` — use fetch timestamp as proxy

**Current:** `source_refs` is `jsonb[]` with shape `{id, version}`. Version is hardcoded `"1"`.

**Change:** Store a fetch timestamp (`fetched_at`) alongside `version` in each `source_refs` entry. When a sync skill cannot obtain a real version, it omits `version` (or sets `null`) and records `fetched_at` as an ISO 8601 timestamp at sync time. Drift detection logic compares `fetched_at` against `catalog.last_validated_at` to flag rows that have not been re-validated recently — a weaker but available signal.

**`source_refs` entry shape after change:**

```json
{ "id": "<page-id>", "version": null, "fetched_at": "2026-06-24T19:48:40Z" }
```

**Migration surface:**
- `db/init.sql`: no column-type change needed (already `jsonb`).
- `lik-sync-catalog-from-project-indexes` skill: write `fetched_at` at sync time, omit `version` or set `null`.
- Any reconciliation skill: use `fetched_at` to flag rows not re-validated within a threshold.

## Success criteria

- A skill can call `confirm_source` without providing a version string and receive `status: recorded`.
- `read_confirmations` returns rows with `created_at`, allowing a consumer to rank by recency.
- A sync skill can register a `source_refs` entry without a version number and the row is accepted.
- `source_refs[].fetched_at` is populated at sync time and visible to reconciliation logic.
- No regression in dedup behavior: the same user cannot double-confirm the same Confluence source in a single run.

## Assumptions

- The Confluence MCP connector will not expose version numbers in the near term. If it does, the `version` column is already present and skills can populate it without another migration.
- `""` (empty string) is a safe sentinel for the unique constraint (consistent with the existing `locator` pattern).
- Recency-based weighing (`created_at`) is sufficient for the current Query skill use case; exact version matching is a future enhancement.

## Deferred

- Real version-based drift detection (requires MCP to expose page version).
- Per-store version resolution strategy for GDocs, GSheets, BigQuery.
