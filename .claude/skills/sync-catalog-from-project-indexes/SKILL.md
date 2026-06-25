---
name: sync-catalog-from-project-indexes
description: Catalog the project-index pages from Confluence into the Discovery Layer Catalog in Postgres (the lik-mcp service). Fetches every Confluence page tagged `project-index` and upserts one Catalog row per page via `register_catalog_entry`. Use whenever someone says "sync the project indexes", "refresh the project-index catalog", "catalog the project indexes into Postgres", or asks to (re)build Catalog rows from the Project Index Directory. This is a DL-creation skill — it writes to the Catalog, not to Confluence.
---

# Sync Catalog from Project Indexes

Crawls all Confluence pages tagged `project-index` and registers one **Catalog** row per
page in the Discovery Layer's service-fronted store (Postgres, fronted by the **lik-mcp**
MCP service). This is the Postgres counterpart of the `discovery-catalog-sync` skill, which
writes the same source pages into a Confluence table instead.

This is an expensive crawl — run it on demand only, when you want to (re)populate the
Catalog for testing or use. Re-running is safe: each row upserts on its key, so a second
run updates rows in place rather than duplicating them.

## Prerequisites

- The **lik-mcp** MCP service is connected and pointed at the database you want to populate
  (for manual testing, `likdb_local` — see the lik-mcp README "Local database").
- The Atlassian (Confluence) MCP tools are available.

## What to do

### Step 1 — Fetch all project-index pages from Confluence

Call `searchConfluenceUsingCql` with:
- cloudId: `navasage.atlassian.net`
- cql: `label = "project-index" AND type = page`
- limit: 250

For each result, collect:
- `title` → the project name
- `webUrl` → the page URL
- page **ID** → the Confluence page ID
- `space.name`, `summary`, `lastModified`, `author.displayName` → context (optional)

The `label = "project-index"` CQL is the canonical source of truth — it matches exactly what
the Project Index Directory renders via its Page Properties Report macro.

**Note:** The Confluence MCP connector exposes no stable change signal — no version number,
and `lastModified` comes back only as a relative string like `"about 5 hours ago"` (see
[../../../limitations.md](../../../limitations.md)). So the content-state marker is a **hash
of the page body**, computed per the shared recipe below.

### Content-state marker recipe (shared with `query-project-index`)

`source_state` is the SHA-256 hex digest of the page's markdown body:

1. Fetch the body: `getConfluencePage(pageId, contentFormat: "markdown")`, take the `body` field **verbatim**.
2. Write that exact string to a file (no added trailing newline, no normalization) and hash it: `shasum -a 256 FILE | cut -d' ' -f1` (or `sha256sum FILE | cut -d' ' -f1` — both yield the same digest for the same bytes).

The `query-project-index` skill computes `source_state` the **identical** way, so a stored
marker and a live marker compare equal whenever the content is unchanged. Any change to this
recipe must be mirrored in both skills or "edited since" will false-positive on every page.

### Step 2 — Read each page's Update History

For each page from Step 1, find and read its Update History child page.

**2a — Find the child page.** Call `searchConfluenceUsingCql` with:
- cloudId: `navasage.atlassian.net`
- cql: `ancestor = "<pageId>" AND title = "Update History" AND type = page`
- limit: 1

If no result → `verification = "unverified"`. Skip 2b.

**2b — Read the page body.** Call `getConfluencePage` with the returned page ID and
`contentFormat: "markdown"`. The body contains a table of update history entries.

Interpret the table to decide whether a human has verified the project index:
- `human-verified` — the table has at least one row where the content indicates a deliberate
  review was performed (e.g., a row with a date, reviewer name, or explicit "reviewed" /
  "verified" / "updated" signal). Use the **most recent such row** (last row with a date).
  - Extract the **"Approved By"** column value → `verified_by`
  - Extract the **"Date"** column value → `verified_at` (parse to ISO 8601 UTC datetime)
- `unverified` — the table is empty, contains only a header row, or its rows carry no
  meaningful review signal (e.g., all cells blank or placeholder text). Leave `verified_by`
  and `verified_at` as null.

Set `verification`, `verified_by`, and `verified_at` accordingly.

You may batch the CQL lookups in parallel across all pages; fetch each page body only after
its CQL returns a hit.

**2c — Compute the content-state marker.** Fetch the **main** project-index page body
(`getConfluencePage(<pageId>, contentFormat: "markdown")`, the page from Step 1 — not its
Update History child) and compute `source_state` per the Content-state marker recipe above.

### Step 3 — Register one Catalog row per page

For each page, call `register_catalog_entry` (the lik-mcp tool) with an `entry` shaped like:

- `entry_type`: `"index"`  *(these pages are curated indexes)*
- `subject`: `"project: <title>"`  *(e.g. `"project: Atlas"`)*
- `location`: the page `webUrl`
- `store_kind`: `"confluence"`
- `locator`: the Confluence page ID  *(so a consumer can `getConfluencePage` directly)*
- `source_refs`: `[{ "id": "<pageId>", "source_state": "<SHA-256 body hash from Step 2c>" }]`  *(powers staleness checks; `source_state` is the page's opaque content-state marker — a body hash — compared by equality to detect "edited since")*
- `verification`: `"human-verified"` or `"unverified"` — from Step 2
- `verified_by`: the "Approved By" value from the Update History table, or null
- `verified_at`: the "Date" value (ISO 8601 UTC), or null
- `computed_by`: `"sync-catalog-from-project-indexes"`
- `row_provenance`: `"skill"`

Leave the other fields at their defaults (`provenance=ai-generated`, `freshness=current`,
`sensitivity=cleared`, empty `access_groups`). Each call returns a status of `inserted` or
`updated` — tally these for the summary.

### Step 4 — Summary

Respond with:

```
Synced N project-index pages into the Catalog (Postgres).
  • X new rows inserted
  • Y rows updated
```

## Notes

- **Idempotent.** The Catalog upserts on `(entry_type, subject)`, so re-running updates rows
  in place. A page renamed in Confluence creates a new `subject` (a new row) rather than
  updating the old one — the stale row ages out via reconciliation, not this skill.
- **Targets whatever DB lik-mcp points at.** For manual testing that should be `likdb_local`,
  not the disposable `likdb_test`. Confirm the server's `LIK_DB_NAME` before a real run.
- **Writes only the Catalog.** This skill never edits Confluence pages or any other Data
  Source — it only records where each project-index page lives.
- If the search returns 0 results, verify you have permission to view the project-index spaces
  and that the label is spelled correctly.
