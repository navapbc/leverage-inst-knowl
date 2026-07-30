---
name: adhoc-catalog-registration
description: Register an existing Data Source record — a Confluence page or a Google doc/sheet the user points at mid-chat — into the Discovery Layer Catalog (the lik-mcp service) as a human-owned entry point, so it's discoverable in one lookup. The user names the target and the topic; this skill fetches it, proposes the discovery key, asks whether the user is vouching for it or just flagging a pointer (which sets its ranking), and registers a human-owned Catalog row via register_catalog_entry under the user's own identity. No write access to the target is required. Use whenever someone says "register this page as the entry point for X", "add this doc to the catalog", "catalog this page/sheet", "make this the go-to page for <topic>", or points at a specific record and asks to make it discoverable. Do NOT use to (re)build the project-index catalog (that's sync-catalog-from-project-indexes), and do NOT author a new producer/registrar skill by hand.
---

# Ad-hoc Catalog Registration

Register **one existing record the user points at** — a Confluence page, or a Google doc/sheet — as a **human-owned**
entry point in the Discovery Layer Catalog (fronted by the **lik-mcp** service), so the next person finds it in one
`(entry_type, subject)` lookup. The user already knows this record is the best entry point for a topic; your job is to
fetch it, agree on the discovery key, capture whether they vouch for it, and write the Catalog row.

This is the **manual (human) registration** path — the counterpart to the automated registrar
(`sync-catalog-from-project-indexes`). The differences that shape everything below:

- The row is **human-owned** (`row_provenance = "human"`): no skill will ever re-derive it, so it is never scheduled for
  refresh and it never upserts — **each registration inserts a new pointer**, and duplicates on a key coexist as
  ranked rows.
- **Registering designates** the target a DL record. The Catalog row itself is the authoritative record of the
  entry-point role, so tagging the source with the `discovery-layer` marker is **optional** — and therefore **write
  access to the target is not required**. A user can register a page they can only read.
- The user's **identity is attributed automatically** by the server from their verified login — **never pass any
  identity, email, or "created by" field** in the registration payload.

## One record at a time

This path registers a single record the user names in conversation. It is not a crawl and not a batch. If the user
wants many records catalogued from a source (e.g. "catalog all our project indexes"), that is the registrar's job —
point them at `sync-catalog-from-project-indexes` instead of registering by hand in a loop.

## Prerequisites

- **lik-mcp** connected (for `register_catalog_entry`).
- The Data Source MCP for the target: **Atlassian/Confluence** for a page, **Google Drive** for a doc/sheet. If the
  needed source isn't connected, say so and stop — don't guess the record's fields.

## Step 1 — Resolve and fetch the target once

Get the record the user pointed at and read it **once** to populate the row. What you read:

- **Confluence page** — `getConfluencePage(pageId, contentFormat: "markdown")` (cloudId `navasage.atlassian.net`).
  Read `title`, `webUrl`, the page `id`, and the markdown `body`. Apply the **Response integrity guard** (below) before
  using any field. The content-state marker is a **SHA-256 hash of the verbatim markdown body**, computed the identical
  way as `sync-catalog-from-project-indexes` / `query-project-index` (recipe below) — Confluence exposes no stable
  version signal.
- **Google doc/sheet** — fetch it via the Google Drive connection by its file ID / URL. Read the title, the file's
  `webViewLink`/URL, the file ID, and its `modifiedTime` (or version identifier). The content-state marker for a Drive
  file is its **`modifiedTime` / version identifier** — Drive gives a real change signal, so no body hash is needed.

If the fetch fails or the source is unavailable, **stop and report** the error, its likely cause, and the remedy —
don't register a row from guessed fields.

### Content-state marker recipe (Confluence — shared with the project-index skills)

`source_state` = the SHA-256 hex digest of the page's markdown body:
1. `getConfluencePage(pageId, contentFormat: "markdown")`, take the `body` **verbatim**.
2. Write it to a file (no added trailing newline, no normalization) and hash: `shasum -a 256 FILE | cut -d' ' -f1`.

This must match the other skills' recipe exactly, or later staleness checks false-positive on every page.

### Response integrity guard (required)

Run concurrently, a fetch can silently return the **wrong** record's body. Before hashing or using any field, assert
the returned `id` equals the requested one (and any search result belongs to the query you sent). On mismatch, re-issue
that call serially until it matches, or fail rather than register from a mismatched body.

## Step 2 — Propose the discovery key (`entry_type`, `subject`)

The lookup key is `(entry_type, subject)`. Propose both from what you fetched and the topic the user named; the user
confirms or adjusts.

- **`subject`** — the topic a person would look up (usually the record's title, or the topic phrase the user gave).
- **`entry_type`** — pick from the **established vocabulary** describing *what this record is as an entry point*:
  `project-summary`, `index`, `aggregation`, `retrieval-hint`, `trust-signal`, and the like (see the DL-record kinds in
  the architecture doc). Choose the one that fits how the record serves discovery.

**Never invent a registration-specific `entry_type`** — there is no `manual` or `ad-hoc` type. That a human registered
this is already recorded by `row_provenance = "human"`; `entry_type` describes the record, not who filed it.

**Coining a brand-new `entry_type` is discouraged by default.** If the user insists on a type outside the established
vocabulary, first surface that **a key nobody queries is effectively undiscoverable** — the row won't be found
unless a consumer looks up that exact new type — and proceed only on the user's **deliberate confirmation**. Prefer
steering them to an existing type.

## Step 3 — Vouch or flag (sets `verification` and ranking)

Ask the user, framed as a **ranking** choice, not a correctness one:

> Are you **vouching** for this record as the go-to entry point for this topic, or just **flagging** it as a useful
> pointer? A vouch ranks it as the **default** entry point on this key; a flag ranks it **below** any vouched record.

- **Vouching** → `verification: "human-verified"`, with `verified_by`/`verified_at` set to the user and the current
  time. **Before you write a vouch, confirm the exact target:** show the record's **title** and **last-updated**, and
  have the user confirm it's the right record — this guards against vouching for a mis-resolved page.
- **Just flagging** → `verification: "unverified"` (leave `verified_by`/`verified_at` null).

A vouched row sorts above unverified rows on the same key; a flagged row sorts below any vouched row. That is the whole
consumer-facing effect of this choice.

## Step 4 — Audience and sensitivity (default-deny)

Set the row's audience no broader than the source, defaulting closed:

- **`access_groups`** — the audience for this pointer, **no broader than the source record's own access**. If the user
  doesn't specify, leave it **empty (default-deny)** rather than guessing a broad audience.
- **`sensitivity`** — default **`restricted`**. Set `cleared` **only** when the user explicitly states the target is
  broadly / publicly readable. When unsure, keep `restricted`.

The Catalog exposes a row's existence and location, not the target's content, and enforcement stays at the source —
but default-deny keeps a restricted record's metadata from ranking to a broad audience.

## Step 5 — Optional: tag the source (only with write access + opt-in)

The Catalog row already carries the entry-point role, so tagging the source is **never required**. Offer it **only** if
**both**: the user can write to the target, **and** they want the entry-point role visible in the source itself. If so,
add the source's `discovery-layer` marker in whatever form that store supports (e.g. a Confluence `discovery-layer`
label). Otherwise **skip tagging entirely** — never attempt a write to a record the user can only read.

## Step 6 — Register the human-owned row

`register_catalog_entry` (lik-mcp) with an `entry`:

- `entry_type`: from Step 2
- `subject`: from Step 2
- `location`: the record's URL (`webUrl` / `webViewLink`)
- `store_kind`: `"confluence"` for a page, `"gdoc"` for a Google doc, `"gsheet"` for a Google sheet
  *(never `"gdrive"` — the Catalog doesn't recognize it)*
- `locator`: the Confluence page ID or the Drive file ID
- `source_refs`: `[{ "id": "<page or file id>", "source_state": "<Confluence body hash, or Drive modifiedTime/version>" }]`
- `verification`: from Step 3 (`"human-verified"` or `"unverified"`)
- `verified_by` / `verified_at`: set when vouching (Step 3); otherwise omit
- `access_groups`: from Step 4 (empty if unspecified)
- `sensitivity`: from Step 4 (`"restricted"` default)
- `computed_by`: `"adhoc-catalog-registration"`  *(audit only on the human path — human rows are not part of the
  skill-only upsert key, so this records which skill wrote the row and nothing more)*
- `row_provenance`: `"human"`

**Leave these unset:**
- `provenance` — drives nothing for a human-owned row; accept the default rather than asking.
- `refresh_due_at`, `last_computed_at` — human rows are never scheduled for re-derivation.

**Never pass identity.** The server stamps the registering user from their verified login automatically. Do not send an
email, `created_by`, or `updated_by` in the payload.

Each human registration **inserts** a new row (it never upserts), so registering the same record twice creates a second
pointer. If the user is intentionally superseding an earlier row, say so — there is no automatic replacement.

## Step 7 — Summary

Confirm what was registered, in one short block:

```
Registered <title> as a Catalog entry point.
  • key: (<entry_type>, <subject>)
  • ranking: <vouched — default entry point | pointer — ranks below vouched rows>
  • audience: <access_groups or "restricted, no audience set">
  • source tag: <added discovery-layer | not tagged>
```

## Notes

- **Writes the Catalog, and the source only if the user opted into tagging.** By default it touches no Data Source.
- **Human-owned rows are never re-derived.** Staleness is surfaced to the owner like any human row; this skill does not
  schedule or maintain the row.
- **Duplicates on a key are intentional and coexist as ranked rows** — a vouched row wins; superseding is a deliberate
  separate action, never automatic.
