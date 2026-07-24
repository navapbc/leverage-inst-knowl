---
name: lik-sync-catalog-from-project-indexes
description: Catalog the project-index pages from Confluence into the Discovery Layer Catalog (the lik-mcp service). Fetches every Confluence page tagged `project-index` and upserts one Catalog row per page via `register_catalog_entry`. Use whenever someone says "sync the project indexes", "refresh the project-index catalog", "catalog the project indexes", or asks to (re)build Catalog rows from the Project Index Directory. This is a DL-creation skill: the project-index pages are authored by a separate process; this skill only registers them as Catalog rows — it writes to the Catalog, never to Confluence.
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

## Step 4 — Summary

```
Synced N project-index pages into the Catalog.
  • X new rows inserted
  • Y rows updated
```

## Notes

- **Idempotent.** A page renamed in Confluence makes a new `subject` (new row); the stale row ages out via
  reconciliation, not this skill.
- **Writes only the Catalog** — never edits Confluence or any Data Source.
- 0 results → check you can view the project-index spaces and that the label is spelled correctly.
