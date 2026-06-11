---
name: discovery-catalog-sync
description: Sync the Discovery Layer Catalog Google Sheet by fetching all Confluence pages tagged with `project-index` and upserting a row for each one. Use whenever someone says "sync the catalog", "update the discovery catalog", "refresh the catalog from Confluence", or asks to add/update catalog entries from the Project Index Directory. The catalog spreadsheet ID is 1awd09QT94UiHj7ubUgV3lz_qscxe2NmF06irlcqWVG0.
---

# Discovery Layer Catalog Sync

Syncs the **Discovery Layer Catalog** Google Sheet with all Confluence pages tagged `project-index`. The Project Index Directory page surfaces these pages via a Page Properties Report macro using `label = "project-index"` as its CQL query.

## What to do

### Step 1 — Fetch all project-index pages from Confluence

Call `searchConfluenceUsingCql` with:
- cloudId: `navasage.atlassian.net`
- cql: `label = "project-index" AND type = page`
- limit: 250

For each page in the results, collect:
- `title` → **Name**
- `webUrl` → **URL**
- `space.name` → **Space**
- `type` → **Type** (always "page")
- `summary` → **Description** (trim to a readable length; omit label noise like "project-index" at the end)
- `lastModified` → **Last Modified**
- `author.displayName` → **Author**

If you want richer metadata (Portfolio, Primary Archetype, etc.), fetch each page individually using `getConfluencePage` with `contentFormat: "html"` and look for a `details` macro table. Parse its rows as `key: value` pairs and add them as additional columns. Only do this if the user explicitly asks for it — it adds one API call per page and can be slow.

### Step 2 — Read the current catalog sheet

Call `read_file_content` (Google Drive MCP) with fileId `1awd09QT94UiHj7ubUgV3lz_qscxe2NmF06irlcqWVG0`.

Parse the result as CSV. The expected columns are:
```
Name, URL, Space, Type, Description, Last Modified, Author
```

Build an in-memory map keyed by **URL** so you can detect which rows are new vs. already present.

### Step 3 — Upsert rows

For each page from Confluence:
- If a row with the same URL already exists → update it with the freshest values from Confluence.
- If no row exists with that URL → append a new row.

Preserve any rows in the current sheet that were *not* returned by the Confluence query (they may have been added manually).

### Step 4 — Write the updated catalog

The Google Drive MCP does not support in-place cell updates. To persist changes, create a new Google Sheet from the merged CSV:

```
create_file(
  title: "Discovery Layer Catalog",
  textContent: <merged CSV string>,
  contentMimeType: "text/csv"
)
```

This creates a new spreadsheet. Tell the user:
- The new sheet URL
- How many rows were added vs. updated vs. unchanged
- That the old sheet (`https://docs.google.com/spreadsheets/d/1awd09QT94UiHj7ubUgV3lz_qscxe2NmF06irlcqWVG0`) can be deleted manually if they no longer need it

### Step 5 — Summary

Respond with a tight summary:
```
Synced N pages from Confluence.
  • X new rows added
  • Y rows updated
  • Z rows unchanged

New catalog: <link>
```

## Notes

- The `label = "project-index"` CQL is the canonical source of truth — it matches exactly what the Project Index Directory page renders via its Page Properties Report macro.
- If the search returns 0 results, verify the user has permission to view project index spaces and that the label is spelled correctly.
- The columns in this catalog may evolve. If new columns are added manually in the sheet, preserve them when merging — only update the standard columns listed above.
