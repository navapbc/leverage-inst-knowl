# Known Limitations

## Confluence MCP: Page Version Number Not Available

The Confluence MCP connector (`01fd8586-e417-4e54-ae66-45006d1e08b1`) does not expose a page **version number**. Neither `getConfluencePage` nor `searchConfluenceUsingCql` (with `expand=version`) returns a version field in the response body.

**What this rules out:** staleness checks that compare a stored version *number* against the live page's version number. That specific mechanism cannot work.

**What it does NOT rule out:** detecting whether a page's content has *changed* since DL last saw it. A version number is one way to detect change — it is not the only one.

**No stable native change signal either (verified live).** Beyond the missing version number, the connector exposes **no** stable timestamp to use as a marker. Both `getConfluencePage` and `searchConfluenceUsingCql` return `lastModified` only as a *human-readable relative string* (e.g. `"about 5 hours ago"`, `"Jun 18, 2026"`), and `expand=version` / `expand=history.lastUpdated` are silently ignored. Used *raw*, a relative string changes on every read even when the page hasn't, so it is unusable as an equality marker (it would flag every page as edited) — though parsing it to a day-granular date partly rescues it (see Option B below). The raw Confluence REST API does return `version.when` / `version.createdAt`, but this MCP connector does not pass them through.

### Marker options for Confluence

Two ways to derive the `source_state` content-state marker from this connector. **We implement Option A (content hash).**

**Option A — content hash of the page body (implemented).** Fetch the body via `getConfluencePage` (markdown) and hash it; change detection = `stored hash ≠ current hash`.
- *Pro:* exact change detection at any granularity; no timezone or format assumptions; bulletproof.
- *Pro:* free for the query path — the Query skill already fetches the body to answer, so the hash costs nothing extra there.
- *Con:* the **sync** path must add one `getConfluencePage` per page (the search result alone doesn't return the body), so a daily sync does N extra fetches.

**Option B — parse `lastModified` to a day-granular date (rejected, viable only at day precision).** Parse the relative string (`"about 5 hours ago"`, `"yesterday"`, `"Jun 18, 2026"`) into a calendar date and use that as the marker.
- *Only works at day granularity.* Parsed to a finer resolution it jitters: `"about 5 hours ago"` read at two different times yields two different timestamps for an unchanged page, false-positiving every read. Truncated to a date it is mostly stable (the day-relative forms are self-consistent: `"3 days ago"` on day X and `"4 days ago"` on day X+1 both resolve to X−3).
- *Pro:* **avoids the sync body fetch** — `lastModified` already rides the search result the sync crawls.
- *Con — under-flags intra-day edits:* two edits on the same day share a marker, so a since-confirmed same-day edit reads as "not edited." Acceptable only if day precision is genuinely the desired resolution.
- *Con — fragility:* the string renders in an **undocumented, localizable** format (Atlassian may change `"about 5 hours ago"` → `"5h"` / `"hace 5 horas"` anytime) in an **unspecified timezone** (day-truncation flips at the tz boundary; sync and query must pin the same tz or disagree by a day). Near-midnight edits can still flip the parsed date across reads — that direction over-flags, which is safe, but it is noise.
- *Requires:* a fixed-tz normalization, a parser for the connector's known format set, and a **content-hash fallback** when the string doesn't parse. Adopting it needs a small spike to characterize the format/threshold/tz space (only two sample formats have been observed).

**When Option B would win:** if the sync body fetch becomes a real cost (page volume, rate limits) **and** day-level change detection is acceptable. Until then, Option A's simplicity and exactness outweigh saving one fetch per page on a daily job.

### Live spike (2026-07-27): `lastModified` characterized — and the two read paths disagree

Ran the pre-implementation spike for using `lastModified` as a day-granular pre-filter hint (not as the
`source_state` marker — the body hash stays that). CQL `label = "project-index" AND type = page` over 111
pages, plus a controlled body-edit test. Findings:

- **Format set is small and enumerable.** Only three shapes seen in the wild:
  `less than a minute ago`, `about N hours ago`, and the absolute `Mon DD, YYYY` (date-only). Confluence
  renders relative for recent edits and switches to the absolute form once older. A parser must treat any
  unrecognized shape (`yesterday`, `last week`, localized/abbreviated variants) as **always-process**, never
  guess.
- **`getConfluencePage` and `searchConfluenceUsingCql` populate `lastModified` from different sources — and
  the per-page one is stale.** After a human edited a page body and published, the **CQL** result's
  `lastModified` advanced to `less than a minute ago` (correct), while `getConfluencePage` for the same page
  still returned a 21-day-old date **even though its own body payload reflected the just-published edit**.
  So: the CQL `lastModified` **does track main-body edits** (validated), but the `getConfluencePage`
  `lastModified` is cached/stale and must **never** be trusted for change detection. Any `lastModified`-based
  hint must be read **only from the CQL search result**.
- **Timezone can't be pinned from read-only access** (the connector exposes no absolute timestamp, and the
  absolute form is date-only). Low-risk in practice: old absolute dates never flip; only recent
  relative-form pages near a midnight boundary could, and there over-flagging (an extra fetch) is safe.
  Normalize to a single fixed tz (UTC is a safe default).
- **Still no native timestamp.** `getConfluencePage` confirmed to expose no `version.when` / `createdAt` —
  the body hash (Option A) remains the drift source of truth.

Net: Option B is viable **only** as a day-granular pre-filter *hint* sourced strictly from the CQL result,
with a content-hash fallback for unparseable strings — not as a standalone marker. Full spike write-up:
[docs/brainstorms/2026-07-27-02-catalog-refresh-due-ttl-spike-results.md](docs/brainstorms/2026-07-27-02-catalog-refresh-due-ttl-spike-results.md).

**Design impact:** confirmations and `catalog.source_refs[]` anchor to an opaque content-state marker compared by equality, not to a version number. See [docs/brainstorms/2026-06-25-02-confirmation-content-state-marker-requirements.md](docs/brainstorms/2026-06-25-02-confirmation-content-state-marker-requirements.md). For Confluence the marker is a content hash of the page body (Option A) — not `lastModified` — so change detection is not blocked by the missing version number.

## Confluence MCP: `getConfluencePage` Returns the Wrong Page Under Concurrency

When multiple `getConfluencePage` calls run **concurrently** (same batch / parallel tool
calls), the connector sometimes returns a **different page than the `pageId` requested** —
the response carries another in-flight request's content. Observed live during a sync of 15
project-index pages: two pages' Update-History fetches each came back with an *unrelated*
page's body (a third page that was also being fetched in the same batch). The returned object's
`id` field did **not** match the requested `pageId`.

**Impact:** silent data corruption. A hash or verification computed from a mismatched body is
wrong but looks valid — there is no error, just the wrong content. For a body-hash marker
(Option A above) this means a `source_state` that belongs to the wrong page.

**Mitigations:**
- **Serialize** `getConfluencePage` calls — issue them one at a time, not in a parallel batch.
- **Verify `id`** on every response: assert the returned object's `id` equals the requested
  `pageId`; on mismatch, retry until it matches.

`searchConfluenceUsingCql` showed a related symptom under concurrency (one query's result
duplicated another's), so the same serialize-and-verify discipline applies to batched CQL
lookups.
