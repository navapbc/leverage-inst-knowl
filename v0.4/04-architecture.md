# Architecture

*The technical design. For the concepts in plain language, start with <u>Concepts</u>. Access control and identity are in <u>Access Control</u>; per-store mechanics in <u>Storage</u>; the build plan in <u>Strategy</u>.*

## 1. Purpose

Make institutional knowledge available to AI agents, AI-enabled apps, search platforms, and people — without each tool re-running expensive, repetitive searches across every source system.

Knowledge stays in the **Data Sources (DSs)**. A low-maintenance **Discovery Layer (DL)** makes discovery, prioritization, and retrieval faster and more reliable.

## 2. Core components

### Data Sources (DSs)
The systems where knowledge is created, corrected, summarized, governed, and accessed. **All permanent writes happen in a DS** — new knowledge, corrections, human-verified summaries — and DSs remain the source of truth.

### Discovery Layer (DL)
A **computed layer derived from DSs** — a *logical role, not a single store*. What makes something DL is **purpose, not location**: it exists to make DS knowledge faster to find and reuse, and never holds primary knowledge authored for its own sake. Each piece is a **DL output**, and by **where it lives and who backs it up** every output is one of three:
- **A DS record** — most DL by volume: a summary, aggregation, index, categorization, prioritized pointer, retrieval hint, relationship map, dedup/canonical pointer, content-freshness/obsolescence signal, or propagated access-control hint, written into a DS and tagged with a `discovery-layer` marker. Still DL by role, but **a DS record for storage — the DS governs and backs it up** (so its durability is only as good as that DS's backup), with version-history revert as recovery. Born `ai-generated` and recomputable (rebuilt on demand); a person editing or verifying it makes that copy durable (`human-created`/`human-verified`).
- **The Catalog** — a directory mapping `type + subject → location` so tools know where each output lives (§3). Recomputable, so it's rebuilt rather than backed up.
- **Confirmation signals** — captured human trust that is no DS record and can't be derived from any DS. The **one DL output DL must retain deliberately** — recoverable only by restoring an earlier version, so wherever it outgrows a DS page into DL's own store, that store is what DL backs up (<u>Strategy</u> §3.1).

### Tags that travel with a DL output
Realized via whatever the store supports (a column, a label, a page property) — no bespoke system.
- **Provenance/verification:** `ai-generated` (default), `human-created`, `human-verified`, `discovery-layer` — the marker also lets a skill recognize a DS-stored artifact as DL and register it in the Catalog automatically.
- **Lifecycle/trust:** content freshness/staleness, obsolescence, trust/confirmation signal.
- **Classification:** entry type + subject (Catalog keys), category (also an ACL-mapping input).
- **Access control:** propagated ACL metadata (a *hint* only), sensitivity.

#### Content-freshness signals
Derived hints about how current a piece of prepared material (or its underlying source) is, so a consumer can judge whether to trust it. They are *content* freshness — distinct from the **permission freshness** of <u>Access Control</u>, which tracks whether access has been revoked. Each is produced from a Catalog-schema column (§3):
- **Last-updated date** — the underlying source record's own modified timestamp ("source last edited 3 days ago" vs. "2 years ago").
- **Version drift** — the output was computed from source `v5` but the source is now `v7`; detected by comparing the version/etag stored in `source_refs`.
- **A `current` / `stale` / `obsolete` tag** — the explicit `freshness` column.
- **Last-validated timestamp** — `last_validated_at`: when the skill last confirmed the pointer resolves and the sources are unchanged; a long-ago validation is itself a staleness flag.
- **Obsolescence** — the record has been superseded (a newer doc replaces it, a ticket is closed/resolved, a space is deprecated).
- **"Confirmed, but edited since"** — a cited source was confirmed accurate, but it changed afterward, so the prior trust no longer cleanly applies (<u>Strategy</u> §3.2).

## 3. The Catalog

DL's directory — a "yellow pages" you consult to find *where* an output lives (`type + subject → location`), then follow the pointer. It indexes DL's **topology** (where outputs live), not DS content, so a subject's pointers can migrate from one store to another by changing one row, with no agent change.

**Why it's needed:** DL deliberately spreads outputs across many stores. Without one known starting point, every tool would hard-code the topology or fan out and search every store on each query — the exact repetitive searching DL exists to eliminate. The Catalog gives consumers **one lookup**, decoupled from storage.

It is the one un-pointed-to artifact, so it lives at a **well-known address** agents know a priori. It can be a **single Confluence page** and is treated as **just another DS artifact**, with one tightening: because it's the single entry point everyone hits first, **all writes go through a DL-creation skill's service account** — autonomously for rows it computes, under a verified human assertion for human-created rows; no one edits rows directly. Reads stay open. Consumers treat a **missing or malformed row as a cache miss** — fall back to skill routing or a bounded fan-out rather than erroring.

**Start as a page, promote to a DB at scale.** A page suits low-cardinality pointers (dozens to low-hundreds of subjects). When subject count outgrows it, the same schema is **promoted to Postgres (or any indexed DB)** with no change to consumers — they still do one `(entry_type, subject)` lookup. See <u>Storage</u>.

### Catalog schema

The same columns apply in both realizations (Confluence-page table first, DB table later).

| Column | Type | Purpose |
|---|---|---|
| `entry_type` | enum/text | **Discovery key.** `project-summary`, `index`, `aggregation`, `retrieval-hint`, `trust-signal`, … |
| `subject` | text | **Discovery key.** `project: Atlas`, `client: Acme`, `team: Payments`. |
| `location` | URI | The pointer — Doc URL, Confluence page ID, `bq://dataset.table`, etc. |
| `store_kind` | enum | How to fetch: `gdoc` \| `gsheet` \| `confluence` \| `postgres` \| `bigquery` |
| `locator` | text (nullable) | Sub-location within the store (sheet tab, anchor, row filter). Null when `location` is the whole artifact. |
| `provenance` | enum | `ai-generated` (default) \| `human-created`. |
| `verification` | enum | `unverified` (default) \| `human-verified`. |
| `verified_by` / `verified_at` | email / timestamp (nullable) | Who promoted it, and when. |
| `freshness` | enum | **Content freshness:** `current` \| `stale` \| `obsolete`. |
| `source_refs` | text[] / JSON | DS records this output derived from (IDs/URLs + version/etag). **Powers staleness checks and re-derivation.** |
| `last_computed_at` / `last_validated_at` | timestamp | When last (re)derived; when the pointer/sources were last confirmed. |
| `access_groups` | text[] | Propagated ACL **hint** — the output's single assigned audience group. *Never trusted for enforcement.* |
| `sensitivity` | enum | `restricted` (default) \| `cleared`. |
| `category` | text (nullable) | Descriptive classification; also an ACL-mapping input (<u>Access Control</u>). |
| `computed_by` | text | The skill that owns this row. |
| `row_provenance` | enum | `skill` \| `human` — which writer owns the row, so the skill knows what it may re-derive vs. leave alone. |

**Keys.** Unique `(entry_type, subject)` — extend to `(…, category)` for per-category variants. One subject may have several rows across `entry_type`s. Index `access_groups` (GIN in Postgres) for query-time filtering.

**Notes.** No `created_at`/`updated_at`/`updated_by` in the Confluence realization — version history supplies them; add those columns only after promotion. `access_groups` is a hint, not a gate. `source_refs` is load-bearing: dangling-pointer detection and re-derivation both depend on it. `row_provenance`/`computed_by` let the skill re-derive only the rows it owns and leave human-created rows to revert-based recovery.

### Dangling-pointer resilience

A `location` can break: a DS page is deleted, a dataset is dropped, a doc is moved, or a space is reorganized. Then the pointer resolves to nothing. Three layers handle this — detection, recovery, and graceful consumer behavior — and none needs a new always-on service.

**Detection — reconciliation folded into existing runs.** Pointer checking rides on the scheduled skill runs that already maintain the Catalog (§5), not a separate watchdog. Each run, a skill confirms that the `location` of every row it owns still resolves, then stamps `last_validated_at`. `source_refs` makes this cheap: comparing the stored version/etag against the live source catches both a **vanished** target (the pointer fails) and a **drifted** one (the source moved past the version the output was built from). To close the edges per-skill runs miss — rows whose owning skill no longer runs, and human-owned rows nobody re-derives — one **owner-agnostic reconciliation pass** (itself just a skill) periodically reads every row's `location` to confirm it's reachable and updates `freshness` / `last_validated_at`. It only checks reachability; it never rewrites content.

**Recovery — by who owns the row.**
- **Skill-owned rows (`row_provenance = 'skill'`):** the owning skill re-derives — recompute the output, write it to its (possibly new) location, update the row. If the underlying source is itself gone (not merely moved), the output is no longer derivable, so the row is dropped or marked `obsolete` and consumers stop trusting it.
- **Human-owned rows (`row_provenance = 'human'`):** can't be recomputed. The reconciliation pass flags the row `obsolete` and surfaces it to its owner; recovery is the same revert-based path as any human-authored output. A human row is never silently deleted.

**Graceful degradation — a broken pointer never errors.** A consumer that follows a pointer to nothing treats it exactly like a missing row: a **cache miss**. It falls back to the Query skill's routing or a bounded fan-out and still returns an answer — a dangling pointer costs that one query some latency, never correctness. This is the point of the Catalog being a cache, not a system of record: the DSs stay the source of truth, so any stale or broken pointer is always recoverable by going to the source.

## 4. Data flows

```
DSs → DL-creation skill (one of many, per source/team) → DL (Catalog + chosen store, via MCP)
AI tools → Query skill (one of many, per topic) → known DL output directly, else read Catalog → follow pointers
Saved synthesis → user writes artifact (own SSO) → service account registers the Catalog pointer (human-owned row)
Confirmations → Confluence page (default) or integrity-enforcing store (at scale)
Durable updates → DSs
```

- **Creation & governance** — knowledge created/corrected/summarized in DSs; access via Google SSO + Groups (see <u>Access Control</u>).
- **DL population & refresh** — AI-assisted content via scheduled/manual skills that compute outputs, write each to its store via MCP, register locations in the Catalog, and run staleness checks on referenced DS content *and* their own pointers.
- **Saved synthesis** — when a user persists a cross-source answer (<u>Strategy</u> Level 4), the write **splits**: the user authors the artifact under their own SSO, then a service account registers the Catalog pointer with the user as `created_by` and `row_provenance = 'human'`. Because such an output isn't derivable from any single source, no skill re-derives it — recovery is revert.
- **Query & retrieval** — AI tools query DSs and DL via MCP under a verified SSO token, guided by one of many topic-specialized query skills. A skill that knows where its topic lives points straight there, skipping the Catalog; otherwise the agent reads the Catalog, then follows pointers.
- **Feedback & source updates** — users confirm whether a cited source was right or wrong (attributed, revertible); permanent updates always go to DSs.

## 5. Update mechanisms

All updates propagate/assign ACL metadata and register location in the Catalog.

- **AI skills** — for interpretation-heavy content. A skill reads DS content (respecting ACLs), computes indexes/aggregations/categories, detects content freshness/obsolescence, runs staleness checks on sources *and* its own pointers, writes to a backing store via MCP, registers the Catalog entry, provenance-marks outputs, and rebuilds only content it still owns. **There are many such skills, not one** — each customized to the source it handles.

**Overwrite safety.** Before recomputing any output it owns, the skill checks the target's **version history and overwrites only if the last revision was its own service account**. If a person edited it since, the skill leaves it untouched — that edit transferred ownership, promoting the output to `human-verified`/`human-created` (recoverable only by restoring an earlier version). In non-versioned stores, the same check reads the `provenance`/`row_provenance` columns instead.

## 6. Write model

- **New data** → a DS (policy → Confluence/Drive; decision → ticket/page).
- **Corrections** → a DS (guide the user to fix the underlying record).
- **Human-verified summaries** → a DS (DL may index/point to them).
- **AI-generated artifacts in DSs** → computed, human-readable output stored where people read it; provenance-marked, registered in the Catalog, written under a clear identity. Marked as `ai-generated`. Unverified until a human reviews it, becoming a `human-verified` DL output under that person's identity.
- **Persisted synthesis** → a user-saved cross-source synthesis stored as a new `human-created` DL output, under the **user's own SSO**, born `human-created`; durable and not recomputable (<u>Strategy</u>, Level 4).
- **Confirmations** → non-recomputable data; attributed; start as a Confluence-page table, promote to an integrity-enforcing store at scale.
- **The Catalog** → DL topology, written by the skill service account only; reads stay open.
- **DL writes** → only computed data, the Catalog, and confirmation signals. Never canonical new knowledge, human corrections, or human-verified summaries.

> **Use case — secured project information (courtesy of Ryn Bennett).** Portfolio managers restrict PMR meeting notes, the only place comprehensive per-program risk metrics are discussed; MA PFML now requires Program Manager approval to share sprint metrics. These walls inhibit data democracy. Independently-vetted [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ) was created as a workaround.

## 7. Why DL matters

Without DL each tool re-searches many DSs, raising latency, token usage, cost, missed context, duplicate work, inconsistent answers, and difficulty finding trusted/current info. DL is a reusable computed layer + a single Catalog to discover it, so tools have one known place to start instead of fanning out per query. It doesn't replace DSs — it makes them easier to use.
