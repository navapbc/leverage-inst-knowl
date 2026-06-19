# Leveraging Institutional Knowledge — Implementation Strategy

**The problem.** Institutional knowledge is scattered across many systems. To answer a question, every AI agent, app, and person has to search all of them — repeatedly and redundantly. That is slow, token-expensive, inconsistent across tools, and prone to missing the trusted or current answer. We treat this as the strategy's **working hypothesis** — grounded so far in one concrete signal, the hand-built [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ) workaround for walled-off project information ([use case](lik-3-architecture-concise.md)), not a measured baseline — and **Level 0 is its first test**: if the pain is smaller than assumed, the gap backlog comes back thin and the strategy stops at buy. We want that knowledge reliably discoverable and retrievable for AI agents and people alike — *without* creating a second source of truth or copying everything into one place.

**Key terms.** The core concepts — **Data Sources (DSs)**, **Discovery Layer (DL)**, **Catalog**, the **DL-creation skill**, the **Query skill**, and **confirmation signals** — are defined in plain language in [lik-1-overview.md](lik-1-overview.md). One term used heavily below and not in that overview:
- **MCP** (Model Context Protocol) — the service interface through which agents and apps read and write DSs (and later DL) under a verified user identity.

**Progressive disclosure.** The Catalog and DL let an agent answer in cheap steps — Catalog → DL → DS → on-demand link-following — instead of loading everything at once. See [lik-1-overview.md](lik-1-overview.md#progressive-disclosure-answering-in-cheap-steps) for the four-step walkthrough.

**Storage.** Each DL output lands in one of a few backing stores. This doc names *which* store an output uses and the one-clause reason; *how* each store behaves — in-place vs. create-only writes, versioning, group enforcement, governed-writer controls — is the canonical reference in [lik-dl-storage.md](lik-dl-storage.md).

Other acronyms used below:
- **ACL** (access control list) — the per-record permissions a system stores: who may read or write what.
- **SSO** (single sign-on) — one verified login across systems; here, **Google SSO** + **Google Groups** for role/permission grouping.
- **OIDC / OAuth** — the standard identity/authorization protocols that produce the verified token carrying the user's identity.
- **BI** (business intelligence) — operational dashboards and reporting (the Parallel Track).

**The strategy.** This is an implementation strategy for Leveraging Institutional Knowledge (LIK). It starts by *buying* (Level 0) to learn what's actually missing, then *builds* progressively (Levels 1–4) only where a bought tool falls short — with a parallel data-pipeline track. Each level adds one standalone capability and is justified by a limitation in the level before it. But standalone capability isn't standalone ROI: Levels 2–3 pay off only once Level 1 adoption shows the same questions recurring across many users — reuse is the value, so treat that recurrence as a precondition to check, not an assumption.

The strategy is deliberately evidence-driven: ship a layer, learn from it, and only spend on the next if the prior one proved the need. Every layer ends with a **limitation** — the reason the next one exists.

---

## (Optional) Level 0 — Buy a commercial tool and learn

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

The gaps catalogued here become the **build backlog** for subsequent levels — and if none are worth the cost, the strategy correctly stops at Level 0.

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

### 1.3 Query skills — encode *how* to answer

Even with read/write MCP access, a raw agent doesn't know the organization's retrieval conventions: which DS is authoritative for which question, what internal jargon to search for, which space holds the real answer. Capture that know-how once as a **skill** — a reusable set of instructions that guides the agent's behavior for certain question types — and share it as an **"Query skill" available to any employee**, so everyone's agent benefits from the same institutional know-how without each person rediscovering it.

A skill can direct the agent to, for example:

- **Query a particular DS first** for a given question type — e.g., policy questions → the Confluence policy space before anything else; HR/benefits → Workday; incident history → the Jira incident project and the `#incidents` Slack channel.
- **Search with specific terms** — expand internal acronyms and codenames (`PTO` → "paid time off"; project "Atlas" → its real ticket prefix), apply known synonyms, and prefer the org's canonical phrasing.
- **Scope the search** — restrict to certain folders, spaces, labels, or projects, and exclude known-noisy or deprecated locations.
- **Prefer authoritative sources** — name the documents/owners that are the source of truth for a topic, and rank them above ad-hoc mentions.
- **Follow a fallback chain** — if the primary DS yields nothing, try the next-best source in a defined order rather than fanning out blindly.
- **Shape the answer** — always cite source links, surface each source's last-updated date, and flag when the best match looks stale.
- **Route by entity** — map a team/client/project name to the systems and people that own it.

This is the cheapest, human-authored analog of what the Discovery Layer later automates: it encodes "where to look and how to ask" as shareable instructions instead of computed pointers. A skill is **maintained by a named owner**, **versioned**, and improved as the gap backlog from Level 0 reveals where agents go wrong.

**Expect many Query skills, not one.** Each covers a topic, question type, or team/project/program — policy questions, incident history, a specific client's projects — with its own named owner. An agent selects the skill that matches the question; where none fits, it falls back to a broad search (later, the catalog). A skill scoped to a known topic can point straight at the right place without any general lookup step.

Crucially, a skill is **guidance, not enforcement** — which is exactly why it's safe to share with everyone: it can only help an agent *find* answers faster, never widen access. Every query still runs under the user's own SSO identity (§1.1), so the DS's permissions — not the skill — decide what comes back. This means Query skills need no approval regime or governed-writer controls; a bad or stale skill can misdirect (send someone to the wrong place), but it can never leak data the user wasn't already entitled to. The corollary: never rely on a skill to *restrict* access — gating is always the DS's job.

### Broadening the data consumers

The MCP-to-DS path is not specific to one agent. The same services can back other clients — including the **commercial or self-hosted tools from Level 0**, repointed at our MCP services so they proxy the end-user's identity instead of relying solely on their own connectors (and, for index-based tools, their own copy of the data).

**Third-party trust boundary (inline hardening):** external tools are a distinct trust zone. For each one, define **credential scope** (least-privilege slice), **data minimization** (which DSs, not all), **retention/training constraints**, and **breach containment**. A tool querying under its own service credentials must faithfully proxy the end-user's identity so per-DS enforcement isn't bypassed — and this is **enforced, not assumed**: require a verifiable end-user assertion (a signed user token / OBO) alongside the tool's service credential, and **reject any request carrying only a service credential with no user identity**.

### Expected limitations of this level

Where no skill covers a question, a tool must **query each DS and fan out across all of them** on every request — slow, token-expensive, inconsistent across tools, and prone to dead ends.

Query skills (§1.3) cut that blind fan-out for the questions they cover, but they don't remove the underlying problem — they only point the agent at the right place. The **residual limitations** that survive even a good skill are what motivate Level 2:

- **No reuse of computed results.** A skill says *where* to look, but the agent still performs the full retrieval and synthesis **live on every query** — the same work repeated, never cached as a reusable output.
- **Hand-authored guidance doesn't scale or compute.** A skill can route by question type, but it can't carry per-subject pointers for thousands of projects/clients, and it can't **precompute** aggregations, freshness, or trust signals — it can only direct, not derive.
- **Skills drift.** They are manually maintained, so they go stale as DSs change; there is still no shared, *computed* view of what exists or where it is.

---

## Level 2 — Discovery Layer computed outputs (no catalog yet)

**Goal:** stop re-searching the DSs from scratch by precomputing reusable **Discovery Layer (DL)** outputs derived from them — automating and scaling what the §1.3 Query skill did by hand (hand-authored "where to look" → *computed* pointers and *precomputed* outputs any tool can reuse).

Where Level 1 ran under the **user's** SSO, DL outputs are produced by a **DL-creation skill** under its **own non-user service identity** — never the triggering user's SSO. DL inputs are untrusted: the skill treats DS content as data, not instructions, and an output's sharing group always comes from the skill's instructions, never inferred from input content.

**DL output, not DS record — a distinction of role, not storage.** Every output below is *derived material whose purpose is reuse and discovery*: cataloged, ranked, and staleness-tracked, pointing at or distilling the DSs. It is never primary knowledge authored for its own sake — that stays a **DS record** (§1.2). The line is **role, not location**: a DL summary can sit in a Confluence page right beside the DS records it summarizes and still be DL, because it exists only to help find and reuse them. This holds for every output type that follows, including the human-authored ones (§2.2) and the Level 4 syntheses (§4.2).

### 2.1 The DL-creation skill

A DL-creation skill runs on a schedule or on demand, querying **one or more DSs** and producing outputs that can link to data across several of them. Its identity is realized as a per-DS service principal — a Slack bot, a Jira/Salesforce service account, a Workday ISU, a GCP service account — each granted **least-privilege read**; the skill may use several of these principals in a single run. It authenticates with **keyless, rotated credentials** and writes with audit logging, scoped per-output-type where practical to bound a compromise.

**Expect many DL-creation skills, not one.** A given skill is customized to the source data it handles — its type, location, and owning **team, project, or program** — so it can process and validate that source the way that team or program requires (their conventions, their quality bar, their sensitivity rules) and produce a **specific kind of output in a specific DS**. One skill might summarize a program's Confluence space into an index there; another might derive incident signals from Jira plus Slack. They share the disciplines below (service identity, least-privilege read, group assignment, provenance) but differ in what they read, how they validate it, and what they emit.

The scheduled re-derivation that recomputes an output also bounds how long it can outlive its source: a run that finds a source deleted or its access revoked drops or re-restricts the derived output, so "recomputable" never means "persists stale indefinitely."

*(Distinct from the §1.3 **Query skill**, which steers a user's agent at query time; the DL-creation skill is the automated **producer**.)*

### 2.2 Authorship and durability

Every DL output carries one of three authorship states:

| State | Written by | Durability |
|---|---|---|
| `AI-generated` | DL-creation skill | **Recomputable** from the DSs — the default |
| `human-verified` | A reviewer, under their own SSO | **Durable** — revert is the only recovery |
| `human-created` | A human author directly | **Durable** — revert is the only recovery |

A person reviewing an AI-generated output promotes it to `human-verified` under their own identity; version history records who verified it. Human-verified and human-created outputs are the one part of DL that can't be rebuilt from the DSs — they need their own backup/retention and are the reason "stop-anytime, recomputable" has exceptions.

### 2.3 Access control

Every output carries one of three sharing states:

1. **Shared with a specified Google Group** — the group that should see it.
2. **Explicitly unrestricted** — an affirmative flag the skill sets to open the output org-wide.
3. **Unspecified → default-deny** — shared only with a restricted fallback group. Absence of a decision is never "open."

Enforcement is the **store's own native group/role grant** — no separate layer to keep in sync. How each store honors a Google Group (Drive's direct sharing, Confluence's SCIM-synced restriction, Postgres's group→role bridge) is tabulated in **[lik-dl-storage.md](lik-dl-storage.md#how-a-google-group-is-honored-per-store)**; a BigQuery warehouse grants the group a role via IAM (Parallel Track).

Two disciplines keep this correct: **one sensitivity tier per output** (one group unambiguously matches the audience; blending tiers is a smell — split the output), and the author **names that group in the instructions** (the skill never chooses at runtime). Where a source isn't already group-based (Slack, Jira, Salesforce, Workday), an admin must provision a matching Google Group or the output stays default-deny. A genuinely cross-tier output is served by an admin-provisioned audience group, or — absent a standing audience — by storing pointers and recomputing at query time under the user's own SSO so each viewer sees only their slice. Before writing, the skill asserts the named group is no broader than the audience of every input it read; on failure the output stays default-deny.

### 2.4 Summaries & indexes

Summaries, digests, indexes → written into a **Confluence page**, which is updatable in place so each re-derivation revises the same page rather than spawning a new file. Authorship starts as `AI-generated` (§2.2); a reviewer promotes it to `human-verified` under their own SSO identity, with version history supplying attribution, audit, and revert.

Confluence is required here — not a Doc or Sheet — because the Google Drive connector can only create files, never update them in place; see [lik-dl-storage.md](lik-dl-storage.md#google-drive--docs--sheets).

### 2.5 Retrieval signals

Indexes, prioritized pointers, retrieval hints, freshness/obsolescence signals → saved to a **service-fronted table** to start; BigQuery or Postgres at scale. Like §2.4, signals are updated in place as freshness changes — a write the Google Drive connector can't do — so they don't begin life in a Sheet.

A signal store is non-versioned, so its writer runs under the [governed-writer controls](lik-dl-storage.md#governed-writer-controls). If signals land in [Postgres](lik-dl-storage.md#postgres-the-service-fronted-store), it additionally needs the group → role bridge — realized by the service in §2.6.

### 2.6 The service-fronted store — one MCP write/read path

The signal store (§2.5), the confirmation store (§3.1), and a promoted catalog (Level 3-Catalog) all become the **same thing** once they outgrow a Confluence page: a database we own, reached through an **MCP service** — the same interface agents already use for the DSs. That service *is* the "service-fronted store" / "Postgres + app" those sections name; treat it as **one component, not three**. To a consumer, reading a DL signal looks exactly like reading a DS.

**Scoped tools, never raw SQL.** The service exposes intent-named tools — e.g. `confirm_source`, `upsert_signal`, `register_catalog_entry` — each enforcing its own rules at the moment of writing. This is the whole reason a store graduates to a database: §3.1 promotes confirmations precisely to *hard-enforce* rate-limiting, de-duplication, and "reject a confirmation whose citation doesn't resolve." A generic `run_sql` or `upsert(table, row)` tool would hand that enforcement back to the caller and forfeit the reason for moving off the page. The validation lives in the tool.

**Two writer identities — a different shape than Level 1.** A Level 1 MCP proxies the *user's* identity through to a DS (§1.1 token exchange). This service instead writes under its **own service identity** to a store we own, in one of two modes:

- **Service-only** — retrieval signals and catalog rows, written by the DL-creation skill's service identity with no user in the loop.
- **Service + user assertion** — a confirmation is written by the service account but carries the confirming user's verified identity as `confirmed_by` (§3.1); the tool needs the user's token both to attribute the write and to rate-limit per person.

**What the service owns.** Centralizing the path puts three already-required disciplines in one place instead of scattering them (store mechanics in [lik-dl-storage.md](lik-dl-storage.md#postgres-the-service-fronted-store)):

- **Reads** resolve the caller's Google Groups into a row-level-security predicate — the `group → Postgres role` bridge — so the same service gates reads and writes under the §2 group-share model.
- **Governed-writer controls** on its database connection (§2.5).
- **Backup/retention** for the confirmation tables specifically — the durable, non-recomputable exception (§3.1); signals and catalog rows recover by re-derivation.

**Start as one service.** One service fronting all three output types, with separate database roles and tables per type to bound a compromise (§2.1). Split into separate services only if confirmations' write-enforcement later needs an isolation the others don't — don't start there.

### Expected limitations of this level

Level 2 leaves two open problems, each solvable independently:

- **No human trust signal.** DL's signals rank by what can be *derived* — freshness, provenance, co-occurrence, obsolescence — but nothing captures whether a person actually found an answer *correct*. Two answers can look equally fresh and well-sourced while one is right and one is wrong; computed signals can't tell them apart.
- **No single entry point.** DL outputs are deliberately scattered across many stores — a Confluence page here, a signal table there. Every tool must either hard-code that topology or fan out and search every store — reintroducing the Level 1 problem one layer up.

### After Level 2 — two independent extensions

Levels 3-Confirmations and 3-Catalog each address one of the two limitations above and have no dependency on each other — both require Level 2, neither requires the other. Build them in whichever order the gap backlog suggests matters most:

- **Level 3-Confirmations** adds the missing human trust signal.
- **Level 3-Catalog** adds the missing single entry point.

---

## Level 3-Confirmations — User confirmations

**Goal:** capture the one trust signal Level 2 can't compute — a person saying *"this answer was right"* (or wrong) — and feed it back into retrieval. These confirmations are produced by people, not derived from the DSs, so they are the one part of DL that isn't recomputable.

### 3.1 Confirmation signals

Users can confirm that a **DL output** or a **DS data** an AI built its response from is trustworthy -- confirming the underlying source of truth feeds the ranking signals of §2.5. These confirmations **originate in DL** from user feedback and exist in **no DS** — they are **durable DL-origin data**, the one part of DL that is *not* recomputable. *(Confirming an answer that exists in **no** DL or DS yet is a different gesture — not a trust signal on existing data but a request to **create** one; that belongs to Level 4, see §4.1.)* **Revert is their only recovery.** This makes confirmation signals one of the strategy's few **irreversible commitments** — with human-created artifacts (Key terms), the places the otherwise stop-anytime, recomputable design takes on durable custodial data that needs its own backup/retention.

**Linking a signal to its data.** A confirmation attaches to data only if the response is traceable to it via the §1.3 "always cite source links" convention — the citation is the join key. That convention is guidance, not a guarantee, so the confirm path **rejects a confirmation whose citation doesn't resolve** rather than attaching it loosely. Each signal also records the **version of the confirmed data** as its own column (e.g., doc revision, ticket `updated_at`), so a later edit doesn't silently inherit trust the prior version earned.

**How a user confirms** — from explicit to implicit:
- **An affordance in the AI tool** — thumbs-up / "accurate," scoped per cited source rather than the whole answer (one response may cite several sources; only one was the good one).
- **Conversationally, to the agent** — in Claude Cowork there may be no button; the user just says "yes, that's right," and the agent records it by calling an **MCP confirm tool** (agent-native parity with the button).
- **A correction is a negative signal** — when a user fixes the underlying record (§1.2), capture that too; trust is two-sided.

Like all DL writes, a **service account writes the confirmation to the store** — users never get direct write access to the confirmation store. The **confirming user's verified identity is captured as an attributed field** (e.g., `confirmed_by`), and routing every write through the service lets it enforce validation, **rate-limiting / de-duplication** (so no one inflates a record's trust by confirming it repeatedly), and provenance at write time. Concretely: at most one confirmation per user per cited source-version, and a minimum count of distinct confirmers before trust affects ranking (§3.2). Read access follows the §2 group-share model.

- **Start as a [Confluence-page table](lik-dl-storage.md#confluence-pages):** updatable in place (unlike a create-only Drive Sheet), so the service account appends and de-duplicates against the same page, with version history as the audit log and revert as recovery.
- **Promote** to the [service-fronted Postgres store](lik-dl-storage.md#postgres-the-service-fronted-store) (§2.6) when scale, untrusted writers, or high-stakes ranking demand hard write-time enforcement of rate-limiting and de-duplication. Being **durable and non-recomputable**, confirmation signals also need their own **backup/retention** — unlike the rest of DL, they can't be rebuilt from the DSs.

### 3.2 Using confirmation signals at query time

The §3.1 table is just another §2.5 retrieval signal: a **Query skill** (§1.3) triggered by a user's question can read it — joining on the DS-record or DL-output pointer the answer cites — and let accumulated trust shape the response. The skill runs under the **user's** SSO, so it only ever sees confirmations the group-share model already permits. How aggressively a skill leans on trust is the **skill author's choice**; the options below run from lightest-touch to most invasive.

**Trust can also live in the DS itself.** Some data sources carry their own native trust signals — a Confluence page marked "verified," a resolved or accepted Jira ticket, reactions or endorsements, an owner's explicit sign-off. These are separate from DL confirmation signals, and it is up to the Query skill to **weigh the two together**: a DS-native endorsement and a DL confirmation are both evidence of trust, and the skill (under the user's SSO) reads whichever it can and combines them as the author sees fit.

- **A. Presentation only** (never changes what's retrieved) — annotate "confirmed accurate by N people" (or by a named expert, from `confirmed_by`), or flag "reported inaccurate on <date>" for a previously-corrected record. Safest; never hides data.
- **B. Version-aware** (exploits the confirmed-version column) — **staleness gating** (if the record changed since it was confirmed, downgrade/flag — "confirmed, but edited since") and **recency decay** (weight recent confirmations higher).
- **C. Ranking** (changes which data the answer uses) — **tie-breaker** (prefer the more-confirmed of similarly-relevant or conflicting candidates; least distorting), **rank boost** (relevance retrieves, trust reorders), or **threshold/filter** (aggressive — prefer soft demotion, since a hard filter can hide correct-but-unconfirmed data).
- **D. Audience weighting** (exploits `confirmed_by`) — weight confirmations from the asker's group or a topic's owners (§1.3) above a stranger's; adds query-time group-resolution cost.

**Choosing a strategy.** Start with **A + staleness gating (B)** — read-only, transparent, exploiting columns we already capture. Add the **tie-breaker (C)** once confirmation volume is trustworthy. Defer hard filters and audience weighting until the Level 0 gap backlog shows a question type that needs them. Whatever the choice, **trust advises, never gates**: a record the user is entitled to is never hidden by low trust, only ranked or annotated — gating stays the DS's job (§1.3).

### 3.3 Managing the signal store

Confirmation signals are the one durable, non-recomputable part of DL (§3.1), so the store needs deliberate upkeep — both to bound its size and to push trust back toward the source of truth. Two mechanisms:

- **Backpropagate to the DS record (with user validation).** Once a record accumulates enough confirmations or after a certain amount of time, a user can promote that trust into the data source itself — marking the Confluence page "verified," accepting the Jira ticket — written under the **user's own SSO** through the §1.2 write model. Trust then lives natively in the DS, where §3.2 already reads it, so the matching DL confirmation signals are now redundant and can be **removed or archived** from the DL store. This is gated on **user validation, never automatic**: a write to the source of truth is far harder to undo than a DL revert, so a person entitled to edit the record confirms the promotion. The payoff is that DL's irreversible, backup-needing footprint (§3.1) shrinks as custody returns to the DS.
- **Age out on a moving window.** A confirmation counts toward the live signal only while recent (the same intuition as the recency decay of §3.2 B); past the window it is **archived rather than deleted** — kept for audit and retention (§3.1), but no longer weighed in ranking. This bounds the store and keeps trust reflecting current judgment rather than years-old votes.

What stays live is recent, un-promoted trust; everything else has either moved into the DS or into an archive tier.

---

## Level 3-Catalog — The catalog (a Confluence page)

**Goal:** give every consumer **one lookup** to discover where any DL output lives, decoupled from storage decisions.

The catalog is DL's "yellow pages": a directory you consult to find *where* an output lives (`entry_type + subject → location`), then follow the pointer. It indexes DL's **topology**, not DS content, so a subject's pointers can migrate from one store to another (a Confluence page to a database) by changing one catalog row — with no change to any agent.

The catalog only ever does **exact-match lookup on its keys**; turning a user's fuzzy question into the right `(entry_type, subject)` key is the **Query skill's** job (§1.3), never the catalog's — which is why the catalog stays a plain keyed directory and never needs semantic search or a vector index. When the skill can't resolve an exact subject, its area-level fallback reuses the existing `category` column — filter rows by `category` to get a candidate set, then narrow — rather than adding a new grouping axis; this can only misroute, never widen access, since reads stay gated at the target store.

It is the one artifact nothing points *to*, so it lives at a **well-known address** agents know a priori; everything else is discovered through it.

**This mirrors an emerging industry standard.** Google's [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (v0.1 draft released June 12, 2026) — an open spec for handing AI agents curated organizational knowledge as a set of markdown files — reserves a special `index.md` file for exactly this purpose: a file at a known location that **lists what a directory contains so an agent can map it before opening any individual document** (progressive disclosure). Our catalog is the same idea applied to the whole Discovery Layer instead of a single folder — one well-known map of what exists and where, consulted before fetching the artifact itself. The one deliberate difference is *how* it's read: an OKF `index.md` is small enough to read whole, whereas our catalog spans every subject DL covers, so an agent resolves its question to a key and fetches only the matching row (see below) rather than loading the whole catalog.

**Implemented as a [Confluence page](lik-dl-storage.md#confluence-pages) — chosen for transparency and in-place editing.** It is updated in place at a stable address, with version history and SSO-attributed edits for free, and sits alongside the source pages it indexes so anyone can open it and read exactly what the catalog claims. It is treated as **just another DS artifact**, with one tightening: because it's the single entry point every consumer hits first, **all writes go through the DL-creation skill's service account** — autonomously for the rows it computes, and under a verified human assertion for human-created rows (§4.3); no one edits rows directly. Reads stay open for transparency. Consumers treat a **missing or malformed row as a cache miss** — fall back to the Query skill's routing (or a **bounded fan-out** — a capped search of the few most-likely stores, never the unbounded "search every store" fan-out of Level 1) rather than erroring. Suits low-cardinality pointers (dozens to low-hundreds of subjects). The schema is in [lik-3-architecture-concise.md §3](lik-3-architecture-concise.md).

**What gets cataloged.** Not every output a producer touches earns a row — registration is **per `(entry_type, subject)` key**, not per artifact, and an output qualifies only when it meets all three:

- **Externally addressable** — it answers a stable `(entry_type, subject)` that a consumer *other than its producer* would look up. Many outputs about one subject collapse to a single row; the catalog indexes topology by subject, not every artifact.
- **Meant to be discovered** — it's intended for reuse by other tools/agents, not a producer's private intermediate (a skill's scratch signal, the confirmation store itself). Cataloging something only its producer reads buys nothing.
- **Worth a stable pointer** — it has a durable address that survives re-derivation (the same Confluence page, the same signal row), rather than a transient result.

The **producer decides**, by these conditions: a DL-creation skill registers the outputs its author designated catalog-worthy; a Level 4 synthesis is registered when the user opts to save it (§4.3); a Parallel-Track pipeline registers its reporting outputs the same way. The rule is uniform — *register a reusable answer, keyed by a stable `(entry_type, subject)`, that consumers beyond the producer should discover.*

**How it's created and kept honest.** The **DL-creation skill**, writing under its non-human service account (e.g., `summarizer@navapbc.com`), registers the location of each output it's configured to publish (per the conditions above) as it runs, appearing in version history like any editor. Because version history is *corrective, not preventive*, each run also **validates entries / dangling pointers and re-derives the rows it owns** (`row_provenance = 'skill'`), bounding any misdirection window; human-created rows it can't re-derive rely on revert.

*Hardening (inline):*
- **The catalog stores pointers, not permissions.** Real access is enforced at each target store's group grant (§2 access control), so a tampered or wrong catalog row can *misdirect* a lookup but can never *widen* access. That bounds the blast radius of a bad write; routing every write through the skill account (above) then keeps the shared entry point from being broken or redirected by any editor.
- **Promotion.** When subject count or pointer volume outgrows a page, promote the *same logical schema* to **[Postgres](lik-dl-storage.md#postgres-the-service-fronted-store) or any indexed DB**, served by the §2.6 service — consumers still do one `(entry_type, subject)` lookup. A catalog in a non-versioned store takes on the [governed-writer discipline](lik-dl-storage.md#governed-writer-controls) and adds its own audit columns (`created_at` / `updated_at` / `updated_by`), which the Confluence-page realization doesn't need. Because the catalog is the a-priori entry point, promotion must preserve its **well-known address**: consumers reach it through a stable alias/indirection, not the page's raw URL, so the backing store can change underneath without breaking any consumer.

**Result.** Tools have one known starting point instead of fanning out per query. This is the core of "data democracy": authorized users reach knowledge without knowing where any artifact physically lives.

**Query skills now evolve.** What §1.3 did by hand — a maintained routing table of "for this question, look here" — the catalog now provides as computed, scalable data. So a skill stops hard-coding DS routing and instead routes through the catalog when it doesn't already know where the answer lives. The two become complementary: the catalog authoritatively answers *where* each output lives, while the skill still shapes *how* the agent answers (citations, freshness, fallback).

**A topic-scoped skill can skip the catalog.** Because there are **many Query skills, each expert on a topic** (§1.3), a skill built for a known subject can point the agent **straight at the specific DL outputs it already knows**, with no catalog lookup at all — the fastest path. The catalog is the **fallback** for questions a skill can't place directly: a general skill, or a specialized one that hits an unknown subject, resolves the question to a key and looks it up. So the catalog isn't always step one — it's the shared map for whatever a skill hasn't already memorized.

**Consulting the catalog is a targeted lookup, not a full read.** The skill directs the agent to resolve the question to a `(entry_type, subject)` key and fetch only the matching row(s) — never to load the whole catalog and scan it. The catalog grows with every subject DL covers, so reading it whole would reintroduce the per-query bloat the catalog exists to remove and would break the moment it outgrows what fits in a single read. The skill's job is therefore to turn a user's intent into the right key (expanding the same acronyms, codenames, and canonical phrasing it already knows from §1.3); the catalog answers the keyed lookup. This holds in both realizations — a keyed lookup against the Confluence page today, an indexed `(entry_type, subject)` query after promotion (§2.6) — so the consumer's access pattern never changes as the catalog scales.

---

## Level 4 — Flywheel: saved answers become new DL outputs

**Goal:** grow DL coverage from the questions people actually ask. When the **Query skill** synthesizes an answer across several DSs that exists in no DL output yet, it offers to persist that synthesis as a new durable artifact — so the next person retrieves it instead of re-deriving it.

The gap this closes: Level 2's DL-creation skills must **guess** what to precompute, and Level 3-Confirmations only captures trust on outputs that *already exist*. Neither turns a one-off cross-source answer — correct, but living only in one chat transcript — into reusable DL. Level 4 makes every saved novel synthesis a candidate DL output, so coverage grows **demand-driven** rather than by guesswork. It builds on Level 1 (the §1.3 Query skill and §1.2 write model do the work) and uses Level 3-Catalog to make each new output discoverable; it does *not* depend on Level 3-Confirmations.

### 4.1 The save-to-create gesture

When the Query skill **synthesizes an answer across multiple DSs that matches no existing DL output**, Level 4 lets it offer to **create** that missing output — as simply as *"Create a Confluence page / Google Doc from this answer?"*

- **The skill detects the trigger.** It already knows whether it answered from an existing DL output (it looked one up) or had to fan out across DSs and synthesize. Only the latter — a synthesis with no DL home — prompts the offer.
- **Whole answer or parts.** A response may stitch together several sources; the user can save the whole synthesis or just the section that was the good one.
- **Opt-in and user-driven.** The user vouches for both the *content* (this answer is right) and the *action* (yes, save it). No silent writes.

Once the artifact exists, ordinary §3.1 confirmations apply to it like any other DL output — but that is downstream reuse, not what creates it.

### 4.2 What gets written, and where

The persisted synthesis is a **human-created Discovery Layer output** (§2.2) — a §2.4 summary, born durable. It is **not** a DS record: a DS record is primary knowledge authored for its own sake, while this is *derived* material whose purpose is reuse and discovery. Like every §2.4 artifact, it simply lives in a DS-hosted store — a Confluence page or Google Doc.

It is written under the **user's own SSO** — which §2.2 already allows for human-authored DL outputs (human-verified and human-created outputs come from people, not the service identity). Because a person vouched for it at creation, it is born **`human-verified`**: durable, not recomputable, attributed to the creating user in version history. Like confirmation signals, it is one of the strategy's durable, **non-recomputable** commitments (Key terms, §3.1) — it can't be rebuilt from the DSs, so it needs its own backup/retention, and revert is its only recovery.

Access follows the **DL group-share model (§2.3)** — one sensitivity tier, audience no broader than its most-restricted source — *not* the single-location ACL inheritance of a §1.2 DS write, because a cross-source synthesis can blend tiers (see Guardrails).

It is **registered in the catalog** (§4.3) so the next consumer finds it through the same single lookup as any other DL output, and from there it behaves exactly like a §2.4 summary — read under the group-share model, ranked with the same signals, eligible for further confirmations (§3.1).

### 4.3 Registering in the catalog

The artifact is written by the user's agent under their own SSO (§4.2), but the **catalog row is not** — §3-Catalog routes every catalog write through the DL-creation skill's service account, never a user's agent. The same split confirmations use applies (§3.1: the user supplies the signal, a service account writes the store): **the user creates the artifact; a service registers the pointer.**

After writing the artifact, the Query skill calls the §2.6 scoped tool `register_catalog_entry` with the user's verified assertion. The service performs the catalog write under **its own service identity** — preserving the narrow-writer rule — and captures the creating user as `created_by`. This adds a second writer mode for catalog rows: §2.6 today writes them **service-only**; Level 4 writes them **service + user assertion**, the mode §2.6 already defines for confirmations.

The tool enforces three things at write time (the reason §2.6 forbids raw SQL):

- **Pointer resolves** — reject if the artifact doesn't exist, mirroring §3.1's citation-must-resolve rule.
- **Sensitivity (§2.3)** — the row's declared audience must be no broader than the artifact's actual ACLs, so registering a pointer can never widen access.
- **De-dup** — an existing row for the same `(entry_type, subject)` is updated in place, not duplicated (§4.1 guardrail, §2.4).

The row is marked **human-created**, not `row_provenance = 'skill'`: the §3-Catalog validation pass can't re-derive a human synthesis, so it **validates the pointer but doesn't recompute the row**, dropping or flagging it only if it goes dangling — revert is its recovery, consistent with its durable, non-recomputable nature (§4.2).

Routing through the service account works in **both catalog realizations**: the service does the Confluence-page write today and the indexed-DB write after promotion (§2.6). Nothing forces promotion — but Level 4 is a real argument for it, since catalog growth now comes from many users supplying assertions, not just the skill's own runs.

### 4.4 The flywheel

Each turn of the loop makes the next answer cheaper:

1. A user asks something with no DL answer; the Query skill fans out across DSs and synthesizes.
2. The user saves the answer (§4.1–4.2).
3. The synthesis is now a durable DL output, discoverable via the catalog.
4. The next person asking the same thing retrieves it in one step instead of re-fanning out — and can confirm it too, accruing trust (§3.2).

Usage surfaces answers worth saving; saved answers become new DL outputs; new outputs make answers faster and cheaper; faster answers drive more usage. DL coverage grows toward the questions people actually ask — the opposite of precomputing outputs nobody reads.

### Guardrails

- **One sensitivity tier per artifact (§2.3).** A cross-source synthesis can blend content from differently-restricted DSs. The save path must place it in a location no broader than its **most-restricted input** — default-deny when in doubt — so persisting an answer never widens access beyond what its sources allowed.
- **No duplication storms.** Before creating, the skill checks the catalog for an existing artifact on the same `(entry_type, subject)` and updates it in place (§2.4) rather than spawning near-duplicates — the same de-duplication discipline confirmations use (§3.1).
- **Trust the source, not the synthesis, long-term.** A saved synthesis goes stale as its underlying DSs change and — unlike an `AI-generated` output — isn't re-derived. The §3.2 staleness signals flag it ("verified, but sources edited since"), and the §3.3 backpropagation path lets its trust eventually move into the source DSs, after which the standalone synthesis can be archived.

### Expected limitations of this level

The flywheel only covers subjects that get **asked about and confirmed** — a cold-start topic nobody has queried yet still has no DL output. So Level 4 complements, rather than replaces, Level 2's proactive precomputation: the DL-creation skill seeds coverage for known-important subjects, while the flywheel fills in coverage demand reveals.

---

## Parallel Track — Deterministic data pipeline & warehouse

**Goal:** serve operational reporting (BI dashboards) and scale DL's retrieval signals, via the **same MCP interface** as everything else.

**This is not a fifth step — it's an independent track.** It builds on the same foundations as Levels 1–4 (MCP exposure, SSO, and — once it registers outputs — the catalog), but isn't gated on completing the levels in sequence: start it whenever the BI use case matters, provided the foundations it uses are already in place. Equally, Levels 1–4 stand on their own without it.

It is a **deterministic path** — no AI in the loop:

```
DSs → Deterministic Pipeline → Warehouse → BI Dashboards
```

- **Deterministic pipelines** handle known, repeatable transforms — dashboard tables, aggregations, metrics, reporting indexes, scheduled extracts — typically materialized in a **warehouse**. They assign each output a sharing group (the same fail-closed model as §2) and register their outputs in the catalog (Level 3-Catalog), exactly like the DL-creation skill does.
- **The warehouse is exposed via MCP like any other DS.** An agent or app queries it through the same `verified-SSO-token` path; the catalog points to warehouse tables (`store_kind = warehouse`, `bq://dataset.table`) just as it points to a Confluence page. To consumers, the warehouse is simply one more discoverable store.
- The warehouse is also **one option for DL's retrieval-signal backing store at scale** — the natural promotion target from §2.2 when signal volume is large. It is *one possibility*, not a requirement of the architecture.

*Hardening (inline):* the warehouse is a non-versioned store, so its writers (pipelines and any DL-signal promotion landing here) run under the [governed-writer controls](lik-dl-storage.md#governed-writer-controls). A BigQuery warehouse honors a Google Group via IAM directly; an admin only has to provision a Group for an audience whose source DS isn't already group-based.

Because it's a parallel track, it can be deferred entirely, or pulled forward ahead of Level 3-Catalog if reporting is the more urgent need.

---

## Coverage check

Every element of [lik-3-architecture-concise.md](lik-3-architecture-concise.md) lands in a layer:

| Concept | Layer |
|---|---|
| Build-vs-buy, commercial apps, bought-tool baseline, gap backlog | 0 |
| Self-hosted platforms | 0 (adopt) / 1.3 (consume our MCP) |
| Third-party trust boundary | 0 / 1.3 |
| DSs as source of truth, MCP exposure | 1 |
| Google SSO + Groups, identity rules, native per-DS enforcement | 1.1 |
| Write model (new / corrections / verified summaries) | 1.2 |
| DL computed outputs, tags, recomputable-vs-durable | 2 |
| DL-creation skill (privileged reader, group assignment, provenance marking) | 2 |
| Access control: group-share, fail-closed default, store→group/role table (mosaic dissolved via one-tier-per-output) | 2 (Access control) |
| Provision/maintain a Google Group for audiences whose source isn't group-based | 2 (Access control) / Parallel Track |
| Summaries & indexes | 2.4 |
| Retrieval signals | 2.5 |
| Confirmation signals (durable DL-origin) | 3-Confirmations §3.1 |
| Consuming confirmation signals at query time (annotation / staleness / ranking) | 3-Confirmations §3.2 |
| The catalog, schema, DL-creation skill (non-human account), validate/re-derive | 3-Catalog |
| Flywheel: saved cross-source answers persisted as new DL outputs | 4 |
| Store promotion (page/table → DB), governed-writer controls | 2.2 / 2.6 / Parallel Track (inline) |
| Deterministic pipeline, warehouse, BI dashboards | Parallel Track |

## Why this strategy

Each layer is an **evidence-driven bet**, and the order is chosen so each one's spend is justified by evidence from the layer before it:

- **Level 0** establishes whether a bought tool is already good enough, and — win or lose — yields the gap backlog that justifies any build at all. This operationalizes the build-vs-buy open question and the front-loaded build-vs-buy experiment from [lik-3-architecture-concise.md §11](lik-3-architecture-concise.md): buy first, A/B against the bought baseline, build only the gaps.
- **Level 1** proves SSO-gated MCP access is enough for real work.
- **Level 2** proves precomputed outputs beat fan-out search.
- **Levels 3-Confirmations and 3-Catalog** are independent of each other — both build on Level 2, neither requires the other. Level 3-Confirmations proves a human trust signal improves answers in ways computed signals can't; Level 3-Catalog proves a single catalog entry point beats per-store fan-out. The gap backlog guides which to build first.
- **Level 4** turns saved cross-source answers into reusable DL outputs, so coverage grows from real demand rather than precomputed guesses — complementing Level 2's proactive precomputation.
- The **deterministic pipeline** runs as a parallel track, adding reporting whenever BI demands it.

Ship one, learn, then spend on the next — rather than committing to the full system up front.
