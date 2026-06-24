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

**Note:** The Confluence MCP connector does not expose page version numbers. Do not attempt
to collect a version from the search result — use a fetch timestamp instead (see Step 2).

### Step 2 — Register one Catalog row per page

For each page, call `register_catalog_entry` (the lik-mcp tool) with an `entry` shaped like:

- `entry_type`: `"index"`  *(these pages are curated indexes)*
- `subject`: `"project: <title>"`  *(e.g. `"project: Atlas"`)*
- `location`: the page `webUrl`
- `store_kind`: `"confluence"`
- `locator`: the Confluence page ID  *(so a consumer can `getConfluencePage` directly)*
- `source_refs`: `[{ "id": "<pageId>", "fetched_at": "<current UTC timestamp in ISO 8601>" }]`  *(powers staleness checks; `version` is omitted because the Confluence MCP connector does not expose it — use `fetched_at` as the proxy recency signal instead)*
- `computed_by`: `"sync-catalog-from-project-indexes"`
- `row_provenance`: `"skill"`

Leave the other fields at their defaults (`provenance=ai-generated`, `verification=unverified`,
`freshness=current`, `sensitivity=cleared`, empty `access_groups`). Each call returns a
status of `inserted` or `updated` — tally these for the summary.

### Step 3 — Summary

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
