# Institutional Knowledge for AI Enablement — Implementation Strategy

**The problem.** Institutional knowledge is scattered across many systems. To answer a question, every AI agent, app, and person has to search all of them — repeatedly and redundantly. That is slow, token-expensive, inconsistent across tools, and prone to missing the trusted or current answer. We treat this as the strategy's **working hypothesis** — grounded so far in one concrete signal, the hand-built [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ) workaround for walled-off project information ([use case](lik-architecture-concise.md)), not a measured baseline — and **Level 0 is its first test**: if the pain is smaller than assumed, the gap backlog comes back thin and the strategy stops at buy. We want that knowledge reliably discoverable and retrievable for AI agents and people alike — *without* creating a second source of truth or copying everything into one place.

**Key terms.**
- **Data Sources (DSs)** — the systems where knowledge is actually created, corrected, and governed: Google Drive, Confluence, Jira, GitHub, Slack, Gmail, Salesforce, Workday, etc. They remain the **source of truth**; all durable writes happen here.
- **MCP** (Model Context Protocol) — the service interface through which agents and apps read and write DSs (and later DL) under a verified user identity.
- **Discovery Layer (DL)** — a lightweight, *computed* layer **derived from the DSs** (indexes, aggregations, freshness/confirmation signals, pointers) that makes discovery and retrieval faster. Its AI-generated outputs are never a second source of truth and are recomputable from the DSs at any time; the exceptions are durable, human-originated data — confirmation signals (§2.3) and human-verified/human-created artifacts — which live only in DL and recover by revert. Its data is **distributed across many stores** — a summary in a Confluence page, signals in a database, tables in a warehouse — wherever each output best belongs.
- **Catalog** — DL's "yellow pages": a single, **published, well-known location** (one address clients know in advance) mapping `type + subject → location`. Because DL is scattered, the catalog is **typically a client's first stop** — one lookup to find *where* any DL output lives, then follow the pointer, instead of searching every store.

Other acronyms used below:
- **ACL** (access control list) — the per-record permissions a system stores: who may read or write what.
- **SSO** (single sign-on) — one verified login across systems; here, **Google SSO** + **Google Groups** for role/permission grouping.
- **OIDC / OAuth** — the standard identity/authorization protocols that produce the verified token carrying the user's identity.
- **BI** (business intelligence) — operational dashboards and reporting (the Parallel Track).

**The strategy.** This is an implementation strategy for Leveraging Institutional Knowledge (LIK). It starts by *buying* (Level 0) to learn what's actually missing, then *builds* progressively (Levels 1–3) only where a bought tool falls short — with a parallel data-pipeline track. Each level adds one standalone capability and is justified by a limitation in the level before it. But standalone capability isn't standalone ROI: Levels 2–3 pay off only once Level 1 adoption shows the same questions recurring across many users — reuse is the value, so treat that recurrence as a precondition to check, not an assumption.

The strategy is deliberately evidence-driven: ship a layer, learn from it, and only spend on the next if the prior one proved the need. Every layer ends with a **limitation** — the reason the next one exists.

---

## Level 0 — Buy a commercial tool and learn

**Goal:** get immediate value and a measurable baseline by adopting an existing tool *before* building anything — and use the experience to decide what, if anything, is worth building.

Commercial enterprise-search / AI-retrieval products already connect to these DSs, enforce permissions, and provide AI retrieval out of the box. Buy one and run it for a few months:

- **Commercial apps** — Glean, GoSearch, SearchUnify.
- *Lower-cost variant:* self-hosted open-source platforms — Onyx CE, PipesHub, SWIRL — adopt (don't build) if data residency or budget rules out commercial apps.

**What we get beyond the tool itself:**
- A **working capability today**, with no build cost.
- A **baseline / yardstick** to measure any future build against — the honest comparison is "our build vs. this tool," not "our build vs. nothing."
- Most importantly, a **catalogued backlog of gaps**: specific **use cases**, each a `(data source, user question)` pair, where the bought tool does poorly — cross-source aggregations it can't compute, stale or untrusted answers, secured-but-discoverable content it can't reach, rankings it gets wrong. These gaps become the build backlog for the levels below.

**How to run it:** pick a pilot user group, connect a few high-value DSs, and have users log real questions and rate the answers. Track precisely *where* it fails — which data sources it can't reach, which questions come back wrong/stale/incomplete, which permissions it can't honor.

### Expected limitations of this layer

A turnkey tool is a black box — possible limitations include: you can't change its ranking, and you can't add cross-source aggregations or confirmation signals it doesn't natively support. Its **data-handling model** also matters and varies per tool — confirm it during evaluation, and wherever a data copy exists test third-party data-custody controls:

- *Index-based* (e.g., Glean, GoSearch) ingests/crawls sources into its own search index — a derived copy with source ACLs mirrored in, and a bulk re-export surface.
- *Federated / connector* (e.g., SearchUnify) queries sources at read time and doesn't persist a full copy.
- Many are *hybrid*.

The gaps catalogued here become the **build backlog** for Levels 1–3 — and if none are worth the cost, the strategy correctly stops at Level 0.

---

## Level 1 — Direct DS access via MCP

**Goal:** address Level 0's gaps by building our own agent that reads and writes institutional knowledge in the systems where it already lives, with access governed by Google SSO.

The **Data Sources (DSs)** — Google Drive, Confluence, Jira, GitHub, Slack, Gmail, Salesforce, Workday — stay the source of truth. Nothing is copied or pre-computed yet. Each DS is exposed through an **MCP service**, and the agent reads/writes through it.

### 1.1 Single agent, read-only

A local Claude Cowork-style agent connects to a few approved DSs via MCP and reads on the user's behalf.

- **Access control via Google SSO.** Each MCP service / AI connector requires a **verified Google OIDC/OAuth token** (audience-validated); the verified email *claim* authorizes the call. Identity is carried across every `agent → MCP → DS` hop via **on-behalf-of token exchange** — each MCP service exchanges the verified Google token for a DS-native token per source, since a DS won't accept a Google-audience token directly — so the agent can only ever see what the signed-in person can see. An email is an identifier, never a self-asserted authenticator. *(Each user grants per-DS OAuth consent once; the MCP service vaults and refreshes their per-DS tokens — the storage/refresh scheme is a planning-phase detail.)*
- **The DS enforces its own native permissions.** The connector authenticates to each DS as the signed-in user, and that DS applies its native ACLs directly — no separate enforcement layer to keep in sync, and no need to provision Google Groups for DL at this level. (Maintaining a Google Group that represents a shared output's audience — for sources not already group-based — only becomes necessary once DL produces shared outputs; see Level 2's access-control model.)

### 1.2 Read-write to DSs

The agent writes back under the **user's own SSO identity**, through each DS's normal permissions. The **write model** is deliberately narrow and stays fixed for all later levels:

- **New knowledge** → a DS (policy → Confluence/Drive; decision → ticket/page).
- **Corrections** → guide the user to fix the underlying record in its DS.
- **Human-verified summaries** → a DS.

Because access is enforced per-DS on every read and write, **new data inherits the right protections automatically** — a doc written into a restricted Drive folder is restricted; a ticket created in a private project stays private. No separate permission system to keep in sync.

### 1.3 Organization skills — encode *how* to answer

Even with read/write MCP access, a raw agent doesn't know the organization's retrieval conventions: which DS is authoritative for which question, what internal jargon to search for, which space holds the real answer. Capture that know-how once as a **skill** — a reusable set of instructions that guides the agent's behavior for certain question types — and share it as an **"organization skill" available to any employee**, so everyone's agent benefits from the same institutional know-how without each person rediscovering it.

A skill can direct the agent to, for example:

- **Query a particular DS first** for a given question type — e.g., policy questions → the Confluence policy space before anything else; HR/benefits → Workday; incident history → the Jira incident project and the `#incidents` Slack channel.
- **Search with specific terms** — expand internal acronyms and codenames (`PTO` → "paid time off"; project "Atlas" → its real ticket prefix), apply known synonyms, and prefer the org's canonical phrasing.
- **Scope the search** — restrict to certain folders, spaces, labels, or projects, and exclude known-noisy or deprecated locations.
- **Prefer authoritative sources** — name the documents/owners that are the source of truth for a topic, and rank them above ad-hoc mentions.
- **Follow a fallback chain** — if the primary DS yields nothing, try the next-best source in a defined order rather than fanning out blindly.
- **Shape the answer** — always cite source links, surface each source's last-updated date, and flag when the best match looks stale.
- **Route by entity** — map a team/client/project name to the systems and people that own it.

This is the cheapest, human-authored analog of what the Discovery Layer later automates: it encodes "where to look and how to ask" as shareable instructions instead of computed pointers. A skill is **maintained by a named owner**, **versioned**, and improved as the gap backlog from Level 0 reveals where agents go wrong.

Crucially, a skill is **guidance, not enforcement** — which is exactly why it's safe to share with everyone: it can only help an agent *find* answers faster, never widen access. Every query still runs under the user's own SSO identity (§1.1), so the DS's permissions — not the skill — decide what comes back. This means organization skills need no approval regime or governed-writer controls; a bad or stale skill can misdirect (send someone to the wrong place), but it can never leak data the user wasn't already entitled to. The corollary: never rely on a skill to *restrict* access — gating is always the DS's job.

### Broadening the data consumers

The MCP-to-DS path is not specific to one agent. The same services can back other clients — including the **commercial or self-hosted tools from Level 0**, repointed at our MCP services so they proxy the end-user's identity instead of relying solely on their own connectors (and, for index-based tools, their own copy of the data).

**Third-party trust boundary (inline hardening):** external tools are a distinct trust zone. For each one, define **credential scope** (least-privilege slice), **data minimization** (which DSs, not all), **retention/training constraints**, and **breach containment**. A tool querying under its own service credentials must faithfully proxy the end-user's identity so per-DS enforcement isn't bypassed — and this is **enforced, not assumed**: require a verifiable end-user assertion (a signed user token / OBO) alongside the tool's service credential, and **reject any request carrying only a service credential with no user identity**.

### Expected limitations of this level

Where no skill covers a question, a tool must **query each DS and fan out across all of them** on every request — slow, token-expensive, inconsistent across tools, and prone to dead ends.

Organization skills (§1.3) cut that blind fan-out for the questions they cover, but they don't remove the underlying problem — they only point the agent at the right place. The **residual limitations** that survive even a good skill are what motivate Level 2:

- **No reuse of computed results.** A skill says *where* to look, but the agent still performs the full retrieval and synthesis **live on every query** — the same work repeated, never cached as a reusable output.
- **Hand-authored guidance doesn't scale or compute.** A skill can route by question type, but it can't carry per-subject pointers for thousands of projects/clients, and it can't **precompute** aggregations, freshness, or trust signals — it can only direct, not derive.
- **Skills drift.** They are manually maintained, so they go stale as DSs change; there is still no shared, *computed* view of what exists or where it is.

---

## Level 2 — Discovery Layer computed outputs (no catalog yet)

**Goal:** stop re-searching the DSs from scratch by precomputing reusable **Discovery Layer (DL)** outputs derived from them — automating and scaling what the §1.3 organization skill did by hand (hand-authored "where to look" → *computed* pointers and *precomputed* outputs any tool can reuse).

**The identity shift from Level 1.** Where Level 1 ran under the **user's** SSO (the agent saw only that user's slice, enforced per-DS automatically), DL outputs are produced by a **DL skill** on a schedule or on demand under its **own non-user service identity** — never the triggering user's SSO. It reads exactly what that identity is granted (data shared with the account, or DSs where it's in the right Google Group), scoped **least-privilege per DS**; admitted across many sources, it reads inputs no single user could see and computes one shared output for everyone. That power is also its hardening burden — it assigns each output a sharing group (below), **default-deny** so a miss over-restricts rather than leaks. *(That single logical identity is realized as a per-DS service principal — a Slack bot, a Jira/Salesforce service account, a Workday ISU, a GCP service account — each granted least-privilege read. From this level on the skill authenticates with **keyless, rotated credentials** and audit-logged writes, scoped per-output-type where practical to bound a compromise; the store-level **governed-writer discipline** (§2.2) additionally attaches wherever a writer lands in a non-versioned store.)* *(Distinct from the §1.3 **organization skill**, shareable guidance that steers a user's agent at query time; the DL skill is the automated **producer**.)*

DL is **computed, never a second source of truth** — **AI-generated by default** (hand-authored artifacts are tagged `human-created`), mostly **recomputable** from the DSs, and tagged with whatever the store supports (provenance, freshness, classification, sharing group — no bespoke system). The scheduled re-derivation that recomputes an output also bounds how long it can outlive its source: a run that finds the source deleted or its access revoked drops or re-restricts the derived output, so "recomputable" never means "persists stale indefinitely." *(Hardening: DL inputs are untrusted — the skill treats DS content as data, not instructions, and an output's sharing group always comes from the skill's instructions, never inferred from input content, so injected text can't widen an audience.)* Each output is written to a **backing store** named in the skill's instructions: a Confluence page for things people read, or a dedicated store (a service-fronted database, a BigQuery warehouse) for machine signals. The choice turns on *who consumes it* (people → human-readable artifact; tools → machine signals) and *how much write integrity it needs* — and on one hard constraint: **any artifact the skill maintains over time must live in a store whose write connector can edit it in place.** The available connector for Google Drive can only create new files, never update them, so anything re-derived, upserted, or appended — the catalog, recomputed summaries, signal and confirmation tables — goes to an update-capable store (a **Confluence page** or a **service-fronted database**), not a Google Doc or Sheet. Access control is **uniform** across stores, described once next.

### Access control — share with a group, fail-closed

Every output the DL skill writes carries one of three sharing states:

1. **Shared with a specified Google Group** — the group that should see it.
2. **Explicitly unrestricted** — an affirmative flag the skill sets to open the output org-wide (the "cleared" case).
3. **Unspecified → default-deny** — shared only with a restricted fallback group, never open. Absence of a decision is never "open."

Enforcement is the **store's own native group/role grant** — there is no separate enforcement layer to keep in sync:

| Store | How a specified group is honored |
|---|---|
| **Google Drive / Docs / Sheets** | Native sharing to the Google Group — direct. |
| **Confluence** | Page/space restriction to a Confluence group **synced** from the Google Group (Atlassian Access / SCIM). *Prereq: Guard/SCIM group provisioning must be configured.* |
| **BigQuery** | IAM grants the Google Group a role on the dataset/table; authorized views and row-access policies for finer control — direct. |

*(Postgres isn't used at this level. If a later promotion needs it, prefer BigQuery — whose IAM honors Google Groups directly — and otherwise add a `Google Group → Postgres role` bridge or a fronting service that resolves the caller's groups into a row-level-security predicate.)*

Because each output is *either* one specified group *or* explicitly unrestricted, the skill **never computes a most-restrictive intersection** — the mosaic problem disappears. Two disciplines keep it correct: **one sensitivity tier per output** (one group unambiguously matches the audience — e.g., *project-X summary → project-X members*; blending tiers is a smell, split it), and the author **names that group in the instructions** (the skill doesn't choose at runtime). Where a source isn't already group-based (Slack, Jira, Salesforce, Workday), an admin must **provision a Google Group** mirroring the audience, else the output stays default-deny. A genuinely cross-tier output (e.g., a leadership digest blending two restricted projects) is served either by an **admin-provisioned audience group** whose membership *is* the intended union, or — absent a standing audience — by storing pointers and **recomputing at query time under the user's own SSO** so each viewer sees only their slice; the skill still never computes an intersection. *(Hardening: before writing, the skill asserts the named group is no broader than the audience of every input source it read; on failure the output stays default-deny rather than publishing.)* Sharing with a **live** group is a bonus — revocations propagate automatically (no per-user cache to go stale); the skill only re-runs when an output's correct group changes.

### 2.1 Human-readable artifacts

Summaries, digests, curated indexes → written into a **Confluence page** (updatable in place, so each re-derivation revises the same page rather than spawning a new file), shared per the model above and **provenance-marked `AI-generated`**. Read and write are both the DL skill's **service identity**, so the artifact is attributed to the skill, not a person — **unverified** until a person reviews it, then **`human-verified`** under that reviewer's identity. Version history supplies attribution, audit, and revert.

### 2.2 Machine retrieval signals

Indexes, prioritized pointers, retrieval hints, freshness/obsolescence signals are saved to a store chosen for scale (a small **service-fronted table** to start; BigQuery or Postgres later). Because these signals are updated in place as freshness changes — a write the create-only Google Drive connector can't do — they don't begin life in a Sheet. This is a storage-engine choice, not an architectural one; access control is the same group-share model above.

*Hardening (inline):* a signal store is **non-versioned** (Postgres/warehouse), so its writer runs under **governed-writer controls** — no long-lived keys (e.g., Workload Identity Federation), a rotation schedule, least privilege, and audit logging on all writes. If signals land in Postgres rather than BigQuery, it additionally needs the `group → role` bridge noted under access control above.

### 2.3 Confirmation signals

Users can confirm that a **DL output** or a **DS data** an AI built its response from is trustworthy -- confirming the underlying source of truth feeds the ranking signals of §2.2. These confirmations **originate in DL** from user feedback and exist in **no DS** — they are **durable DL-origin data**, the one part of DL that is *not* recomputable. **Revert is their only recovery.** This makes confirmation signals one of the strategy's few **irreversible commitments** — with human-created artifacts (Key terms), the places the otherwise stop-anytime, recomputable design takes on durable custodial data that needs its own backup/retention.

**Linking a signal to its data.** A confirmation attaches to data only if the response is traceable to it via the §1.3 "always cite source links" convention — the citation is the join key. That convention is guidance, not a guarantee, so the confirm path **rejects a confirmation whose citation doesn't resolve** rather than attaching it loosely. Each signal also records the **version of the confirmed data** as its own column (e.g., doc revision, ticket `updated_at`), so a later edit doesn't silently inherit trust the prior version earned.

**How a user confirms** — from explicit to implicit:
- **An affordance in the AI tool** — thumbs-up / "accurate," scoped per cited source rather than the whole answer (one response may cite several sources; only one was the good one).
- **Conversationally, to the agent** — in Claude Cowork there may be no button; the user just says "yes, that's right," and the agent records it by calling an **MCP confirm tool** (agent-native parity with the button).
- **A correction is a negative signal** — when a user fixes the underlying record (§1.2), capture that too; trust is two-sided.

Like all DL writes, a **service account writes the confirmation to the store** — users never get direct write access to the confirmation store. The **confirming user's verified identity is captured as an attributed field** (e.g., `confirmed_by`), and routing every write through the service lets it enforce validation, **rate-limiting / de-duplication** (so no one inflates a record's trust by confirming it repeatedly), and provenance at write time. Concretely: at most one confirmation per user per cited source-version, and a minimum count of distinct confirmers before trust affects ranking (§2.4). Read access follows the group-share model above.

- **Start as a Confluence-page table:** updatable in place (unlike a create-only Drive Sheet), so the service account appends and de-duplicates against the same page; page restrictions gate writers, SSO attributes each write, version history is the audit log, and revert recovers a bad write.
- **Promote** to a service-fronted store (e.g., Postgres + an app) when scale, untrusted writers, or high-stakes ranking demand hard write-time enforcement of rate-limiting and de-duplication, under the §2.2 governed-writer controls. Being **durable and non-recomputable**, confirmation signals also need their own **backup/retention** — unlike the rest of DL, they can't be rebuilt from the DSs.

### 2.4 Using confirmation signals at query time

The §2.3 table is just another §2.2 machine-retrieval signal: an **organization skill** (§1.3) triggered by a user's question can read it — joining on the DS-record or DL-output pointer the answer cites — and let accumulated trust shape the response. The skill runs under the **user's** SSO, so it only ever sees confirmations the group-share model already permits. How aggressively a skill leans on trust is the **skill author's choice**; the options below run from lightest-touch to most invasive.

- **A. Presentation only** (never changes what's retrieved) — annotate "confirmed accurate by N people" (or by a named expert, from `confirmed_by`), or flag "reported inaccurate on <date>" for a previously-corrected record. Safest; never hides data.
- **B. Version-aware** (exploits the confirmed-version column) — **staleness gating** (if the record changed since it was confirmed, downgrade/flag — "confirmed, but edited since") and **recency decay** (weight recent confirmations higher).
- **C. Ranking** (changes which data the answer uses) — **tie-breaker** (prefer the more-confirmed of similarly-relevant or conflicting candidates; least distorting), **rank boost** (relevance retrieves, trust reorders), or **threshold/filter** (aggressive — prefer soft demotion, since a hard filter can hide correct-but-unconfirmed data).
- **D. Audience weighting** (exploits `confirmed_by`) — weight confirmations from the asker's group or a topic's owners (§1.3) above a stranger's; adds query-time group-resolution cost.

**Choosing a strategy.** Start with **A + staleness gating (B)** — read-only, transparent, exploiting columns we already capture. Add the **tie-breaker (C)** once confirmation volume is trustworthy. Defer hard filters and audience weighting until the Level 0 gap backlog shows a question type that needs them. Whatever the choice, **trust advises, never gates**: a record the user is entitled to is never hidden by low trust, only ranked or annotated — gating stays the DS's job (§1.3).

### Expected limitations of this level

DL now deliberately **spreads outputs across many stores** — a Confluence page here, a database table there. To use them, every tool must hard-code that storage topology, or fan out and search every store — reintroducing the Level 1 problem one layer up. There is **no single known place to start**.

---

## Level 3 — The catalog (a Confluence page)

**Goal:** give every consumer **one lookup** to discover where any DL output lives, decoupled from storage decisions.

The catalog is DL's "yellow pages": a directory you consult to find *where* an output lives (`entry_type + subject → location`), then follow the pointer. It indexes DL's **topology**, not DS content, so a subject's pointers can migrate from one store to another (a Confluence page to a database) by changing one catalog row — with no change to any agent.

It is the one artifact nothing points *to*, so it lives at a **well-known address** agents know a priori; everything else is discovered through it.

**Implemented as a Confluence page — chosen for transparency and in-place editing.** A Confluence page can be **updated in place**, so each sync revises the same page at a stable address rather than spawning a new file; it gives native version history and SSO-attributed edits, syncs its restrictions from a Google Group, and lets anyone open it and read exactly what the catalog claims — and it sits alongside the source pages the catalog already indexes. It is treated as **just another DS artifact**, with one tightening: because it's the single entry point every consumer hits first, **write access is limited to the DL skill's service account and a small set of named catalog owners** — reads stay open for transparency, edits are attributed via SSO and logged by version history, and a bad edit is reverted. Consumers treat a **missing or malformed row as a cache miss** — fall back to the organization skill's routing (or a bounded fan-out) rather than erroring. Suits low-cardinality pointers (dozens to low-hundreds of subjects). The schema is in [lik-architecture-concise.md §2](lik-architecture-concise.md).

**How it's created and kept honest.** The **DL skill**, writing under its non-human service account (e.g., `summarizer@navapbc.com`), registers each computed output's location as it runs, appearing in version history like any editor. Because version history is *corrective, not preventive*, each run also **validates entries / dangling pointers and re-derives the rows it owns** (`row_provenance = 'skill'`), bounding any misdirection window; hand-authored rows it can't re-derive rely on revert.

*Hardening (inline):*
- **The catalog stores pointers, not permissions.** Real access is enforced at each target store's group grant (§2 access control), so a tampered or wrong catalog row can *misdirect* a lookup but can never *widen* access. That bounds the blast radius of a bad write; restricting writers to the skill account and named owners (above) then keeps the shared entry point from being broken or redirected by any editor.
- **Promotion.** When subject count or pointer volume outgrows a page, promote the *same logical schema* to **Postgres or any indexed DB** — consumers still do one `(entry_type, subject)` lookup. A catalog in a non-versioned store takes on the **governed-writer discipline** and adds its own audit columns (`created_at` / `updated_at` / `updated_by`), which the Confluence-page realization doesn't need. Because the catalog is the a-priori entry point, promotion must preserve its **well-known address**: consumers reach it through a stable alias/indirection, not the page's raw URL, so the backing store can change underneath without breaking any consumer.

**Result.** Tools have one known starting point instead of fanning out per query. This is the core of "data democracy": authorized users reach knowledge without knowing where any artifact physically lives.

**The organization skill now evolves.** What §1.3 did by hand — a maintained routing table of "for this question, look here" — the catalog now provides as computed, scalable data. So the skill stops hard-coding DS routing and instead simply directs the agent to **consult the catalog first**, then follow the pointer. The two become complementary: the skill routes the agent *to* the catalog and still shapes *how* it answers (citations, freshness, fallback), while the catalog authoritatively answers *where* each output lives.

---

## Parallel Track — Deterministic data pipeline & warehouse

**Goal:** serve operational reporting (BI dashboards) and scale DL's machine-retrieval signals, via the **same MCP interface** as everything else.

**This is not a fourth step — it's an independent track.** It builds on the same foundations as Levels 1–3 (MCP exposure, SSO, and — once it registers outputs — the catalog), but isn't gated on completing the levels in sequence: start it whenever the BI use case matters, provided the foundations it uses are already in place. Equally, Levels 1–3 stand on their own without it.

It is a **deterministic path** — no AI in the loop:

```
DSs → Deterministic Pipeline → Warehouse → BI Dashboards
```

- **Deterministic pipelines** handle known, repeatable transforms — dashboard tables, aggregations, metrics, reporting indexes, scheduled extracts — typically materialized in a **warehouse**. They assign each output a sharing group (the same fail-closed model as §2) and register their outputs in the catalog (Level 3), exactly like the DL skill does.
- **The warehouse is exposed via MCP like any other DS.** An agent or app queries it through the same `verified-SSO-token` path; the catalog points to warehouse tables (`store_kind = warehouse`, `bq://dataset.table`) just as it points to a Confluence page. To consumers, the warehouse is simply one more discoverable store.
- The warehouse is also **one option for DL's machine-retrieval backing store at scale** — the natural promotion target from §2.2 when signal volume is large. It is *one possibility*, not a requirement of the architecture.

*Hardening (inline):* the warehouse is a non-versioned store, so its writers (pipelines and any DL-signal promotion landing here) run under the **governed-writer controls** — no long-lived keys, rotation, least privilege, audit logging. A BigQuery warehouse honors a Google Group via IAM directly; an admin only has to provision a Group for an audience whose source DS isn't already group-based.

Because it's a parallel track, it can be deferred entirely, or pulled forward ahead of Level 3 if reporting is the more urgent need.

---

## Artifacts at a glance

Every artifact the strategy creates, where it lives, who writes it, and how it's used.

- **DS records** — new knowledge, corrections, human-verified summaries (§1.2)
  - *Resides in:* the relevant Data Source (Confluence, Drive, Jira, GitHub, Slack, etc.)
  - *Written by:* the user's agent, under the **user's own SSO**
  - *Read/used by:* anyone with DS permission, via MCP
  - *Durability:* the **source of truth** — durable; everything else derives from it
  - *Access control:* the DS's own native ACLs; new data inherits its location's protections automatically

- **Organization skill** (§1.3) — shareable "where to look and how to ask" guidance
  - *Resides in:* a shared skill library, available to any employee
  - *Written by:* a **named human owner**; versioned
  - *Read/used by:* every employee's agent, at query time
  - *Durability:* durable, hand-authored
  - *Access control:* none needed — it's guidance, not enforcement, and can never widen access

- **DL skill** (§2) — the automated *producer* of Discovery Layer outputs
  - *Resides in:* runs under its **own non-user service identity** (per-DS service principals)
  - *Written by:* developers / skill authors
  - *Read/used by:* n/a — it's the engine that writes the DL outputs below
  - *Durability:* code; durable
  - *Access control:* keyless rotated credentials, least-privilege per DS, audit-logged writes

- **Human-readable artifacts** *(Discovery Layer output)* (§2.1) — summaries, digests, curated indexes
  - *Resides in:* a Confluence page (updatable in place, so re-derivation revises the same page)
  - *Written by:* the DL skill's **service identity** (tagged `AI-generated`); promoted to `human-verified` under a reviewer's identity
  - *Read/used by:* people in the sharing group
  - *Durability:* **recomputable** until human-verified; human-verified / `human-created` are durable
  - *Access control:* group-share, fail-closed; native store grant (Drive sharing, Confluence restriction)

- **Machine retrieval signals** *(Discovery Layer output)* (§2.2) — indexes, pointers, retrieval/freshness/obsolescence hints
  - *Resides in:* a small service-fronted table → BigQuery / Postgres (at scale) — updated in place, so never a Drive-connector Sheet
  - *Written by:* the DL skill's **service identity** (governed-writer controls in non-versioned stores)
  - *Read/used by:* tools/agents (via organization skills) at query time
  - *Durability:* **recomputable** from the DSs
  - *Access control:* group-share, fail-closed; store-native group/role grant

- **Confirmation signals** *(Discovery Layer output)* (§2.3) — user trust and correction feedback
  - *Resides in:* a Confluence-page table (updatable in place, free version-history revert) → a service-fronted store (Postgres + app) at scale
  - *Written by:* a **service account** (the confirming user captured as `confirmed_by`); rate-limited / de-duped at write
  - *Read/used by:* organization skills at query time, to shape ranking (§2.4)
  - *Durability:* **durable, NOT recomputable** — revert is the only recovery; needs its own backup/retention
  - *Access control:* group-share for reads; users never get direct write access

- **Catalog** *(Discovery Layer output — the index over the others)* (Level 3) — the "yellow pages" mapping `type + subject → location`
  - *Resides in:* a **Confluence page at a well-known address** (updated in place, stable address) → Postgres / indexed DB at scale
  - *Written by:* the DL skill's **service account** (e.g., `summarizer@navapbc.com`) + a small set of **named catalog owners**
  - *Read/used by:* **every consumer** — the first stop to find where any DL output lives
  - *Durability:* skill-owned rows re-derived each run; hand-authored rows rely on revert
  - *Access control:* reads open for transparency; writes limited to the skill account + named owners

- **Warehouse tables / BI outputs** (Parallel Track) — deterministic reporting, no AI in the loop
  - *Resides in:* a warehouse (e.g., BigQuery)
  - *Written by:* **deterministic pipelines** (governed-writer controls)
  - *Read/used by:* BI dashboards; agents/apps via MCP; also a promotion target for §2.2 signals
  - *Durability:* **recomputable** (deterministic)
  - *Access control:* the same fail-closed group model; BigQuery IAM honors Google Groups directly

## Coverage check

Every element of [lik-architecture-concise.md](lik-architecture-concise.md) lands in a layer:

| Concept | Layer |
|---|---|
| Build-vs-buy, commercial apps, bought-tool baseline, gap backlog | 0 |
| Self-hosted platforms | 0 (adopt) / 1.3 (consume our MCP) |
| Third-party trust boundary | 0 / 1.3 |
| DSs as source of truth, MCP exposure | 1 |
| Google SSO + Groups, identity rules, native per-DS enforcement | 1.1 |
| Write model (new / corrections / verified summaries) | 1.2 |
| DL computed outputs, tags, recomputable-vs-durable | 2 |
| DL skill (privileged reader, group assignment, provenance marking) | 2 |
| Access control: group-share, fail-closed default, store→group/role table (mosaic dissolved via one-tier-per-output) | 2 (Access control) |
| Provision/maintain a Google Group for audiences whose source isn't group-based | 2 (Access control) / Parallel Track |
| Human-readable artifacts | 2.1 |
| Machine retrieval signals | 2.2 |
| Confirmation signals (durable DL-origin) | 2.3 |
| Consuming confirmation signals at query time (annotation / staleness / ranking) | 2.4 |
| The catalog, schema, DL skill (non-human account), validate/re-derive | 3 |
| Store promotion (page/table → DB), governed-writer controls | 2.2 / 3 / Parallel Track (inline) |
| Deterministic pipeline, warehouse, BI dashboards | Parallel Track |

## Why this strategy

Each layer is an **evidence-driven bet**, and the order is chosen so each one's spend is justified by evidence from the layer before it:

- **Level 0** establishes whether a bought tool is already good enough, and — win or lose — yields the gap backlog that justifies any build at all. This operationalizes the build-vs-buy open question and the front-loaded build-vs-buy experiment from [lik-architecture-concise.md §11](lik-architecture-concise.md): buy first, A/B against the bought baseline, build only the gaps.
- **Level 1** proves SSO-gated MCP access is enough for real work.
- **Level 2** proves precomputed outputs beat fan-out search.
- **Level 3** proves a single transparent catalog beats per-store lookups.
- The **deterministic pipeline** runs as a parallel track, adding reporting whenever BI demands it.

Ship one, learn, then spend on the next — rather than committing to the full system up front.
