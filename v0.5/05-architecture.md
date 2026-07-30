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
- **The Catalog** — a directory mapping `type + subject → location` so tools know where each output lives (§3). A **mix**: skill-registered rows are recomputable, rebuilt rather than backed up; the human-owned rows a person registers can't be regenerated and are backed up (§3, <u>Storage</u>), so the Catalog as a whole is not safe to drop and rebuild.
- **Confirmation signals** — captured human trust that is no DS record and can't be derived from any DS. A *signed* signal: a person vouches a cited source was **right or wrong**, a negative vote carrying a reason (*bad retrieval* vs *wrong content*) and an optional free-text note (<u>Strategy</u> §3.1). **Non-recomputable, so DL must retain it deliberately** — it lives in DL's own service-fronted store, which DL backs up alongside the human-owned Catalog rows that likewise can't be regenerated (backup/retention mechanics in <u>Storage</u>). A confirmation is the stronger case: unlike a human Catalog row, whose target artifact still lives in a Data Source, it has no copy in any DS at all.

### Tags that travel with a DL output
Realized via whatever the store supports (a column, a label, a page property) — no bespoke system.
- **Role:** the **DL-record marker** — canonically `discovery-layer` — a **role marker**, not a provenance one: it flags that a DS-stored artifact's purpose is to be a DL entry point, independent of who authored it. Treat it as a *concept with a recommended default value*: realized in whatever each store supports, and a producer may use a **declared per-source equivalent** (e.g., a `project-index` label) so long as the **Catalog-registration skill is configured with a deterministic, enumerable way to find those records** — discovery must never depend on guessing which tag means DL-record. The **DL-creation skill applies the marker**; the separate **registrar discovers marked records and registers them** (§3). Because discovery works by *enumerating* marked records, the marker is **required on the skill path**. It is **optional on the manual (human) registration path** (§3): there a person registers a designated artifact directly, so the Catalog row itself carries the entry-point role, no marker need be written to the source, and the person needn't have write access to tag it. A saved synthesis carries the marker only when the user marks it an entry point at save (<u>Strategy</u> Level 4).
- **Provenance & verification** — two orthogonal signals, both governing durability and what a skill may re-derive (orthogonal to the role tag, and not about whether content is *derived* — a person can hand-author derived material):
  - **`provenance`** (`ai-generated` default \| `human-created`) — *who produced the content.* A born-`ai-generated` output is recomputable; hand-authoring makes it `human-created` and durable.
  - **`verification`** (`unverified` default \| `human-verified`) — *whether a human vouched for it.* Kept **separate** from `provenance` because a human can take ownership by **approving** an output without changing a byte, leaving `provenance` at `ai-generated`. A skill may **autonomously recompute** an output only when it is still `ai-generated` **and** `unverified`; either flip — an edit (→ `human-created`) or a review (→ `human-verified`) — transfers ownership, after which the skill may **propose** a refresh but never overwrites autonomously — the owner makes the final write. Verification needs its own signal precisely because a review leaves content unchanged, so content-diffing alone would miss it. **`verification` also has a second job, beyond overwrite safety: it is a lookup-time ranking key read by *consumers*.** A Catalog lookup returns every row on a key ranked `human-verified` above `unverified` (§3 Keys), so verification decides which pointer is the default entry point — not only what a skill may recompute. This is why the manual path captures it at registration: it sets whether a human-registered pointer wins its key.
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

**What qualifies for registration.** Registration is **keyed by `(entry_type, subject)`** — a key a non-producer looks up, not an artifact's address (one key may resolve to several rows, §3 Keys). An output qualifies only when it is **externally addressable**, **meant to be discovered** (not a producer's private intermediate), and **worth a stable pointer** (surviving re-derivation). Registration reaches the Catalog by **two non-exclusive paths**: the **skill path**, where the **producer designates** what qualifies via the record's tags and the **registrar** discovers and registers it; and the **manual (human) path**, where a **person designates an existing artifact and registers it directly** — for a saved synthesis or any pre-existing record, only if the user opts in (<u>Strategy</u> Level 4). Only a **DL record** is registrable, so **the Catalog only ever indexes DL records**: the skill path lists records a producer marked; the manual path *makes* the designated artifact a DL record by registering it as an entry point, its role recorded on the row rather than requiring a marker on the source. Not writing that marker gives up two things, both acceptable: someone browsing the source directly won't see an entry-point marker on the artifact (the role is visible only via the Catalog — which is the entry point everyone hits first anyway), and no producer skill will later "adopt" the artifact for auto-maintenance (moot, since human-owned rows are never re-derived — §3 dangling-pointer resilience).

**Granularity — top-level entry, not every sub-location.** A row points at the **entry point** for a subject — typically a top-level summary or landing output — not at every finer-grained piece beneath it. When the answer to a specific question lives in material *within* that entry (a section, a child page, a sub-record), reaching it is the **Query skill's** navigation job, not a separate Catalog row: the skill carries the question-type know-how for where such detail sits (<u>Strategy</u> §1.3). This keeps the Catalog small and stable — a small, stable set of top-level pointers per subject — instead of bloating it with sub-rows that drift as a source reorganizes.

It is the one un-pointed-to artifact, so it lives at a **well-known address** agents know a priori — a **service-fronted store (a database) reached through the same MCP interface agents use for the Data Sources**. Because it's the single entry point everyone hits first, **all writes go through the store's single governed writer** — autonomously for rows the registrar derives from discovered records, under a verified human assertion for human-created rows; no one edits rows directly. Reads stay open. Consumers treat a **missing or malformed row as a cache miss** — fall back to skill routing or a bounded fan-out rather than erroring.

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
| `computed_by` | text | The **producing** skill (content owner) — for provenance and to scope duplicates per producer. The row itself is written by the Catalog-registration skill. A **human-owned row has no producer**, so it records the ad-hoc registering skill's name — audit-only, since `row_provenance = 'human'` already excludes it from re-derivation and from the per-producer upsert key. |
| `row_provenance` | enum | `skill` \| `human` — which writer owns the row, so the skill knows what it may re-derive vs. leave alone. |
| `created_at` | timestamp | When the row was first written. |
| `updated_by` / `updated_at` | email / timestamp | Who wrote the row and when — the attribution and audit trail for this non-versioned store. It holds the **user's email for a human-owned row** (stamped server-side from their verified login) and the registrar for a skill row. Because a human row is insert-only and never re-derived, its writer is also its creator, so a separate `created_by` is unnecessary. |

**Keys.** `(entry_type, subject)` is the lookup key — extend to `(…, category)` for per-category variants. A key may resolve to **several rows**: one subject has rows across `entry_type`s, and a single `(entry_type, subject)` may hold **more than one pointer** when independent producers register duplicates (e.g., two saved syntheses on the same key). A lookup returns **all matching rows, ranked** on what the Catalog holds — `human-verified` over `unverified`, fresher over staler — so the top row is the default entry point and a simple consumer still gets one-lookup behavior while a consumer that cares sees the alternatives. When a vector-DB implementation ranks by **semantic similarity**, similarity is an *additional* input applied **after** the `access_groups` filter and layered on the deterministic `human-verified`/fresher ordering — it never bypasses that filter or replaces that ordering. Confirmation-based boost/demotion is layered on by the **consumer (the Query skill)**, which reads confirmation signals live at present-time, not by the Catalog itself. The registrar keeps **one row per `(entry_type, subject, computed_by)`** — `computed_by` identifying the *producer* — updated in place as that producer's record is re-derived (§5), so duplicates arise from independent producers or human saves, not registrar churn. Index `access_groups` (GIN in Postgres) for query-time filtering.

**Notes.** The `created_at`/`updated_at`/`updated_by` columns carry attribution and the audit trail, since the service-fronted store is non-versioned; `updated_by` is the attributed writer (the registering user for a human-owned row). `access_groups` is a hint, not a gate. `source_refs` is load-bearing: dangling-pointer detection and re-derivation both depend on it. `row_provenance`/`computed_by` let the skill re-derive only the rows it owns and leave human-created rows to revert-based recovery.

### Dangling-pointer resilience

A `location` can break: a DS page is deleted, a dataset is dropped, a doc is moved, or a space is reorganized. Then the pointer resolves to nothing. Three layers handle this — detection, recovery, and graceful consumer behavior — and none needs a new always-on service.

**Detection — the registrar's ongoing job.** Pointer checking is part of what the **Catalog-registration skill** already does when it maintains the Catalog (§5), not a separate watchdog. On each run it confirms that the `location` of every row still resolves, then stamps `last_validated_at`. `source_refs` makes this cheap: comparing the stored content-state marker against the live source catches both a **vanished** target (the pointer fails) and a **drifted** one (the live marker no longer matches the one the record was built from). Because one registrar owns the upkeep of *every* row, no separate owner-agnostic pass is needed — it validates reachability across the board; it never rewrites content.

**`stale` vs. `obsolete`.** These are different conditions, and the registrar picks between them from what its validation run sees:
- **`stale`** — the record still exists but has *drifted* (live `source_state` ≠ the stored one), or its pointer failed *transiently* (the source moved, or a 5xx/403 blip). Recoverable: a re-derivation brings it back to `current`. On an ambiguous failure the registrar defaults to `stale`, never `obsolete`, so a transient outage never purges valid DL.
- **`obsolete`** — the record is *no longer derivable or has been superseded*: the underlying source is confirmed **gone** (a 404-style permanent absence, not merely moved), or a newer doc replaces it / a ticket is closed-resolved / a space is deprecated (§2). Re-running won't fix it. (The exact transient-vs-permanent boundary — which error codes count as "gone" — is an open call: <u>Open Questions</u>.)

**Recovery — the registrar flags (per the rule above), the owner fixes.** The registrar never re-derives content; it flags the row and hands off:
- **Skill-produced rows (`row_provenance = 'skill'`):** surfaced to the **producing skill** (via `computed_by`), which re-derives out-of-band — recompute, re-tag at the possibly-new location — and the registrar picks up the refreshed record on its next scan.
- **Human-owned rows (`row_provenance = 'human'`):** surfaced to the owner instead; recovery is the revert-based path of any human-authored output, never a silent delete.

**Graceful degradation — a broken pointer never errors.** A consumer that follows a pointer to nothing treats it exactly like a missing row: a **cache miss**. It falls back to the Query skill's routing or a bounded fan-out and still returns an answer — a dangling pointer costs that one query some latency, never correctness. Skill-registered pointers are a **cache** — the DSs stay authoritative, so any stale or broken skill pointer is recoverable by re-derivation or by going to the source. Human-owned rows are the exception: non-recomputable, they are a small **system-of-record** slice recovered by backup/revert, not rebuild (§2) — which is why the Catalog as a whole is not safe to drop and rebuild. Either way a dangling pointer costs that one query some latency, never correctness.

## 4. Data flows

```
DSs → DL-creation skill (one of many, per source/team) → DL record (tagged `discovery-layer`, in a store, via MCP)
DL records → Catalog-registration skill (the registrar) → Catalog pointer (via MCP)
AI tools → Query skill (one of many, per topic) → known DL output directly, else read Catalog → follow pointers
Designated artifact (a saved synthesis, or any pre-existing record a person points at) → the person designates it an entry point; if they opt to register → the governed writer writes the Catalog pointer (human-owned row), optionally tagging the source
Confirmations → service-fronted store (via MCP)
Durable updates → DSs
```

- **Creation & governance** — knowledge created/corrected/summarized in DSs; access via Google SSO + Groups (see <u>Access Control</u>).
- **DL population & cataloging** — DL-creation skills compute, write, and tag outputs (re-deriving when sources drift); the Catalog-registration skill then discovers the tagged records and registers and maintains their rows (§5).
- **Saved synthesis** — when a user persists a synthesized answer (<u>Strategy</u> Level 4), the user authors the artifact under their own SSO and, at save, marks whether it's a reusable **entry point** (acts as a `human-created` DL record, carrying the `discovery-layer` role tag) or a personal one-off (a **plain DS record**). **Purpose decides which, at save — not authorship, and not registration.** **Registration is a separate opt-in** that only changes discoverability: if the user opts in, the governed writer writes a Catalog pointer (user attributed as the row's writer in `updated_by`, `row_provenance = 'human'`) for one-lookup discovery; unregistered, the record is still reachable by skill routing or fan-out. No skill re-derives it in either case.
- **Manual (human) registration** — the human-owned write path is not limited to an in-session synthesis: a person may **designate a pre-existing artifact** (a page, doc, or sheet they know is the best entry point for a topic) and register it directly. No discovery scan runs, so tagging the source is optional and the person needs only read access to it; the Catalog row carries the entry-point role and no skill re-derives it. `verification` is set from whether the person is vouching for the record or merely flagging a useful pointer — which also fixes its lookup ranking (§2–3). This is the manual counterpart to the registrar's skill path (<u>Strategy</u> Level 3-Catalog, Level 4); the two are non-exclusive.
- **Query & retrieval** — AI tools query DSs and DL via MCP under a verified SSO token, guided by one of many topic-specialized query skills. A skill that knows where its topic lives points straight there, skipping the Catalog; otherwise the agent reads the Catalog, then follows pointers.
- **Feedback & source updates** — users vouch whether a cited source was right or wrong (a signed, attributed, revertible signal); a *wrong content* negative vote also routes to the §6 correction path. At query time a flagged source is demoted with its reason shown, never hidden. Permanent updates always go to DSs.

## 5. Update mechanisms

All updates propagate/assign ACL metadata; the Catalog-registration skill registers each record's location in the Catalog.

**DL-creation skills** do the interpretation-heavy work: read DS content (respecting ACLs), compute indexes/aggregations/categories, detect content freshness/obsolescence, write to a backing store via MCP, provenance-mark and tag outputs, and rebuild only content they still own. **There are many, not one** — each customized to the source it handles. The **Catalog-registration skill** then discovers those tagged records, registers them, and validates their pointers/freshness — it owns the Catalog **row**, not the content (flagging and hand-off per §3).

**Overwrite safety.** Before recomputing any output it owns, the **DL-creation skill** must answer one question: *is this record still mine to overwrite, or did a human take it over?* A record is the skill's to recompute only if it is both **unchanged since the skill's own last write** *and* still **`unverified`** — two guards catching two different human interventions. Change detection (**not identity**) catches an **edit**, which also flips `provenance` to `human-created`; the separate **`verification`** flag catches a **review** — a human vouching for the output without changing a byte, invisible to content-diffing. Either one means a human took ownership, so the skill **never silently overwrites it** — it leaves the record untouched, or surfaces a proposed update for the owner to accept, reject, or reconcile; the human always makes the final write (the record stays `human-created`/`human-verified`, recoverable by restoring an earlier version). *How* the skill detects an intervening change is its **private mechanism** — comparing a recorded content-state marker, or, where a store attributes each revision, comparing the last editor against a dedicated writer identity. That writer identity is **one realization, not an architectural requirement**: nothing outside the skill depends on it, so the team owning DL creation may choose any mechanism that keeps the record's provenance state correct (<u>Open Questions</u>).

## 6. Write model

- **New data** → a DS (policy → Confluence/Drive; decision → ticket/page).
- **Corrections** → a DS (guide the user to fix the underlying record).
- **Human-verified summaries** → a DS (DL may index/point to them).
- **AI-generated artifacts in DSs** → computed, human-readable output stored where people read it; provenance-marked and tagged, written under a clear identity, then registered in the Catalog by the Catalog-registration skill. Marked as `ai-generated`. Unverified until a human reviews it, becoming a `human-verified` DL output under that person's identity.
- **Persisted synthesis** → a user-saved `human-created` artifact under the **user's own SSO**; durable, not recomputable. It acts as a DL record or a plain DS record by the user's entry-point choice at save (<u>Strategy</u> Level 4). It is a user *authoring* an artifact, not a skill *deriving* one, so it is a **DS write**, not a DL write (below).
- **Confirmations** → non-recomputable, signed (right/wrong) data; attributed; stored in the service-fronted store (via MCP), recovered by backup. A *wrong content* negative vote additionally drives a correction to the underlying DS record (the *new data*/*corrections* rows above), but the signal itself is never canonical knowledge.
- **The Catalog** → DL topology, written through the governed writer only (the registrar is its only Catalog writer); reads stay open.
- **DL writes** → writes of **derived, non-canonical data** into DL's own stores: computed outputs, the Catalog, and confirmation signals. Defined by **what** is written, not by who writes it. The Catalog and confirmation signals go through **the governed writer** (a required single identity); computed DL records are written under whatever credential their DL-creation skill runs under. Never canonical new knowledge, human corrections, or human-verified summaries — those are **DS writes** under a human's own SSO. (A user saving a synthesis writes under their own SSO into a DS — a DS write, not a DL write, even when the artifact then acts as a DL record. Conversely, a user who merely *triggers* a DL-creation run isn't authoring canonical knowledge, so its computed output is still a DL write.)

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

- **Read and write the tags that travel with a DL output** (§2) — `discovery-layer`, `provenance`, `verification` — using whatever the store supports (a column, a label, a page property); no bespoke tagging system.
- **Expose a change-detection signal** — enough for a skill to tell whether a record is **unchanged since its own last write**: a content-state marker (version, revision, or content hash), or the last-writer identity where the store attributes revisions. That signal, together with the `verification` tag, powers the §5 overwrite-safety check — the skill autonomously recomputes only a record it still owns (unchanged *and* still `unverified`); for one a human edited or verified it may propose an update but never overwrites it autonomously.

The Catalog's own store is reached through this **same MCP interface** (§3), so the contract above spans both the Data Sources and DL's service-fronted store.
