---
name: lik-sync-catalog-from-project-indexes
description: Catalog the project-index pages from Confluence into the Discovery Layer Catalog (the lik-mcp service). Fetches every Confluence page tagged `project-index` and upserts one Catalog row per page via `register_catalog_entry`. Use whenever someone says "sync the project indexes", "refresh the project-index catalog", "catalog the project indexes", or asks to (re)build Catalog rows from the Project Index Directory. This is a Catalog-registration skill: the project-index pages are authored by a separate process; this skill only registers them as Catalog rows — it writes to the Catalog, never to Confluence.
---

# Sync Catalog from Project Indexes

Crawl every Confluence page tagged `project-index` and register one **Catalog** row per page in the Discovery Layer's
Catalog store (fronted by the **lik-mcp** service). This is the Catalog-store counterpart of `discovery-catalog-sync`,
which writes the same pages into a Confluence table instead.

An expensive crawl — run on demand only. Re-running is safe: each row upserts on its key, so a second run updates in
place rather than duplicating.

## Prerequisites

- **lik-mcp** connected

## Step 1 — Fetch all project-index pages

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
- optionally `space.name`, `summary`, `lastModified`, `author.displayName` for context

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

## Content-state marker recipe (shared with `lik-query-project-index`)

`source_state` = the SHA-256 hex digest of the page's markdown body:
1. `getConfluencePage(pageId, contentFormat: "markdown")`, take the `body` **verbatim**.
2. Write it to a file (no added trailing newline, no normalization) and hash: `shasum -a 256 FILE | cut -d' ' -f1` (or
   `sha256sum FILE | cut -d' ' -f1` — same digest for the same bytes).

`lik-query-project-index` computes `source_state` the **identical** way, so a stored and a live marker compare equal
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
- `source_refs`: `[{ "id": "<pageId>", "source_state": "<body hash from Step 1>" }]`  *(powers staleness checks;
  compared by equality to detect "edited since")*
- `verification`: from Step 2
- `verified_by` / `verified_at`: from the Update History table, else null
- `computed_by`: `"lik-sync-catalog-from-project-indexes"`
- `row_provenance`: `"skill"`

Leave other fields at defaults (`provenance=ai-generated`, `freshness=current`, `sensitivity=cleared`, empty
`access_groups`). Each call returns `inserted` or `updated` — tally for the summary.

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

```
Synced N project-index pages into the Catalog.
  • X new rows inserted
  • Y rows updated
  • Z held back as self-disclaiming (W registered after confirmation)
```

Omit the held-back line when Z is 0.

## Notes

- **Idempotent.** A page renamed in Confluence makes a new `subject` (new row); the stale row ages out via
  reconciliation, not this skill.
- **Writes only the Catalog** — never edits Confluence or any Data Source.
- 0 results → check you can view the project-index spaces and that the label is spelled correctly.
