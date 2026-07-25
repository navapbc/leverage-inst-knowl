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
A **layer of prepared material derived from DSs** — a *logical role, not a single store*. What makes something DL is **purpose, not location, provenance, or content**: it exists to be a fast entry point into DS knowledge, not to be authored as knowledge for its own sake. It is *usually* derived, but a person may curate or edit an output; its safety rests on where it lives (source-governed, source-backed) and on citing what it points to, not on a rule that its content is purely derived. Each piece is a **DL output**, and by **where it lives and who backs it up** every output is one of three:
- **A DL record** — most DL by volume: a summary, aggregation, index, categorization, prioritized pointer, retrieval hint, relationship map, dedup/canonical pointer, content-freshness/obsolescence signal, or propagated access-control hint, written into a DS and tagged with a `discovery-layer` marker that flags its entry-point **role**. Still DL by role, but **stored as a DS record — the DS governs and backs it up** (so its durability is only as good as that DS's backup), with version-history revert as recovery. This is the **automatic-vs-hand-touched split within DL records**: born `ai-generated` and recomputable (rebuilt on demand); a person editing, verifying, or hand-authoring it makes that copy durable (`human-created`/`human-verified`) — even if it then carries original content, the role is unchanged.
- **The Catalog** — a directory mapping `type + subject → location` so tools know where each output lives (§3). Recomputable, so it's rebuilt rather than backed up.
- **Confirmation signals** — captured human trust that is no DS record and can't be derived from any DS. A *signed* signal: a person vouches a cited source was **right or wrong**, a negative vote carrying a reason (*bad retrieval* vs *wrong content*) and an optional free-text note (<u>Strategy</u> §3.1). The **one DL output DL must retain deliberately** — non-recomputable, so it lives in DL's own service-fronted store, and **that store is what DL backs up** (backup/retention mechanics in <u>Storage</u>).

### Tags that travel with a DL output
Realized via whatever the store supports (a column, a label, a page property) — no bespoke system.
- **Role:** the **DL-record marker** — canonically `discovery-layer` — a **role marker**, not a provenance one: it flags that a DS-stored artifact's purpose is to be a DL entry point, independent of who authored it. Treat it as a *concept with a recommended default value*: realized in whatever each store supports, and a producer may use a **declared per-source equivalent** (e.g., a `project-index` label) so long as the **Catalog-registration skill is configured with a deterministic, enumerable way to find those records** — discovery must never depend on guessing which tag means DL-record. The **DL-creation skill applies the marker**; the separate **registrar discovers marked records and registers them** (§3). A saved synthesis carries it only when the user marks it an entry point at save (<u>Strategy</u> Level 4).
- **Provenance/verification:** `ai-generated` (default), `human-created`, `human-verified` — the automatic-vs-hand-touched axis, orthogonal to the role tag: it governs durability and what a skill may re-derive, not whether the artifact is DL or whether its content is derived (a person can hand-author derived material).
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

DL's directory — a "yellow pages" you consult to find *where* an output lives (`type + subject → location`), then follow the pointer. It indexes DL's **topology** (where outputs live), not DS content, so a subject's pointers can migrate from one store to another by changing one row, with no agent change. Even a vector-DB implementation (below) that embeds text for semantic matching embeds only the **DL records' own derived text**, never raw Data-Source content — the Catalog never becomes a copy of the sources.

**Why it's needed:** DL deliberately spreads outputs across many stores. Without one known starting point, every tool would hard-code the topology or fan out and search every store on each query — the exact repetitive searching DL exists to eliminate. The Catalog gives consumers **one lookup** (returning one or more ranked pointers), decoupled from storage. It is what makes discovery *scale*, not a hard prerequisite for any single output: the system still works without it — a consumer falls back to skill routing or a bounded fan-out — so an un-registered output (e.g., a freshly saved answer) is still reachable, just not in one lookup. That is why <u>Strategy</u> can treat it as essential at scale yet optional for an individual saved answer.

**What qualifies for registration.** Registration is **keyed by `(entry_type, subject)`** — a key a non-producer looks up, not an artifact's address (one key may resolve to several rows, §3 Keys). An output qualifies only when it is **externally addressable**, **meant to be discovered** (not a producer's private intermediate), and **worth a stable pointer** (surviving re-derivation). The **producer designates** what qualifies via the record's tags; the **registrar registers** it — for a saved synthesis, only if the user opts in (<u>Strategy</u> Level 4). Only a **DL record** is registrable, so **the Catalog only ever indexes DL records**.

**Granularity — top-level entry, not every sub-location.** A row points at the **entry point** for a subject — typically a top-level summary or landing output — not at every finer-grained piece beneath it. When the answer to a specific question lives in material *within* that entry (a section, a child page, a sub-record), reaching it is the **Query skill's** navigation job, not a separate Catalog row: the skill carries the question-type know-how for where such detail sits (<u>Strategy</u> §1.3). This keeps the Catalog small and stable — a small, stable set of top-level pointers per subject — instead of bloating it with sub-rows that drift as a source reorganizes.

It is the one un-pointed-to artifact, so it lives at a **well-known address** agents know a priori — a **service-fronted store (a database) reached through the same MCP interface agents use for the Data Sources**. Because it's the single entry point everyone hits first, **all writes go through the Catalog-registration skill's service account** — autonomously for rows it registers from discovered records, under a verified human assertion for human-created rows; no one edits rows directly. Reads stay open. Consumers treat a **missing or malformed row as a cache miss** — fall back to skill routing or a bounded fan-out rather than erroring.

**A database from the start.** The Catalog lives in a service-fronted store — **Postgres, another indexed DB, or a vector DB** — reached through MCP, so consumers do one `(entry_type, subject)` lookup at any scale. **Keyed lookup is the guaranteed floor**; an implementation **may** add fuzzy or semantic matching on top — from `subject ILIKE` / trigram indexes up to a vector DB that embeds the DL records' text and retrieves by similarity — but never in place of the keyed floor. Semantic matching is **opt-in**, with its own guardrails (below). See <u>Storage</u>.

**Vector-DB Catalog (opt-in) — guardrails.** An implementation that embeds DL-record text to serve semantic matching must hold to all of the following, so the added power never erodes the Catalog's contract or its security model:
- **Keyed lookup stays the contract floor** — semantic search is additive; no consumer may assume it exists.
- **Embed DL-record text only** — the derived summaries/indexes, never raw Data-Source content, so the Catalog never becomes a copy of the sources (the index-based-copy custody risk of <u>Strategy</u> Level 0).
- **Filter by `access_groups` before ranking** — similarity runs only over rows the asker may see. A hit now surfaces record *text*, not just a pointer, so an unfiltered match is a content leak, not a mere misdirection.
- **Partition by sensitivity tier** — `restricted` and `cleared` vectors don't share an index; embeddings can leak the content they encode, so a mixed index inherits the sensitivity of the most restricted vector it holds.
- **Enforcement stays at the target store** — the Catalog remains advisory; a bad hit misdirects or reveals a snippet but never unlocks the actual record.
- **Re-embed on re-derivation** — an embedding is derived from a DL record's content-state; when that changes the vector is stale until refreshed, tracked like any freshness signal (§2).

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
| `computed_by` | text | The **producing** skill (content owner) — for provenance and to scope duplicates per producer. The row itself is written by the Catalog-registration skill. |
| `row_provenance` | enum | `skill` \| `human` — which writer owns the row, so the skill knows what it may re-derive vs. leave alone. |

**Keys.** `(entry_type, subject)` is the lookup key — extend to `(…, category)` for per-category variants. A key may resolve to **several rows**: one subject has rows across `entry_type`s, and a single `(entry_type, subject)` may hold **more than one pointer** when independent producers register duplicates (e.g., two saved syntheses on the same key). A lookup returns **all matching rows, ranked** on what the Catalog holds — `human-verified` over `unverified`, fresher over staler — so the top row is the default entry point and a simple consumer still gets one-lookup behavior while a consumer that cares sees the alternatives. When a vector-DB implementation ranks by **semantic similarity**, similarity is an *additional* input applied **after** the `access_groups` filter and layered on the deterministic `human-verified`/fresher ordering — it never bypasses that filter or replaces that ordering. Confirmation-based boost/demotion is layered on by the **consumer (the Query skill)**, which reads confirmation signals live at present-time, not by the Catalog itself. The registrar keeps **one row per `(entry_type, subject, computed_by)`** — `computed_by` identifying the *producer* — updated in place as that producer's record is re-derived (§5), so duplicates arise from independent producers or human saves, not registrar churn. Index `access_groups` (GIN in Postgres) for query-time filtering.

**Notes.** The `created_at`/`updated_at`/`updated_by` columns carry attribution and the audit trail, since the service-fronted store is non-versioned. `access_groups` is a hint, not a gate. `source_refs` is load-bearing: dangling-pointer detection and re-derivation both depend on it. `row_provenance`/`computed_by` let the skill re-derive only the rows it owns and leave human-created rows to revert-based recovery.

### Dangling-pointer resilience

A `location` can break: a DS page is deleted, a dataset is dropped, a doc is moved, or a space is reorganized. Then the pointer resolves to nothing. Three layers handle this — detection, recovery, and graceful consumer behavior — and none needs a new always-on service.

**Detection — the registrar's ongoing job.** Pointer checking is part of what the **Catalog-registration skill** already does when it maintains the Catalog (§5), not a separate watchdog. On each run it confirms that the `location` of every row still resolves, then stamps `last_validated_at`. `source_refs` makes this cheap: comparing the stored content-state marker against the live source catches both a **vanished** target (the pointer fails) and a **drifted** one (the live marker no longer matches the one the record was built from). Because one registrar owns the upkeep of *every* row, no separate owner-agnostic pass is needed — it validates reachability across the board; it never rewrites content.

**`stale` vs. `obsolete`.** These are different conditions, and the registrar picks between them from what its validation run sees:
- **`stale`** — the record still exists but has *drifted* (live `source_state` ≠ the stored one), or its pointer failed *transiently* (the source moved, or a 5xx/403 blip). Recoverable: a re-derivation brings it back to `current`. On an ambiguous failure the registrar defaults to `stale`, never `obsolete`, so a transient outage never purges valid DL.
- **`obsolete`** — the record is *no longer derivable or has been superseded*: the underlying source is confirmed **gone** (a 404-style permanent absence, not merely moved), or a newer doc replaces it / a ticket is closed-resolved / a space is deprecated (§2). Re-running won't fix it. (The exact transient-vs-permanent boundary — which error codes count as "gone" — is an open call: <u>Open Questions</u>.)

**Recovery — the registrar flags (per the rule above), the owner fixes.** The registrar never re-derives content; it flags the row and hands off:
- **Skill-produced rows (`row_provenance = 'skill'`):** surfaced to the **producing skill** (via `computed_by`), which re-derives out-of-band — recompute, re-tag at the possibly-new location — and the registrar picks up the refreshed record on its next scan.
- **Human-owned rows (`row_provenance = 'human'`):** surfaced to the owner instead; recovery is the revert-based path of any human-authored output, never a silent delete.

**Graceful degradation — a broken pointer never errors.** A consumer that follows a pointer to nothing treats it exactly like a missing row: a **cache miss**. It falls back to the Query skill's routing or a bounded fan-out and still returns an answer — a dangling pointer costs that one query some latency, never correctness. This is the point of the Catalog being a cache, not a system of record: the DSs stay authoritative, so any stale or broken pointer is always recoverable by going to the source.

## 4. Data flows

```
DSs → DL-creation skill (one of many, per source/team) → DL record (tagged `discovery-layer`, in a store, via MCP)
DL records → Catalog-registration skill (the registrar) → Catalog pointer (via MCP)
AI tools → Query skill (one of many, per topic) → known DL output directly, else read Catalog → follow pointers
Saved synthesis → user writes artifact (own SSO); if the user separately opts to register → service account writes the Catalog pointer (human-owned row)
Confirmations → service-fronted store (via MCP)
Durable updates → DSs
```

- **Creation & governance** — knowledge created/corrected/summarized in DSs; access via Google SSO + Groups (see <u>Access Control</u>).
- **DL population & cataloging** — DL-creation skills compute, write, and tag outputs (re-deriving when sources drift); the Catalog-registration skill then discovers the tagged records and registers and maintains their rows (§5).
- **Saved synthesis** — when a user persists a synthesized answer (<u>Strategy</u> Level 4), the user authors the artifact under their own SSO and, at save, marks whether it's a reusable **entry point** (acts as a `human-created` DL record, carrying the `discovery-layer` role tag) or a personal one-off (a **plain DS record**). **Purpose decides which, at save — not authorship, and not registration.** **Registration is a separate opt-in** that only changes discoverability: if the user opts in, a service account writes a Catalog pointer (user as `created_by`, `row_provenance = 'human'`) for one-lookup discovery; unregistered, the record is still reachable by skill routing or fan-out. No skill re-derives it in either case.
- **Query & retrieval** — AI tools query DSs and DL via MCP under a verified SSO token, guided by one of many topic-specialized query skills. A skill that knows where its topic lives points straight there, skipping the Catalog; otherwise the agent reads the Catalog, then follows pointers.
- **Feedback & source updates** — users vouch whether a cited source was right or wrong (a signed, attributed, revertible signal); a *wrong content* negative vote also routes to the §6 correction path. At query time a flagged source is demoted with its reason shown, never hidden. Permanent updates always go to DSs.

## 5. Update mechanisms

All updates propagate/assign ACL metadata; the Catalog-registration skill registers each record's location in the Catalog.

**DL-creation skills** do the interpretation-heavy work: read DS content (respecting ACLs), compute indexes/aggregations/categories, detect content freshness/obsolescence, write to a backing store via MCP, provenance-mark and tag outputs, and rebuild only content they still own. **There are many, not one** — each customized to the source it handles. The **Catalog-registration skill** then discovers those tagged records, registers them, and validates their pointers/freshness — it owns the Catalog **row**, not the content (flagging and hand-off per §3).

**Overwrite safety.** Before recomputing any output it owns, the **DL-creation skill** checks the target's **version history and overwrites only if the last revision was its own service account**. If a person edited it since, the skill leaves it untouched — that edit transferred ownership, promoting the output to `human-verified`/`human-created` (recoverable only by restoring an earlier version). In non-versioned stores, the same check reads the `provenance`/`row_provenance` columns instead.

## 6. Write model

- **New data** → a DS (policy → Confluence/Drive; decision → ticket/page).
- **Corrections** → a DS (guide the user to fix the underlying record).
- **Human-verified summaries** → a DS (DL may index/point to them).
- **AI-generated artifacts in DSs** → computed, human-readable output stored where people read it; provenance-marked and tagged, written under a clear identity, then registered in the Catalog by the Catalog-registration skill. Marked as `ai-generated`. Unverified until a human reviews it, becoming a `human-verified` DL output under that person's identity.
- **Persisted synthesis** → a user-saved `human-created` artifact under the **user's own SSO**; durable, not recomputable. It acts as a DL record or a plain DS record by the user's entry-point choice at save (<u>Strategy</u> Level 4). Written under the user's SSO, so it is **not** a service-account "DL write" (below).
- **Confirmations** → non-recomputable, signed (right/wrong) data; attributed; stored in the service-fronted store (via MCP), recovered by backup. A *wrong content* negative vote additionally drives a correction to the underlying DS record (the *new data*/*corrections* rows above), but the signal itself is never canonical knowledge.
- **The Catalog** → DL topology, written by the Catalog-registration skill's service account only; reads stay open.
- **DL writes** → the **service-account write path** into DL's own stores: only computed data, the Catalog, and confirmation signals. Never canonical new knowledge, human corrections, or human-verified summaries. (A user saving a synthesis writes under their *own SSO* into a DS — that is a DS write, not a DL write, even when the artifact then acts as a DL record.)

## 7. What an MCP service for a Data Source must provide

Every DS is reached through an **MCP service** — the one interface agents, skills, apps, and the Level 0 tools use to read and write it. Adding a new DS means standing up an MCP service that meets the requirements below. They are written to be **general to any DS**: a requirement pinned to one source's quirks (a Confluence page ID, a Jira field) would break on the next source, so each is stated in store-agnostic terms and realized with whatever the specific store supports.

### 7.1 Capabilities the service exposes

- **Search / find** — turn a request into candidate records. This is what a <u>Strategy</u> §1.3 Query skill calls to locate the right DS records, what a §2 DL-creation skill calls to gather inputs, and what the **Catalog-registration skill** calls to discover the DL-record-marked records to register. Keyed or text search is the floor; richer matching is optional per store, and **finding by the configured DL-record marker** (a label, tag, or property — canonically `discovery-layer`, §2) must be supported so the registrar can enumerate DL records without guessing.
- **Fetch by pointer** — resolve a `location` (plus optional `locator` for a sub-location) to the actual content. This powers citation resolution, the confirmation step that shows a user the exact source, re-derivation, and the registrar's pointer-validation.
- **Write** — create or update a record, following the fixed write model (§6): new knowledge, human-verified summaries, and provenance-marked DL artifacts go to the DS; corrections guide the user to the underlying record rather than overwriting silently.

### 7.2 Identity and permissions

- **Run under the caller's verified identity.** Every read and write happens on behalf of the signed-in user, via token verification and on-behalf-of exchange across the `agent → MCP → DS` hop (<u>Access Control</u>). The user only ever sees what they could see in the DS directly.
- **Lean on the DS's native permissions.** The MCP service adds **no separate enforcement layer** — the DS decides what each request returns. New data written through it inherits the DS's protections automatically.
- **Support a non-user service identity** for the DL-creation skills and the Catalog-registration skill (<u>Strategy</u> §2, Level 3-Catalog): a least-privilege service principal with keyless, rotated, audit-logged credentials, distinct from the end-user SSO path — per-DS for a creation skill, and (for the registrar) scoped to read tagged records and write the Catalog store.
- **Require a verifiable end-user assertion at the third-party boundary.** When a Level 0 tool is repointed at the service, reject service-credential-only requests — the service must always know *which person* it is acting for (<u>Access Control</u>).

### 7.3 Citation and freshness support

- **Return a structured, resolvable reference** for every record, in the shape the Catalog and confirmations already use: `store_kind + location + locator + source_state`. An answer that can't produce this can't be cited, and an uncited answer can't be confirmed (<u>Strategy</u> §1.3, §3.1).
- **Expose a content-state marker (`source_state`).** An opaque per-record signal — a native change signal where the DS offers one, otherwise a content hash — compared by **equality, not ordering**. It drives staleness/drift detection (§2) and "confirmed but edited since" (§3.1).
- **Expose a last-updated timestamp** for each record, so freshness signals (§2) and the confirmation step ("title + last-updated") have something to show.

### 7.4 Provenance and overwrite safety

- **Read and write the tags that travel with a DL output** (§2) — `discovery-layer`, provenance — using whatever the store supports (a column, a label, a page property); no bespoke tagging system.
- **Reveal who last wrote a record** — version-history author where the store is versioned, a provenance column where it isn't — so a skill can apply the overwrite-safety check (§5) and overwrite only its own prior output.

The Catalog's own store is reached through this **same MCP interface** (§3), so the contract above spans both the Data Sources and DL's service-fronted store.
