---
date: 2026-07-27
topic: catalog-refresh-due-ttl
---

# Catalog `refresh_due_at`: TTL-driven, trust-tiered incremental sync

## Summary

Add one Catalog column recording when a row is next **due for re-derivation**, and split the
`sync-catalog-from-project-indexes` skill into two modes: a fast **routine** run that re-checks only the
rows that are due (expired TTL) plus not-yet-catalogued and recently-changed pages, and an explicit
**full sweep** that re-hashes every page for periodic completeness. The TTL is **trust-tiered**: rows the
skill is more confident are stable get a longer interval; unverified or recently-drifted rows get a
shorter one. Routine runs get faster because still-fresh rows are skipped — an accepted trade, since the
full sweep and the bounded TTL both cap how long an unnoticed edit can persist.

To decide *which in-TTL pages to also re-check* without an expensive fetch, the sync also captures the
Confluence `lastModified` value — which the connector exposes only as a day-granular, best-effort signal
(see the Change-signal constraint below) — into a second column, `source_modified_date`, used as a cheap
pre-filter hint. The body hash stays the source of truth for actual drift.

Working column names: `refresh_due_at` and `source_modified_date` (naming is the planner's to finalize —
see Open Questions). All DB columns are snake_case; the Confluence field `lastModified` (camelCase, external)
maps to the snake_case `source_modified_date` column.

---

## Problem Frame

`sync-catalog-from-project-indexes` today re-fetches and re-hashes **every** project-index page on every
run: for each page it fetches the body (to compute the `source_state` hash), then fetches and interprets
the page's Update History child. The cost is entirely in these per-page fetches, and it scales linearly
with the number of pages — the skill is documented as "an expensive crawl — run on demand only."

Because it re-hashes everything every run, it catches every edit every run — but it has no way to spend
less effort on pages that almost certainly haven't changed. As the project-index directory grows, every
sync pays full cost even when only a handful of pages actually moved.

This addresses the "Catalog table maintenance/management" TODO in `lik-mcp/README.md` (age out / prioritize
rows relative to others of the same type), reframed from *aging out* toward *prioritizing which rows to
re-derive first and how often*.

### The core trade-off (explicit)

The "faster sync" benefit is **only** real if the routine run *skips* the per-page fetches for rows whose
TTL hasn't expired. Skipping means an edit to a page the skill considers still-fresh is **not noticed until
that row's TTL lapses or the next full sweep runs**. This is an accepted, bounded trade — not a defect —
and both the trust-tiered TTL (shorter intervals where change is likelier) and the full-sweep mode exist to
bound it. A design that merely *reordered* work without skipping would preserve full drift detection but
deliver **zero** runtime saving; that is explicitly rejected.

### The change-signal constraint (verified)

`limitations.md` records a **live-verified** finding: this Confluence connector exposes no stable native
change signal — no version number, and `lastModified` comes back only as a *human-readable relative string*
(`"about 5 hours ago"`, `"Jun 18, 2026"`) in an undocumented, localizable format and unspecified timezone.
Parsed finer than day granularity it jitters (false-positives every read); truncated to a **calendar date**
it is mostly stable. That doc's "Option B" evaluated using this as the `source_state` *marker* and **rejected
it** in favor of the content hash (Option A), because at day granularity it **under-flags intra-day edits**.

This feature uses `lastModified` for a *narrower, safer* purpose than a marker: a **cheap pre-filter hint**
that decides which in-TTL pages are worth re-hashing on a routine run. The body hash (Option A) remains the
drift source of truth. The day-granular under-flag is therefore **bounded** here — a missed same-day edit is
caught at the next TTL lapse or full sweep — rather than silently permanent as it would be for a marker.

The costs from Option B still apply and are accepted as carrying cost: a fixed-timezone normalization, a
parser for the connector's known relative-string formats, and a **content-hash fallback when the string
doesn't parse**. `limitations.md` notes only two sample formats have been observed, so a small spike to
characterize the format/tz space is a prerequisite (see Open Questions). If this proves too fragile, the
clean fallback is to drop the "recently changed" bucket and let routine mode cover only expired-TTL and
not-yet-catalogued pages.

---

## Requirements

**The columns** (both snake_case, matching the existing schema)
- R1. Add a nullable timestamp column meaning "this row is due for re-derivation after this time" (working
  name `refresh_due_at`). It is a *future* target the skill sets when it registers/updates a row — distinct
  from the existing `last_computed_at` (past: when last derived) and `freshness`
  (`current`/`stale`/`obsolete`).
- R2. Add a nullable **date** column holding the source's own last-modified day (working name
  `source_modified_date`), derived from the Confluence `lastModified` value. Day granularity is deliberate:
  finer resolution jitters and false-positives every read (per the change-signal constraint / `limitations.md`).
  The camelCase external field `lastModified` maps to this snake_case column.
- R3. Both columns are generic to any Catalog row and registrar; nothing about them is Confluence- or
  index-specific. Only the sync skill's *use* of them (below) is scoped to project-index rows for now.
- R4. The schema change is applied non-destructively (`ALTER TABLE ... ADD COLUMN`, nullable / with a
  default), never a drop-and-recreate. A row with no `refresh_due_at` is treated as always-due; a row with no
  `source_modified_date` is treated as "modification day unknown → do not skip on the hint." Applying the
  change to the production `lik-prod-db` is a separate, required migration step from merging the code.
- R5. `register_catalog_entry` accepts and persists both values; `list_catalog_entries` returns them (it
  already `SELECT *`s, so they are available to the skill once the columns exist).

**TTL policy — trust-tiered**
- R6. When the skill registers or updates a row, it sets `refresh_due_at = <run time> + interval`, where the
  interval depends on the row's trust/stability signal:
  - longer for rows that are `human-verified` and `current`,
  - medium for `unverified` rows,
  - shorter for rows that were `stale` / drifted on the run that produced them.
- R7. The concrete interval values are the planner's to choose (see Open Questions). The requirement is the
  *ordering* (verified-current ≥ unverified ≥ stale/drifted), not the numbers.

**Sync skill — two modes**
- R8. **Routine run (default).** The skill:
  1. reads existing index rows via `list_catalog_entries("index")` to learn each page's `refresh_due_at`
     and stored `source_modified_date`,
  2. fetches the project-index page list from Confluence (the cheap CQL step), which carries each page's
     relative `lastModified` string,
  3. does the expensive per-page work (body hash + Update History) **only** for pages that are: (a) past
     their `refresh_due_at`, (b) not yet catalogued (no matching row), or (c) whose freshly-parsed
     `source_modified_date` is **later than** the stored one (a likely edit since last sync),
  4. skips the per-page work for rows still within their TTL whose modification day has not advanced,
  5. registers/updates the rows it processed, stamping a fresh `refresh_due_at` (R6) and the parsed
     `source_modified_date`.
- R9. Processing order within a routine run is **most-urgent first**: expired-TTL rows, then new pages, then
  pages whose modification day advanced — so a run that is interrupted or capped does the highest-value work
  first.
- R10. **Full sweep (explicit).** An explicit mode re-checks **every** page as the skill does today, ignoring
  `refresh_due_at` and the `source_modified_date` hint, and re-stamps both columns. This is the completeness
  backstop; it is opt-in, not the default.
- R11. The `source_modified_date` hint (R8c) must be derived only from the `lastModified` string already in
  the cheap CQL result — never from a new per-page fetch. Parsing is **day-granular**, normalized to a fixed
  timezone, over the connector's known relative-string formats, with a **fallback to always-process** when the
  string does not parse (never skip on an unparseable hint). Under-flagged same-day edits are acceptable
  because R6's TTL and R10's full sweep bound how long they persist.
- R12. All existing skill guarantees are preserved unchanged for every page the skill *does* process:
  the Response integrity guard, the `source_state` hashing recipe (shared with `query-project-index`), the
  self-disclaiming "DO NOT USE" hold-back flow, and the Update-History verification logic.

---

## Acceptance Examples

- **Fast routine run.** Directory has 200 index pages; 190 have a future `refresh_due_at` and are unchanged,
  10 are past-due. A routine run does per-page fetches for ~10 pages (plus any brand-new or recently-modified
  ones), not 200, and finishes markedly faster than today's full crawl.
- **New page appears.** A page tagged `project-index` that has no Catalog row is always processed on the next
  routine run, regardless of TTL, and gets a row with a freshly-set `refresh_due_at`.
- **Modification day advances → re-checked despite TTL.** A page is edited yesterday; its
  `source_modified_date` parses to a later day than the stored one. The routine run re-hashes it even though
  its TTL has not lapsed.
- **Same-day edit is under-flagged but bounded.** A verified page is edited one hour after its last sync (same
  calendar day). The routine run skips it (TTL not expired, modification day unchanged); the drift is surfaced
  when its TTL lapses or a full sweep runs — never silently permanent.
- **Unparseable `lastModified` → processed, not skipped.** A page whose `lastModified` string doesn't parse is
  processed (fallback per R11), never silently skipped on a bad hint.
- **Trust tiering bites.** Two pages sync in the same run: one `human-verified`/`current`, one `stale`. The
  stale one comes due for re-check sooner than the verified one.
- **Full sweep ignores hints.** An explicit full sweep re-hashes all 200 pages ignoring both `refresh_due_at`
  and `source_modified_date`, and re-stamps both, matching today's completeness.
- **Migration safety.** Adding the columns to a populated DB (including prod) does not lose or rewrite existing
  rows; pre-existing rows with no `refresh_due_at` are treated as due, and with no `source_modified_date` are
  never skipped on the hint, until their first re-derivation stamps both.

---

## Dependencies / Assumptions

- **Assumption:** the routine run can read back existing rows via `list_catalog_entries("index")` and match
  them to Confluence pages by their key (`subject` = page title / `locator` = page ID) to decide what is
  due vs. new. [Verified: `list_catalog_entries(entry_type)` exists and returns all columns.]
- **Change signal is day-granular and format-fragile [verified — `limitations.md`].** Confluence's
  `lastModified` is a relative string in an undocumented, localizable format and unspecified timezone; usable
  only truncated to a calendar date. This bounds `source_modified_date` to day precision (under-flags same-day
  edits) and requires a fixed-tz normalization, a format parser, and an always-process fallback. Only two
  sample formats have been observed — a **small spike to characterize the format/tz space is a prerequisite**
  before committing to R11.
- **Must-verify before build:** confirm the CQL result's `lastModified` reflects edits to the **main
  project-index page body that gets hashed**, not merely child-page or metadata churn — otherwise the hint
  mis-selects. (Direction unknown; check against the live connector.)
- **Production impact:** `lik-prod-db` holds real data; the `ADD COLUMN`s must be applied there as a separate
  migration after merge. `db/init.sql` uses `CREATE TABLE IF NOT EXISTS`, so re-running it will **not** add
  the columns to the existing prod table.
- Both columns and the skill logic must stay store-agnostic in spirit; only this skill's scheduling of index
  rows (and the Confluence-specific `lastModified` parsing) is Confluence-facing.

---

## Scope Boundaries

**In scope**
- Two new Catalog columns: `refresh_due_at` (next re-derivation due) and `source_modified_date` (day-granular
  source last-modified hint).
- Two-mode (routine + full sweep) behavior for `sync-catalog-from-project-indexes`.
- Trust-tiered TTL setting at registration time.

**Out of scope / deferred**
- **Aging out or deleting obsolete rows** — the *other* half of the README Catalog TODO. Related but separate;
  this feature prioritizes *re-derivation*, not retirement.
- The **confirmation-table** maintenance TODOs (rate-limiting, minimum-distinct-confirmers, backpropagation,
  negative-confirmation correction) — untouched.
- Rolling this pattern into **other** sync-catalog skills. The column is generic and reusable, but only
  `sync-catalog-from-project-indexes` adopts the two-mode behavior in this pass.
- Any change to how the **Query skill** consumes rows — ranking, freshness display, confirmation weighting.

---

## Open Questions (planner's to finalize)

- **Column names.** `refresh_due_at` vs. `next_refresh_at` vs. `revalidate_after` vs. the requested
  `ttl_date` (`ttl_date` risks reading as "delete after"; recommend a "next-refresh"-style name); and
  `source_modified_date` vs. `source_last_modified` / `last_modified_date`.
- **Interval values** for each trust tier (R6/R7), and whether they are constants, config, or per-run inputs.
- **Whether the routine run also enforces a hard count cap** (process at most K pages/run) on top of the
  TTL-driven subset, or whether the due-set is the only bound. (User deferred this to planning.)
- **How the full sweep is triggered** — a skill argument, a distinct invocation phrase, or a periodic
  schedule — and whether it should run automatically on some cadence as the completeness backstop.
- **`lastModified` parsing spike (R11):** characterize the connector's relative-string format set, pin the
  timezone, and confirm the field tracks main-page-body edits (see Assumptions) before committing to the hint.
  **Ready-to-run procedure in the appendix below** — run it in a connector-enabled session (Claude Desktop
  with the Atlassian MCP) as a pre-implementation gate.

---

## Appendix — `lastModified` spike procedure (pre-implementation gate for R11)

Run this in a session where the Atlassian/Confluence MCP connector is available (e.g. Claude Desktop). It is
**read-only against Confluence** except where a human makes one test edit in the Confluence UI (step 3); the
connector itself never writes. Apply the **Response integrity guard** from `limitations.md` throughout —
serialize `getConfluencePage` calls and assert each returned `id` equals the requested `pageId`, since
concurrent reads can silently return the wrong page.

**Goal:** decide whether `source_modified_date` (R2/R11) is safe to build, and pin the parser/tz. If any
check fails, the documented fallback applies — drop the "recently changed" bucket and let routine mode cover
expired-TTL + not-yet-catalogued pages only.

**Step 1 — Format census.** Run `searchConfluenceUsingCql` with
`cql: 'label = "project-index" AND type = page'`, `cloudId: navasage.atlassian.net`, `limit: 250`. Record
every **distinct** shape of the `lastModified` string across all results (e.g. `"about 5 hours ago"`,
`"yesterday"`, `"Jun 18, 2026"`, `"last week"`). This is the parser's required input set.
- *Pass:* the shapes fall into a small, enumerable set a parser can cover.
- *Fail:* open-ended / free-form values that can't be reliably day-parsed → hint is unsafe.

**Step 2 — Timezone & midnight behavior.** Pick one page and read its `lastModified` (via the same CQL, or
`getConfluencePage`) twice: once well before and once just after a local midnight (or compare a
relative-form page against its own absolute `"Mon DD, YYYY"` form). Determine (a) which timezone the
relative string is anchored to, and (b) whether the truncated calendar date flips across the boundary.
- *Record:* the tz to pin in normalization; whether near-midnight reads can flip the date (over-flagging is
  safe noise, under-flagging is not).

**Step 3 — Body-edit tracking (load-bearing).** This is the must-verify from Assumptions.
1. Choose a test project-index page; record its current `lastModified`.
2. A human makes a **trivial edit to the main page body** in the Confluence UI (the connector is read-only,
   so this edit is manual). Re-run the CQL and confirm `lastModified` advances to a recent value.
3. Separately, touch **only the page's `Update History` child** (not the parent body). Re-run the CQL for
   the **parent** and observe whether the parent's `lastModified` moves.
- *Pass:* parent `lastModified` advances on a parent-body edit (step 2) — the hint tracks what we hash.
- *Note either way:* whether child-only edits (step 3) move the parent. If they do, the hint over-flags
  (harmless extra fetches). The disqualifying outcome is step 2 **not** advancing on a real body edit — that
  is a silent miss and makes the hint unsafe.

**Deliverable:** a short note recording (a) the format set, (b) the pinned tz + midnight behavior, and (c)
the step-3 result — pass/fail for building `source_modified_date`, feeding the parser spec in R11 or
triggering the fallback.
