# Architecture

*The technical design. For the concepts in plain language, start with <u>Concepts</u>. Access control and identity are in <u>Access Control</u>; per-store mechanics in <u>Storage</u>; the build plan in <u>Strategy</u>.*

## 1. Purpose

Make institutional knowledge available to AI agents, AI-enabled apps, search platforms, and people — without each tool re-running expensive, repetitive searches across every source system. Re-searching per query raises latency, token cost, missed context, duplicate work, and inconsistent answers, and makes trusted or current information hard to find.

Knowledge stays in the **Data Sources (DSs)**. A low-maintenance **Discovery Layer (DL)** — a reusable computed layer plus a single Catalog to discover it — gives tools one known place to start instead of fanning out per query, making discovery, prioritization, and retrieval faster and more reliable. It doesn't replace DSs; it makes them easier to use.

> **Use case — secured project information (courtesy of Ryn Bennett).** Portfolio managers restrict PMR meeting notes, the only place comprehensive per-program risk metrics are discussed; MA PFML now requires Program Manager approval to share sprint metrics. These walls inhibit data democracy. Independently-vetted [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ) was created as a workaround.

## 2. Core components

### Data Sources (DSs)
The systems where knowledge is created, corrected, summarized, governed, and accessed. **All permanent writes happen in a DS** — new knowledge, corrections, human-verified summaries — and each DS remains authoritative for what it holds.

### Discovery Layer (DL)
A **computed layer derived from DSs** — a *logical role, not a single store*. What makes something DL is **purpose, not location**: it exists to make DS knowledge faster to find and reuse, and never holds primary knowledge authored for its own sake. Each piece is a **DL output**, and by **where it lives and who backs it up** every output is one of three:
- **A DL record** — most DL by volume: a summary, aggregation, index, categorization, prioritized pointer, retrieval hint, relationship map, dedup/canonical pointer, content-freshness/obsolescence signal, or propagated access-control hint, written into a DS and tagged with a `discovery-layer` marker. Still DL by role, but **stored as a DS record — the DS governs and backs it up** (so its durability is only as good as that DS's backup), with version-history revert as recovery. Born `ai-generated` and recomputable (rebuilt on demand); a person editing or verifying it makes that copy durable (`human-created`/`human-verified`).
- **The Catalog** — a directory mapping `type + subject → location` so tools know where each output lives (§3). Recomputable, so it's rebuilt rather than backed up.
- **Confirmation signals** — captured human trust that is no DS record and can't be derived from any DS. A *signed* signal: a person vouches a cited source was **right or wrong**, a negative vote carrying a reason (*bad retrieval* vs *wrong content*) and an optional free-text note (<u>Strategy</u> §3.1). The **one DL output DL must retain deliberately** — non-recomputable, so it lives in DL's own service-fronted store, and **that store is what DL backs up** (backup/retention mechanics in <u>Storage</u>).

### Tags that travel with a DL output
Realized via whatever the store supports (a column, a label, a page property) — no bespoke system.
- **Provenance/verification:** `ai-generated` (default), `human-created`, `human-verified`, `discovery-layer` — the marker also lets a skill recognize a DS-stored artifact as DL and register it in the Catalog automatically. A **DL-creation skill applies `discovery-layer` to the output it authors**; a human-authored saved synthesis (<u>Strategy</u> Level 4) is *not* tagged — it's a person's artifact, discoverable through its explicitly registered Catalog pointer.
- **Lifecycle/trust:** content freshness/staleness, obsolescence, trust/confirmation signal.
- **Classification:** entry type + subject (Catalog keys), category (also an ACL-mapping input).
- **Access control:** propagated ACL metadata (a *hint* only), sensitivity.

### Content-freshness signals
Derived hints about how current a piece of prepared material (or its underlying source) is, so a consumer can judge whether to trust it. They are *content* freshness — distinct from the **permission freshness** of <u>Access Control</u>, which tracks whether access has been revoked. Each is produced from a Catalog-schema column (§3):
- **Last-updated date** — the underlying source record's own modified timestamp ("source last edited 3 days ago" vs. "2 years ago").
- **Content-state drift** — the output was computed from one content state of the source, but the source has since changed; detected by comparing the content-state marker stored in `source_refs` against the live source's current marker (equality, not ordering).
- **A `current` / `stale` / `obsolete` tag** — the explicit `freshness` column.
- **Last-validated timestamp** — `last_validated_at`: when the skill last confirmed the pointer resolves and the sources are unchanged; a long-ago validation is itself a staleness flag.
- **Obsolescence** — the record has been superseded (a newer doc replaces it, a ticket is closed/resolved, a space is deprecated).
- **"Confirmed, but edited since"** — a cited source was confirmed accurate, but its content-state marker no longer matches the marker stored with the confirmation, so the prior trust no longer cleanly applies (<u>Strategy</u> §3.2).

## 3. The Catalog

DL's directory — a "yellow pages" you consult to find *where* an output lives (`type + subject → location`), then follow the pointer. It indexes DL's **topology** (where outputs live), not DS content, so a subject's pointers can migrate from one store to another by changing one row, with no agent change.

**Why it's needed:** DL deliberately spreads outputs across many stores. Without one known starting point, every tool would hard-code the topology or fan out and search every store on each query — the exact repetitive searching DL exists to eliminate. The Catalog gives consumers **one lookup** (returning one or more ranked pointers), decoupled from storage. It is what makes discovery *scale*, not a hard prerequisite for any single output: the system still works without it — a consumer falls back to skill routing or a bounded fan-out — so an un-registered output (e.g., a freshly saved answer) is still reachable, just not in one lookup. That is why <u>Strategy</u> can treat it as essential at scale yet optional for an individual saved answer.

**What qualifies for registration.** Registration is **per `(entry_type, subject)` key**, not per artifact. An output qualifies only when it is **externally addressable** (answers a stable key a *non-producer* would look up), **meant to be discovered** (not a producer's private intermediate), and **worth a stable pointer** (a durable address surviving re-derivation). The **producer decides**: a skill registers what its author designated; a saved synthesis (<u>Strategy</u> Level 4) only if the user opts in to registration as a step separate from saving the artifact. The rule: *register a reusable answer, keyed by a stable `(entry_type, subject)`, that consumers beyond the producer should discover.*

**Granularity — top-level entry, not every sub-location.** A row points at the **entry point** for a subject — typically a top-level summary or landing output — not at every finer-grained piece beneath it. When the answer to a specific question lives in material *within* that entry (a section, a child page, a sub-record), reaching it is the **Query skill's** navigation job, not a separate Catalog row: the skill carries the question-type know-how for where such detail sits (<u>Strategy</u> §1.3). This keeps the Catalog small and stable — a small, stable set of top-level pointers per subject — instead of bloating it with sub-rows that drift as a source reorganizes.

It is the one un-pointed-to artifact, so it lives at a **well-known address** agents know a priori — a **service-fronted store (a database) reached through the same MCP interface agents use for the Data Sources**. Because it's the single entry point everyone hits first, **all writes go through a DL-creation skill's service account** — autonomously for rows it computes, under a verified human assertion for human-created rows; no one edits rows directly. Reads stay open. Consumers treat a **missing or malformed row as a cache miss** — fall back to skill routing or a bounded fan-out rather than erroring.

**A database from the start.** The Catalog lives in a service-fronted store — **Postgres (or any indexed DB)**, reached through MCP — so consumers do one `(entry_type, subject)` lookup at any scale. Keyed lookup is the floor; an implementation **may** add partial or fuzzy matching on the keys (e.g., `subject ILIKE`, trigram index) when it helps consumers place a question — the store choice doesn't constrain this. See <u>Storage</u>.

### Catalog schema

The columns of the service-fronted store:

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
| `source_refs` | text[] / JSON | DS records this output derived from — each entry carries a `source_state` content-state marker (a native change signal or a content hash, per source). **Powers staleness checks and re-derivation.** |
| `last_computed_at` / `last_validated_at` | timestamp | When last (re)derived; when the pointer/sources were last confirmed. |
| `access_groups` | text[] | Propagated ACL **hint** — the output's single assigned audience group. *Never trusted for enforcement.* |
| `sensitivity` | enum | `restricted` (default) \| `cleared`. |
| `category` | text (nullable) | Descriptive classification; also an ACL-mapping input (<u>Access Control</u>). |
| `computed_by` | text | The skill that owns this row. |
| `row_provenance` | enum | `skill` \| `human` — which writer owns the row, so the skill knows what it may re-derive vs. leave alone. |

**Keys.** `(entry_type, subject)` is the lookup key — extend to `(…, category)` for per-category variants. A key may resolve to **several rows**: one subject has rows across `entry_type`s, and a single `(entry_type, subject)` may hold **more than one pointer** when independent producers register duplicates (e.g., two saved syntheses on the same key). A lookup returns **all matching rows, ranked** on what the Catalog holds — `human-verified` over `unverified`, fresher over staler — so the top row is the default entry point and a simple consumer still gets one-lookup behavior while a consumer that cares sees the alternatives. Confirmation-based boost/demotion is layered on by the **consumer (the Query skill)**, which reads confirmation signals live at present-time, not by the Catalog itself. A skill still keeps **one row per `(entry_type, subject, computed_by)`** that it updates in place on re-derivation (§5), so duplicates arise from human saves, not skill churn. Index `access_groups` (GIN in Postgres) for query-time filtering.

**Notes.** The `created_at`/`updated_at`/`updated_by` columns carry attribution and the audit trail, since the service-fronted store is non-versioned. `access_groups` is a hint, not a gate. `source_refs` is load-bearing: dangling-pointer detection and re-derivation both depend on it. `row_provenance`/`computed_by` let the skill re-derive only the rows it owns and leave human-created rows to revert-based recovery.

### Dangling-pointer resilience

A `location` can break: a DS page is deleted, a dataset is dropped, a doc is moved, or a space is reorganized. Then the pointer resolves to nothing. Three layers handle this — detection, recovery, and graceful consumer behavior — and none needs a new always-on service.

**Detection — reconciliation folded into existing runs.** Pointer checking rides on the scheduled skill runs that already maintain the Catalog (§5), not a separate watchdog. Each run, a skill confirms that the `location` of every row it owns still resolves, then stamps `last_validated_at`. `source_refs` makes this cheap: comparing the stored content-state marker against the live source catches both a **vanished** target (the pointer fails) and a **drifted** one (the live marker no longer matches the one the output was built from). To close the edges per-skill runs miss — rows whose owning skill no longer runs, and human-owned rows nobody re-derives — one **owner-agnostic reconciliation pass** (itself just a skill) periodically reads every row's `location` to confirm it's reachable and updates `freshness` / `last_validated_at`. It only checks reachability; it never rewrites content.

**Recovery — by who owns the row.**
- **Skill-owned rows (`row_provenance = 'skill'`):** the owning skill re-derives — recompute the output, write it to its (possibly new) location, update the row. If the underlying source is itself gone (not merely moved), the output is no longer derivable, so the row is dropped or marked `obsolete` and consumers stop trusting it.
- **Human-owned rows (`row_provenance = 'human'`):** can't be recomputed. The reconciliation pass flags the row `obsolete` and surfaces it to its owner; recovery is the same revert-based path as any human-authored output. A human row is never silently deleted.

**Graceful degradation — a broken pointer never errors.** A consumer that follows a pointer to nothing treats it exactly like a missing row: a **cache miss**. It falls back to the Query skill's routing or a bounded fan-out and still returns an answer — a dangling pointer costs that one query some latency, never correctness. This is the point of the Catalog being a cache, not a system of record: the DSs stay authoritative, so any stale or broken pointer is always recoverable by going to the source.

## 4. Data flows

```
DSs → DL-creation skill (one of many, per source/team) → DL (Catalog + chosen store, via MCP)
AI tools → Query skill (one of many, per topic) → known DL output directly, else read Catalog → follow pointers
Saved synthesis → user writes artifact (own SSO); if the user separately opts to register → service account writes the Catalog pointer (human-owned row)
Confirmations → service-fronted store (via MCP)
Durable updates → DSs
```

- **Creation & governance** — knowledge created/corrected/summarized in DSs; access via Google SSO + Groups (see <u>Access Control</u>).
- **DL population & refresh** — AI-assisted content via scheduled/manual skills that compute outputs, write each to its store via MCP, register locations in the Catalog, and run staleness checks on referenced DS content *and* their own pointers.
- **Saved synthesis** — when a user persists a synthesized answer (<u>Strategy</u> Level 4), the user authors the artifact under their own SSO. **Registration is a separate opt-in**, not part of the save: only if the user chooses to promote the artifact to one-lookup discovery does a service account write a Catalog pointer with the user as `created_by` and `row_provenance = 'human'`. Either way the artifact itself is a **DS record** (human-saved), **not a DL record** — only the optional Catalog pointer is a DL output. It carries no `discovery-layer` tag (that marks skill output) and no skill re-derives it. Unregistered, it stays reachable by skill routing or fan-out.
- **Query & retrieval** — AI tools query DSs and DL via MCP under a verified SSO token, guided by one of many topic-specialized query skills. A skill that knows where its topic lives points straight there, skipping the Catalog; otherwise the agent reads the Catalog, then follows pointers.
- **Feedback & source updates** — users vouch whether a cited source was right or wrong (a signed, attributed, revertible signal); a *wrong content* negative vote also routes to the §6 correction path. At query time a flagged source is demoted with its reason shown, never hidden. Permanent updates always go to DSs.

## 5. Update mechanisms

All updates propagate/assign ACL metadata and register location in the Catalog.

**AI skills** do the interpretation-heavy work. A skill reads DS content (respecting ACLs), computes indexes/aggregations/categories, detects content freshness/obsolescence, runs staleness checks on sources *and* its own pointers, writes to a backing store via MCP, registers the Catalog entry, provenance-marks outputs, and rebuilds only content it still owns. **There are many such skills, not one** — each customized to the source it handles.

**Overwrite safety.** Before recomputing any output it owns, the skill checks the target's **version history and overwrites only if the last revision was its own service account**. If a person edited it since, the skill leaves it untouched — that edit transferred ownership, promoting the output to `human-verified`/`human-created` (recoverable only by restoring an earlier version). In non-versioned stores, the same check reads the `provenance`/`row_provenance` columns instead.

## 6. Write model

- **New data** → a DS (policy → Confluence/Drive; decision → ticket/page).
- **Corrections** → a DS (guide the user to fix the underlying record).
- **Human-verified summaries** → a DS (DL may index/point to them).
- **AI-generated artifacts in DSs** → computed, human-readable output stored where people read it; provenance-marked, registered in the Catalog, written under a clear identity. Marked as `ai-generated`. Unverified until a human reviews it, becoming a `human-verified` DL output under that person's identity.
- **Persisted synthesis** → a user-saved synthesis stored as a new `human-created` **DS record**, under the **user's own SSO**; durable, not recomputable, and **untagged** — no `discovery-layer` marker (reserved for skill output), so it's a DS record but **not a DL record**. The only DL output is the optional Catalog pointer to it (<u>Strategy</u>, Level 4).
- **Confirmations** → non-recomputable, signed (right/wrong) data; attributed; stored in the service-fronted store (via MCP), recovered by backup. A *wrong content* negative vote additionally drives a correction to the underlying DS record (the *new data*/*corrections* rows above), but the signal itself is never canonical knowledge.
- **The Catalog** → DL topology, written by the skill service account only; reads stay open.
- **DL writes** → only computed data, the Catalog, and confirmation signals. Never canonical new knowledge, human corrections, or human-verified summaries.

## 7. What an MCP service for a Data Source must provide

Every DS is reached through an **MCP service** — the one interface agents, skills, apps, and the Level 0 tools use to read and write it. Adding a new DS means standing up an MCP service that meets the requirements below. They are written to be **general to any DS**: a requirement pinned to one source's quirks (a Confluence page ID, a Jira field) would break on the next source, so each is stated in store-agnostic terms and realized with whatever the specific store supports.

### 7.1 Capabilities the service exposes

- **Search / find** — turn a request into candidate records. This is what a <u>Strategy</u> §1.3 Query skill calls to locate the right DS records, and what a §2 DL-creation skill calls to gather inputs. Keyed or text search is the floor; richer matching is optional per store.
- **Fetch by pointer** — resolve a `location` (plus optional `locator` for a sub-location) to the actual content. This powers citation resolution, the confirmation step that shows a user the exact source, and re-derivation.
- **Write** — create or update a record, following the fixed write model (§6): new knowledge, human-verified summaries, and provenance-marked DL artifacts go to the DS; corrections guide the user to the underlying record rather than overwriting silently.

### 7.2 Identity and permissions

- **Run under the caller's verified identity.** Every read and write happens on behalf of the signed-in user, via token verification and on-behalf-of exchange across the `agent → MCP → DS` hop (<u>Access Control</u>). The user only ever sees what they could see in the DS directly.
- **Lean on the DS's native permissions.** The MCP service adds **no separate enforcement layer** — the DS decides what each request returns. New data written through it inherits the DS's protections automatically.
- **Support a non-user service identity** for DL-creation skills (<u>Strategy</u> §2): a least-privilege, per-DS service principal with keyless, rotated, audit-logged credentials, distinct from the end-user SSO path.
- **Require a verifiable end-user assertion at the third-party boundary.** When a Level 0 tool is repointed at the service, reject service-credential-only requests — the service must always know *which person* it is acting for (<u>Access Control</u>).

### 7.3 Citation and freshness support

- **Return a structured, resolvable reference** for every record, in the shape the Catalog and confirmations already use: `store_kind + location + locator + source_state`. An answer that can't produce this can't be cited, and an uncited answer can't be confirmed (<u>Strategy</u> §1.3, §3.1).
- **Expose a content-state marker (`source_state`).** An opaque per-record signal — a native change signal where the DS offers one, otherwise a content hash — compared by **equality, not ordering**. It drives staleness/drift detection (§2) and "confirmed but edited since" (§3.1).
- **Expose a last-updated timestamp** for each record, so freshness signals (§2) and the confirmation step ("title + last-updated") have something to show.

### 7.4 Provenance and overwrite safety

- **Read and write the tags that travel with a DL output** (§2) — `discovery-layer`, provenance — using whatever the store supports (a column, a label, a page property); no bespoke tagging system.
- **Reveal who last wrote a record** — version-history author where the store is versioned, a provenance column where it isn't — so a skill can apply the overwrite-safety check (§5) and overwrite only its own prior output.

The Catalog's own store is reached through this **same MCP interface** (§3), so the contract above spans both the Data Sources and DL's service-fronted store.
