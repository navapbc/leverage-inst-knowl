---
name: sync-catalog-from-project-indexes
description: Catalog the project-index pages from Confluence into the Discovery Layer Catalog (the lik-mcp service). Lists the Confluence pages tagged `project-index` and upserts one Catalog row per page via `register_catalog_entry`. Runs in two modes — a fast default "routine" sync that only re-checks pages due for re-derivation or not yet catalogued, and a "full sweep" that re-checks every page (trigger it when someone says "full sweep", "full resync", or "re-check everything"). Use whenever someone says "sync the project indexes", "refresh the project-index catalog", "catalog the project indexes", or asks to (re)build Catalog rows from the Project Index Directory. This is a Catalog-registration skill: the project-index pages are authored by a separate process; this skill only registers them as Catalog rows — it writes to the Catalog, never to Confluence.
---

# Sync Catalog from Project Indexes

Crawl the Confluence pages tagged `project-index` and register one **Catalog** row per page in the Discovery Layer's
Catalog store (fronted by the **lik-mcp** service). This is the Catalog-store counterpart of `discovery-catalog-sync`,
which writes the same pages into a Confluence table instead.

Re-running is safe: each row upserts on its key, so a second run updates in place rather than duplicating.

## Two modes: routine (default) and full sweep

The expensive part of a sync is the **per-page** work — fetching each page's body to hash it (Step 1) and reading its
Update History child (Step 2). The page **list** itself (the CQL in Step 1) is cheap. So the skill has two modes:

- **Routine (the default).** Do the per-page work only for pages that actually need it — pages that are **past due**
  for re-derivation, or **not yet in the Catalog**. Pages still within their refresh window are skipped this run. This
  makes a routine sync much faster than crawling every page, at the cost of not re-checking still-fresh pages until they
  come due. That trade is bounded: every row carries a `refresh_due_at` deadline (below), so nothing goes unchecked
  indefinitely.
- **Full sweep (explicit).** Re-check **every** page exactly as this skill always has, ignoring `refresh_due_at` and
  the change hint. Run this when the caller asks for a "full sweep" / "full resync" / "re-check everything", or
  periodically as a completeness backstop. A full sweep re-stamps every row's `refresh_due_at` and
  `source_modified_date`.

**Pick the mode first.** Unless the caller explicitly asked for a full sweep, run **routine**. Everything below is
written for routine mode; the "Full sweep" callouts note where it differs (it simply processes *all* pages instead of
the selected subset).

## Prerequisites

- **lik-mcp** connected

## Step 1 — Fetch the project-index page list (cheap)

`searchConfluenceUsingCql` with:
- cloudId: `navasage.atlassian.net`
- cql: `label = "project-index" AND type = page`
- limit: 250

This label is the canonical source of truth — it matches what the Project Index Directory renders via its Page
Properties Report macro.

Per result, collect:
- `title` → project name
- `webUrl` → page URL
- page **ID**
- `lastModified` → the page's relative/absolute last-modified string (used by the routine-mode change hint below)
- optionally `space.name`, `summary`, `author.displayName` for context

This CQL call is the cheap part — it returns the whole list without any per-page body fetch.

## Step 1b — Select which pages to process

**Full sweep:** skip the *selection* below — every page is processed regardless. (You still parse each page's
`lastModified` into `source_modified_date` when you register it in Step 3, per the change hint below; a full sweep just
doesn't use it to decide what to skip.) Go straight to the per-page work below for all pages.

**Routine mode:** first read the Catalog rows this skill already owns so you know each page's refresh deadline:

`list_catalog_entries` (lik-mcp) with `entry_type: "index"`. Match each Catalog row to a page from Step 1 by key —
the row's `subject` equals the page `title` and its `locator` equals the page **ID**. Each row carries a
`refresh_due_at` (may be null on rows written before this field existed).

Process a page when **any** of these holds; otherwise **skip** it this run:
- **Past due** — the page has a matching row and `now` is at or after its `refresh_due_at`. A **null**
  `refresh_due_at` counts as always due (so pre-existing rows are always processed until they get a deadline).
- **Not yet catalogued** — no matching row exists for the page (a new project index).
- **Changed since last sync** — the page's freshly-parsed modification day (from its `lastModified` string, per the
  change hint below) is **later than** the `source_modified_date` stored on its row. This catches edits before the
  row's `refresh_due_at` comes due.

Order the pages you will process **most-urgent-first**: past-due rows first, then not-yet-catalogued pages, then
changed-since-last-sync pages. A run that is interrupted or capped then does the highest-value work first.

### The change hint (`source_modified_date`)

A cheap way to notice a page probably changed without fetching its body. Derive it from the `lastModified` string that
**already rode the Step 1 CQL result** — this is a hard rule:

- **Source it ONLY from the CQL search result's `lastModified`.** Never read `lastModified` from a `getConfluencePage`
  response for this: that field is cached/stale (a live spike saw it return a 21-day-old value right after a real edit
  while the CQL field updated correctly). The body hash — not this hint — remains the source of truth for drift.
- **Parse to a calendar day, normalized to UTC.** Known formats: `less than a minute ago`, `about N hours ago`, and
  `Mon DD, YYYY` (date-only). The first two mean "today (UTC)"; the third is that date. Day granularity is
  deliberate — finer resolution jitters.
- **Any unrecognized shape → process the page** (the always-process fallback). Never skip a page on a `lastModified`
  string you couldn't parse (e.g. `yesterday`, `last week`, a localized or abbreviated form). Over-processing costs an
  extra fetch; under-processing would miss an edit.
- A row whose stored `source_modified_date` is **null** is never skipped on this hint (treat as "changed").

This hint under-flags a same-day edit (two edits on the same UTC day share a day marker), which is acceptable: the
row's `refresh_due_at` and the periodic full sweep still catch it — it is never a silent, permanent miss.

**This whole "changed since last sync" bucket is optional.** If Atlassian changes the `lastModified` format and the
parser becomes unreliable, drop this trigger (and the `source_modified_date` stamping in Step 3). Routine mode still
works on past-due + not-yet-catalogued alone; only the early-edit detection is lost.

## Per-page work (for each selected page)

Do the following for each page selected in Step 1b (routine) or for every page (full sweep).

**Compute the content-state marker** for each page from its body, per the recipe below — the **main** project-index
page, not its Update History child. The connector exposes no stable change signal (no version number; `lastModified` is
only a relative string like `"about 5 hours ago"`), so the
marker is a body hash. You may batch these fetches in parallel, but every response **must** pass the Response integrity
guard before you hash it.

While you have the body in hand, also **check it for a self-disclaiming warning** (see below) — the same body serves
both the hash and this check, so no extra fetch is needed.

## Self-disclaiming pages (content-warning exclusion)

Some project-index pages carry a body banner **explicitly instructing readers not to use the page** — "DO NOT USE",
"do not reference", or equivalent don't-use wording. This is a **content-level** signal in the page body and is
independent of the Update History table: a page can show an approved edit trail (Step 2) yet still carry a "DO NOT USE"
banner, in which case the mechanical `human-verified` result is misleading.

When a page's body carries such a banner, **do not register it in Step 3.** Instead set it aside as a **held-back**
page, recording its `title`, `webUrl`, and the disclaiming phrase you matched. These pages are surfaced to the user in
Step 3b, who decides whether any should be registered anyway.

Match **only** an explicit don't-use instruction. Weaker status wording — "UNVERIFIED", "under active review",
"not yet approved", "draft", "in progress" — is **not** grounds to hold back; register those normally (their
`verification` still comes from Step 2). When unsure whether wording rises to a don't-use instruction, **register the
page** rather than hold it back.

## Unattended (scheduled) runs

This skill is safe to run unattended (on a schedule, with no human present). It never blocks waiting for input:
held-back self-disclaiming pages are **recorded and reported** in the final summary (Step 3b), not paused on — a
scheduled run completes and leaves the held-back list for a human to review later, rather than waiting for a decision
that will never come. Likewise, if a routine write is not approved, **skip that page, record it, and continue** — do
not retry the same write in a loop or wait indefinitely. The goal is always a completed run with an accurate summary of
what was registered, held back, or skipped.

## Content-state marker recipe (shared with `query-project-index`)

`source_state` = the SHA-256 hex digest of the page's markdown body:
1. `getConfluencePage(pageId, contentFormat: "markdown")`, take the `body` **verbatim**.
2. Write it to a file (no added trailing newline, no normalization) and hash: `shasum -a 256 FILE | cut -d' ' -f1` (or
   `sha256sum FILE | cut -d' ' -f1` — same digest for the same bytes).

`query-project-index` computes `source_state` the **identical** way, so a stored and a live marker compare equal
when content is unchanged. Any change to this recipe must be mirrored in both skills, or "edited since" false-positives
on every page.

## Response integrity guard (required)

Run concurrently, `getConfluencePage` / `searchConfluenceUsingCql` can return the **wrong page** — a response silently
carries another request's body, with no error. A hash or
verification from a mismatched body looks valid but poisons the row's `source_state`. Parallel batching is allowed, but
**verify every response first**:
- `getConfluencePage`: assert the returned `id` equals the requested `pageId`. On mismatch, re-issue that call serially
  until it matches, or fail the row.
- `searchConfluenceUsingCql`: confirm each result belongs to the query you sent (e.g. the `ancestor`/space). On
  mismatch, re-run that query alone.

Hash a body or read an Update-History table **only** from a response that passed this check.

## Step 2 — Read each page's Update History

**2a — Find the child.** `searchConfluenceUsingCql` with:
- cloudId: `navasage.atlassian.net`
- cql: `ancestor = "<pageId>" AND title = "Update History" AND type = page`
- limit: 1

No result → `verification = "unverified"`; skip 2b.

**2b — Read the body.** `getConfluencePage` with the returned page ID and `contentFormat: "markdown"`, then apply the
**Response integrity guard**. The body holds a table of update-history entries; interpret it:
- `human-verified` — at least one row shows a deliberate review (a date, reviewer name, or explicit
  "reviewed"/"verified"/"updated" signal). From the **most recent such row** (last with a date), extract **"Approved
  By"** → `verified_by` and **"Date"** → `verified_at` (parse to ISO 8601 UTC).
- `unverified` — table empty, header-only, or no meaningful review signal (blank/placeholder cells). Leave
  `verified_by`/`verified_at` null.

Set `verification`, `verified_by`, `verified_at` accordingly. You may batch the CQL lookups in parallel; fetch each body
only after its CQL returns a hit; apply the **Response integrity guard** to every response.

## Step 3 — Register one Catalog row per page

Register a row for every page **except** those held back as self-disclaiming (see "Self-disclaiming pages" above); those
are handled in Step 3b.

`register_catalog_entry` (lik-mcp) with an `entry`:
- `entry_type`: `"index"`
- `subject`: the page `title`, verbatim  *(e.g. `"Atlas"`)*
- `location`: the page `webUrl`
- `store_kind`: `"confluence"`
- `locator`: the Confluence page ID
- `source_refs`: `[{ "id": "<pageId>", "source_state": "<body hash from the per-page work>" }]`  *(powers staleness
  checks; compared by equality to detect "edited since")*
- `verification`: from Step 2
- `verified_by` / `verified_at`: from the Update History table, else null
- `refresh_due_at`: the row's next re-derivation deadline — see the interval policy below
- `source_modified_date`: the page's parsed modification day (UTC), per the change hint in Step 1b. Omit (leave null)
  when the `lastModified` string didn't parse — the row then always processes next run rather than skipping on a bad
  hint. *(Omit this field entirely if the change-hint bucket has been dropped.)*
- `computed_by`: `"sync-catalog-from-project-indexes"`
- `row_provenance`: `"skill"`

Leave other fields at defaults (`provenance=ai-generated`, `freshness=current`, `sensitivity=cleared`, empty
`access_groups`). Each call returns `inserted` or `updated` — tally for the summary.

**`refresh_due_at` — trust-tiered interval (this skill's policy).** Set `refresh_due_at` to the current time plus an
interval chosen from the row's trust/stability on *this* run. More-trusted, stable rows are re-checked less often;
shakier ones sooner:

| Row state this run | Interval | `refresh_due_at` |
|---|---|---|
| `verification = human-verified` **and** `freshness = current` | 30 days | now + 30 days |
| `unverified` (and not stale/drifted) | 14 days | now + 14 days |
| `freshness = stale` or the row drifted on this run | 3 days | now + 3 days |

These numbers are **this skill's** to tune — only the ordering is fixed (verified-current ≥ unverified ≥
stale/drifted). Both modes stamp `refresh_due_at` on every row they process (a full sweep re-stamps all of them).

## Step 3b — Present held-back pages and ask

If any pages were held back as self-disclaiming, list them for the user and ask whether to register any anyway. Show,
per page, the `title`, the `webUrl`, and the disclaiming phrase matched — so the user can judge each on its merits:

```
N page(s) were held back because their body says not to use them:
  1. <title> — <webUrl>
     matched: "<disclaiming phrase>"
  2. ...
Register any of these anyway? Reply with the numbers (e.g. "1,3"), "all", or "none".
```

For each page the user chooses, register it as in Step 3, but **force `verification: "unverified"`** (with
`verified_by`/`verified_at` null) regardless of what its Update History table showed — a page whose body tells readers
not to use it must not carry a `human-verified` badge, even if its edit trail looks approved. Pages the user does not
choose are left unregistered. If no pages were held back, skip this step silently.

## Step 4 — Summary

State which mode ran, and report how many pages were processed vs. skipped:

```
Synced the project-index Catalog (<routine | full sweep>).
  • N pages found
  • P processed (X new rows inserted, Y rows updated)
  • S skipped as still fresh (not yet due for re-derivation)
  • Z held back as self-disclaiming (W registered after confirmation)
```

In full-sweep mode S is 0 (every page is processed). Omit the skipped line when S is 0, and the held-back line when
Z is 0.

## Notes

- **Idempotent.** A page renamed in Confluence makes a new `subject` (new row); the stale row ages out via
  reconciliation, not this skill.
- **Writes only the Catalog** — never edits Confluence or any Data Source.
- 0 results → check you can view the project-index spaces and that the label is spelled correctly.
