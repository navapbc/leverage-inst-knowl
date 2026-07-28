---
date: 2026-07-27
topic: catalog-refresh-due-ttl
kind: spike-results
gates: R11 (source_modified_date hint)
origin: docs/brainstorms/2026-07-27-02-catalog-refresh-due-ttl-requirements.md
---

# `lastModified` spike results — pre-implementation gate for R11

Ran the appendix procedure against the live Atlassian/Confluence connector (`navasage.atlassian.net`),
CQL `label = "project-index" AND type = page`, 111 pages returned. Response integrity guard applied
(each returned `id` asserted equal to the requested one).

## Step 1 — Format census: **PASS**

Across all 111 project-index pages, only **two format families** appear:

| Shape | Example | Count | Family |
|---|---|---|---|
| `about N hours ago` | `about 14 hours ago`, `about 9 hours ago` | 45 | relative |
| `Mon DD, YYYY` | `Jun 22, 2026`, `Jul 16, 2026` | 66 | absolute |

- The set is small and enumerable — a parser can cover it. **Pass.**
- Confluence renders **relative** for recent edits (within ~a day) and **absolute** (`Mon DD, YYYY`,
  no time-of-day) once older. Consistent with the two sample formats `limitations.md` recorded
  (`about 5 hours ago`, `Jun 18, 2026`).
- Forms the doc anticipated but **not present** in this census: `yesterday`, `last week`, `about a
  minute/N minutes ago`, `N days ago`. A robust parser should treat any unrecognized shape as the
  **always-process fallback** (R11), not guess.
- Note: 44 pages share `about 14 hours ago` — a batch touch (bulk author/sync op), not 44 independent
  edits. Harmless, but explains the clustering.

## Step 1b — No native timestamp (load-bearing corroboration): **CONFIRMED**

`getConfluencePage` (id 2954264654) returned `lastModified: "Jun 22, 2026"` and **no** `version.when`,
`createdAt`, or any ISO timestamp field. This confirms `limitations.md`: the connector exposes no stable
native change signal, only the human-readable string. The hash-based `source_state` must remain the drift
source of truth; the string is only ever a cheap pre-filter hint.

## Step 2 — Timezone & midnight behavior: **PARTIAL / low-risk**

- The connector exposes no absolute timestamp to anchor a timezone against, and the absolute form is
  **date-only** (no time-of-day), so the tz cannot be pinned precisely from read-only single-shot access.
- **Why this is low-risk for this feature:** the absolute-form dates are old (Jun 22, Jul 16); comparing a
  stored old date against the same old date never flips regardless of tz. The tz/midnight risk only bites
  for **relative-form pages modified today/yesterday near a midnight boundary** — and there, **over-flagging
  is safe** (an extra re-hash), only under-flagging is harmful.
- **Recommendation:** normalize to a **single fixed timezone** (UTC is a safe default; at worst it
  over-flags near midnight). Do not attempt sub-day precision. This matches R2's day-granular intent.

## Step 3a — Body-edit tracking: **PASS (via CQL) — with a critical caveat**

Ran live (2026-07-27). Test page: **"Skill: Query Project Index"** (id `3231121417`, personal space),
baseline `lastModified = "Jul 06, 2026"`. A human made a trivial body edit ("Answer questions" →
"Answer user's questions") and published. Then the **same field was read two ways**:

| Read path | `lastModified` after the body edit | Fresh body reflected? |
|---|---|---|
| `getConfluencePage` (pageId) | `Jul 06, 2026` — **did NOT advance** | Yes (body text was updated) |
| `searchConfluenceUsingCql` (`id = …`) | **`less than a minute ago`** — advanced | Yes |

**Findings:**
1. **The CQL path tracks body edits — PASS.** R11 mandates the hint be derived *only from the CQL result*,
   and that path advanced correctly on a real body edit. The hint tracks what we hash. Gate cleared.
2. **`getConfluencePage.lastModified` is stale/cached and MUST NOT be used for the hint.** It returned a
   21-day-old value even though its own body payload reflected the just-published edit — so the two
   endpoints populate `lastModified` from different sources. This hardens R11 into a constraint: derive
   `source_modified_date` **exclusively from the CQL search result**, never from a per-page
   `getConfluencePage` read. (This also reinforces R11's "never from a new per-page fetch" rule — for a
   second reason beyond cost: the per-page field is wrong.)
3. **New format string observed:** `less than a minute ago`. Add to the Step-1 parser set.

## Step 3b — Child-only edit (parent `lastModified` movement): **NOT RUN (optional)**

Informational only — its outcome can at worst cause harmless over-flagging (extra fetches), never a silent
miss, so it cannot disqualify the hint. Deferred; can be run later if we want to tune over-flag behavior.

## Gate decision: **GREEN — build the hint**

- Steps 1 / 1b / 2: green (small enumerable format set, no native timestamp so hash stays source of truth,
  day-granular fixed-tz normalization with always-process fallback).
- Step 3a: **PASS** — the CQL `lastModified` tracks main-body edits.
- **Hard constraint added:** the hint comes **only** from the CQL search result's `lastModified`; the
  per-page `getConfluencePage` `lastModified` is unreliable and must never feed the hint.
- Updated parser format set: `less than a minute ago`, `about N hours ago`, `Mon DD, YYYY`, plus
  always-process fallback for any unrecognized shape (`yesterday`, `last week`, etc.).
- Step 3b left optional (over-flag tuning only).
