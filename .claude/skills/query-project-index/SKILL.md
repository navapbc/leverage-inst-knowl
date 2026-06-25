---
name: query-project-index
description: Answer questions about Nava's projects using the Discovery Layer Catalog in Postgres (the lik-mcp service) and the project-index pages it points to. Use whenever someone asks about past work, project capabilities, agencies Nava has worked with, technologies used, or anything answerable from vetted project-index pages. Triggers on questions like "what has Nava done with X?", "find projects related to Y", "which projects involve Z agency", "tell me about the <name> project". Do NOT use for HR/policy questions or general web research.
---

# Query Project Index

Answers a project question from the **Catalog** (the lik-mcp service over Postgres), following
its pointers to the project-index pages in Confluence. It escalates through three levels and
**asks the user before widening scope** at each step, so the Catalog stays the primary path and
a broad Confluence search is only a last resort.

It also surfaces and accumulates **confirmation signals**: it shows how vouched-for each cited
source is (`read_confirmations`) and offers to record the user's confirmation (`confirm_source`).

## Prerequisites

- The **lik-mcp** MCP service is connected (pointed at `likdb_local` for manual testing) and the
  Catalog has been populated by the `sync-catalog-from-project-indexes` skill.
- The Atlassian (Confluence) MCP tools are available (for reading pages and the Level 3 fallback).

Use the text the user passes to this skill as their question.

## Errors

If any tool call fails or a required tool is unavailable, **stop immediately**. Do not fall
through to the next level. Present:
1. The error or missing tool name
2. Likely root causes (e.g. server not running, tool not yet deployed, MCP session stale)
3. Remedies (e.g. restart the server, reconnect MCP, redeploy)

## Level 1 — exact Catalog lookup, then fuzzy lookup

If the question names a specific project, derive `subject = "project: <name>"` and call
`lookup_catalog_entry` with `entry_type = "index"` and that `subject`.

- **Hit:** follow the row — `getConfluencePage` at its `locator` (page ID) or `location` (URL) —
  read the page, and answer from it. Go to **Rank & present**.
- **Miss**, or the question doesn't name a single project exactly: call
  `search_catalog_entries` with `entry_type = "index"` and the question's key terms as
  `query`. This catches partial names, typos, and reordered words.
  - **Candidate hit(s):** follow the top candidate's pointer (`getConfluencePage` at its
    `locator`/`location`), read the page, and answer. Go to **Rank & present**.
  - **No candidates:** go to **Level 2 (ask first)**.

`search_catalog_entries` is a **targeted, bounded keyed lookup** — top-N ranked candidates,
not a full read — so it runs **without** the "ask before widening" prompt that Levels 2 and 3
require. It stays part of the primary Catalog path.

## Level 2 — list and scan (ask the user first)

On a Level 1 miss, **pause and ask the user** (let them pick a single letter):

> No exact Catalog match. How should I widen the search?
> **(a)** List all project-index entries from the Catalog and scan them, or
> **(b)** Skip to a Confluence search over project-index pages.

If **(a)**: call `list_catalog_entries` with `entry_type = "index"`. Scan the returned rows
(match the question's terms against each `subject` and `category`), pick the most relevant ones,
`getConfluencePage` their pointers, and answer. Then go to **Rank & present**.

If the scan finds nothing relevant, ask again before Level 3. If **(b)**: go to **Level 3**.

## Level 3 — Confluence fallback (ask the user first)

Only with the user's go-ahead, call `searchConfluenceUsingCql` with:
- cloudId: `navasage.atlassian.net`
- cql: `label = "project-index" AND text ~ "<key terms>"`

Read the top matches and answer, noting that this answer came from a **bounded Confluence search**,
not the Catalog. Then go to **Rank & present**.

A Catalog miss or a broken pointer is never an error — it's a cache miss that degrades to the next
level.

## Rank & present (every level)

For each page you're about to cite, build a citation:
- `store_kind`: `"confluence"`
- `location`: the page URL
- `locator`: the page ID
- `version`: the **current** page version (from `getConfluencePage` in this run)

Call `read_confirmations` with that citation. It returns confirmations across **all versions** of
the source, each carrying its own `version`. Split them:
- **current-version** confirmations (row `version` == the live page version), and
- **prior-version** confirmations (any other version).

Rank sources with current-version trust weighed more heavily than prior-version trust, and present
the answer with each citation annotated, e.g. *"(3 confirmations on this version, 1 on an earlier
version)"*.

## Confirm (after answering)

Offer: *"Confirm any of these sources as correct? Reply with the source number."* On a pick, call
`confirm_source` with the **same citation** (the live page `version`), passing the user's email as
the token so `confirmed_by` is the real person, not the service account. Report the result:
- `recorded` — confirmation saved.
- `duplicate` — this user already confirmed this source-version (no-op).
- `rejected` — the citation didn't resolve; say so and don't retry.

## Notes

- Use one consistent `version` per source within a run (the live page version) so the confirmation
  you write and the ones you read line up.
- This skill is self-contained — it does not fetch instructions from Confluence.
- Reads are open; writes (confirmations) are attributed to the verified caller.
