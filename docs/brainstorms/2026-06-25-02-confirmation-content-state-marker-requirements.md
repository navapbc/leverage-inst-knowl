# Confirmation content-state marker (replacing version)

**Date:** 2026-06-25
**Status:** Draft
**Supersedes:** [2026-06-24-04-decouple-version-fields-from-mcp-requirements.md](2026-06-24-04-decouple-version-fields-from-mcp-requirements.md) — that doc made `version` optional and used `fetched_at` as a weak proxy, explicitly deferring real "edited since" detection. This doc resolves that deferral and removes `fetched_at`.

## Problem

The Confluence MCP connector exposes no page version *number* ([limitations.md](../../limitations.md)), so `confirmations.version` and `catalog.source_refs[].version` were hardcoded, then made optional. Two consequences:

1. **Confirmations cannot target a specific content state.** A confirmation records a human's "this source is correct." Confluence pages are edited *in place* (same `pageId`, same `location`, mutated body) — they are not recreated as new records. With no per-state marker, a confirmation silently re-applies that trust to content the human never saw. This is the "confirmed, but edited since" failure the architecture promises to catch ([v0.4/05-architecture.md §2](../../v0.4/05-architecture.md)) — a trust/correctness bug, not cosmetic.
2. **`fetched_at` is the wrong proxy.** It records when *DL last fetched*, not when the *source changed*. The daily sync bumps it every run regardless of change, so any "edited since" check built on it false-positives after one day. It was added but is unused on confirmations for exactly this reason.

Confluence is the *motivating* case, but the gap is general: every Data Source the Catalog points at (`gdoc`, `gsheet`, `confluence`, `postgres`, `bigquery`) exposes a different — or no — version identifier through its MCP connector. A design pinned to Confluence's quirks would break on the next source. The fix must be store-agnostic.

## Key reframe

Drift detection, confirmation targeting, and "edited since" never needed a *version number* or version *history*. They need one yes/no: **is this the same content state the marker was taken from?** That requires an opaque content-state token compared by **equality** — not an ordered version. Because the comparison is pure equality, *any* per-store signal works as the token — a version id, a modified timestamp, an etag, or a content hash — so the model generalizes across every DS without per-store comparison logic.

## Goals

1. A confirmation records *which content state* the human vouched for, so "confirmed, but edited since" works on in-place-edited Confluence pages.
2. No version-number dependency on the MCP, and no version-history tracking.
3. **Store-agnostic by construction.** The marker, the comparison, and the schema are identical across all DSs; only *how a DL-creation skill derives the token* varies per store. No store-specific column or comparison path.
4. Keep the architecture simple: one marker column, one comparison rule (equality), one branch only at populate time.
5. Remove the dead `fetched_at` proxy.
6. Update the architecture and strategy docs so the version/etag-specific language matches the generalized marker model.

## Non-goals

- Version history / ordered versions per source.
- Content-diff or semantic-change classification (any edit counts as "edited").
- Per-store reachability resolver (already deferred behind `CitationResolver`).
- Changes to the `last_validated_at` pipeline or owner-agnostic reconciliation pass.

## Decisions

### 1. The marker is an opaque content-state token, compared by equality

A single token per `(store, location, locator)` representing the current content state. "Edited since" = `stored token ≠ live token`. No ordering, so the same comparison works for any token source.

**How DL populates it (per-store — the only branch).** Each DL-creation skill knows its source and picks the cheapest signal its connector actually returns. Preference order per store: native change signal if present, else content hash of the fetched body (universal, zero store-metadata dependency; DL already fetches the body, so hashing is near-free).

| `store_kind` | Preferred native token (if the connector returns it) | Universal fallback |
|---|---|---|
| `confluence` | *none via the MCP connector* — verified live (see Assumptions); raw REST has `version.when` but the connector drops it | content hash (the marker actually used) |
| `gdoc` | head revision id or `modifiedTime` | content hash |
| `gsheet` | revision id or `modifiedTime` | content hash |
| `postgres` | row `updated_at` / `xmin` | content hash |
| `bigquery` | table `last_modified_time` / snapshot id | content hash |

Two rules keep this honest:
- **Verify the field is in the response *body*, not just queryable**, before relying on it (the Confluence lesson — see Assumptions). Until verified for a connector, that store uses the hash fallback.
- The token is **opaque**: nothing downstream parses or orders it. A skill may switch a store from hash to native (or back) without any schema or consumer change.

### 2. The marker is NOT part of the confirmation's identity

This is the fix for "a hash complicates the target." Today the dedup key is `(confirmed_by, store_kind, location, locator, version)` — putting the marker in the key means every content change spawns a new confirmation slot.

**Change the dedup key to `(confirmed_by, store_kind, location, locator)`** — one confirmation per user per source. The marker becomes a non-key state column. The target is always `(store, location, locator)`, independent of marker type.

### 3. Re-confirming after an edit updates the stored marker

`confirm_source` upserts: a new confirmation by a user who already confirmed that source updates the row's marker to the current state (they've re-vouched for the new content). One row per user per source, always reflecting the last state they confirmed.

### 4. Schema changes

- `confirmations`: rename `version` → `source_state` (text, opaque token). Drop it from the unique constraint; new key `(confirmed_by, store_kind, location, locator)`. Set/update `source_state` on confirm.
- `catalog.source_refs[]`: entry shape `{ id, source_state }`. **Remove `fetched_at`** — "when DL last looked" is already `catalog.updated_at` (bumped by the daily upsert).
- "Edited since" is computed at confirmation read-time by comparing the stored `source_state` against the live source's current token.

### 5. Documentation updates

The version/etag assumption is woven through the v0.4 docs and must move to the generalized marker model. (`limitations.md` already corrected.)

- **[v0.4/05-architecture.md](../../v0.4/05-architecture.md):**
  - §2 *Content-freshness* "Version drift" bullet (`computed from v5 but source is now v7; comparing the version/etag in source_refs`) → restate as a **content-state marker** comparison; drop the version-number framing.
  - §2 *"Confirmed, but edited since"* bullet → tie to the stored marker vs live marker comparison.
  - §3 *Catalog schema* `source_refs` row (`IDs/URLs + version/etag`) → entry carries a **content-state token** (native or hash) per source; remove `fetched_at`.
  - §3 *Detection* paragraph ("comparing the stored version/etag against the live source") → marker equality.
- **[v0.4/04-strategy.md](../../v0.4/04-strategy.md):**
  - §1.3 citation shape `store_kind + location + locator + version` → the `version` slot is the opaque content-state token (note it may be a hash or native id, not necessarily a version number).
  - Level 3 ("each signal records the **version of the confirmed data**") → records the **content-state marker** of the confirmed data; the "title + last-updated" confirm preview is unchanged.
- **[v0.4/07-storage.md](../../v0.4/07-storage.md):** check the confirmations-store description for version-specific wording; update if present.
- Keep "version number unavailable" accurate where it's literally about a version *number* — only generalize the change-detection mechanism.

## Success criteria

- A user who confirmed a Confluence page, which is then edited in place, sees that confirmation reported as "edited since" (stored `source_state` ≠ live).
- Re-confirming the edited page clears the "edited since" flag for that user (marker updated to current).
- A user cannot double-confirm the same source in one state; dedup is one row per user per `(store, location, locator)`.
- No `fetched_at` remains in `source_refs`; reconciliation/recency uses `catalog.updated_at`.
- A sync skill registers `source_refs` with a `source_state` token (a content hash for Confluence; a native signal for stores whose connector exposes one) and no version number.
- The same confirm / "edited since" flow works unchanged for a non-Confluence source (e.g. a `gdoc` using its revision id, or any store falling back to a content hash) — no store-specific code path.
- The architecture and strategy docs describe the marker model, not version/etag, with no remaining version-number framing for change detection.

## Assumptions

- **The MCP connector exposes no usable native marker for Confluence — content hash it is.** [Certain] Verified live against the `01fd8586-…` connector: `getConfluencePage` and `searchConfluenceUsingCql` return `lastModified` only as a relative display string (e.g. `"about 5 hours ago"`) and ignore `expand=version` / `expand=history.lastUpdated`, so no stable timestamp comes through. The raw Confluence *REST* API does return `version.when` / `version.createdAt`, but this connector does not pass them through — an earlier check confirmed the API layer, not the connector the skills actually call, which is the layer that matters. Per the brainstorm's own fallback, Confluence uses a content hash of the page body, and the design is unchanged. See [limitations.md](../../limitations.md).
- Content hash is reproducible only if DL hashes a canonical field consistently (e.g. Confluence storage-format body or extracted text). The exact field is a planning decision.
- Any edit (including cosmetic) changes the body hash, so "edited since" over-flags rather than under-flags — acceptable conservatism for a trust signal.

## Open for planning

- Exact canonicalization for the content hash.
- Whether the live-token fetch for "edited since" happens in `read_confirmations` or in the Query skill that consumes it.
- Per-connector verification of which native token field is actually in the response body (the Decision 1 table lists *preferred* tokens; each needs the same probe Confluence got before a store leaves the hash fallback).
