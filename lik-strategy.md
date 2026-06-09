# Institutional Knowledge for AI Enablement — Implementation Strategy

An implementation **strategy** for [lik-architecture-concise.md](lik-architecture-concise.md). It starts by *buying* (Layer 0) to learn what's actually missing, then *builds* progressively (Levels 1–3) only where a bought tool falls short — with a parallel data-pipeline track. Each level is independently useful, adds one capability, and is justified by a limitation in the level before it.

The strategy is deliberately falsifiable: ship a layer, learn from it, and only spend on the next if the prior one proved the need. Every layer ends with a **limitation** — the reason the next one exists.

---

## Layer 0 — Buy a commercial tool and learn

**Goal:** get immediate value and a measurable baseline by adopting an existing tool *before* building anything — and use the experience to decide what, if anything, is worth building.

Commercial enterprise-search / AI-retrieval products already ingest these DSs, enforce permissions, and provide AI retrieval out of the box. Buy one and run it for a few months:

- **Commercial apps** — Glean, GoSearch, SearchUnify.
- *Lower-cost variant:* self-hosted open-source platforms — Onyx CE, PipesHub, SWIRL — adopt (don't build) if data residency or budget rules out SaaS.

**What we get beyond the tool itself:**
- A **working capability today**, with no build cost.
- A **baseline / yardstick** to measure any future build against — the honest comparison is "our build vs. this tool," not "our build vs. nothing."
- Most importantly, a **catalogued backlog of gaps**: specific **use cases**, each a `(data source, user question)` pair, where the bought tool does poorly — cross-source aggregations it can't compute, stale or untrusted answers, secured-but-discoverable content it can't reach, rankings it gets wrong. These gaps become the build backlog for the levels below.

**How to run it:** pick a pilot user group, connect a few high-value DSs, and have users log real questions and rate the answers. Track precisely *where* it fails — which data sources it can't reach, which questions come back wrong/stale/incomplete, which permissions it can't honor.

> **Limitation.** A turnkey tool is a black box -- possible limitations may be: you can't change its ranking, you can't add cross-source aggregations or trust signals it doesn't natively support, and — for index-based tools — it maintains its own index of your content, effectively a copy and a bulk re-export surface (confirm each tool's data-handling model; some federate queries at read time instead of copying — apply the third-party trust-boundary controls in 1.3 where a copy exists). The gaps catalogued here become the **build backlog** for Levels 1–3 — and if none are worth the cost, the strategy correctly stops at Layer 0.

- Index-based enterprise search (Glean, and GoSearch) ingests/crawls connected sources into its own search index — that is a derived copy, with source ACLs mirrored into it.
- Federated / connector modes (SearchUnify supports this, and others offer it) query sources at read time and don't persist a full copy.
- Many are hybrid, and the data-handling model is a procurement/config detail you'd confirm per tool.

---

## Level 1 — Direct DS access via MCP

**Goal:** address Layer 0's gaps by building our own agent that reads and writes institutional knowledge in the systems where it already lives, with access governed by Google SSO.

The **Data Sources (DSs)** — Google Drive, Confluence, Jira, GitHub, Slack, Gmail, Salesforce, Workday — stay the source of truth. Nothing is copied or pre-computed yet. Each DS is exposed through an **MCP service**, and the agent reads/writes through it.

### 1.1 Single agent, read-only

A local Claude Cowork-style agent connects to a few approved DSs via MCP and reads on the user's behalf.

- **Access control via Google SSO.** Each MCP service / AI connector requires a **verified Google OIDC/OAuth token** (audience-validated); the verified email *claim* authorizes the call. Identity is carried across every `agent → MCP → DS` hop (token passthrough / on-behalf-of), so the agent can only ever see what the signed-in person can see. An email is an identifier, never a self-asserted authenticator.
- **The DS enforces its own native permissions.** The connector authenticates to each DS as the signed-in user, and that DS applies its native ACLs directly — no separate enforcement layer to keep in sync, and no need to normalize permissions into Google Groups at this level. (Normalizing native ACLs into Groups via an **admin mapping process** only becomes necessary once DL *materializes* a copy of the data and has to enforce on it itself — see §2.2 and the Parallel Track.)

### 1.2 Read-write to DSs

The agent writes back under the **user's own SSO identity**, through each DS's normal permissions. The **write model** is deliberately narrow and stays fixed for all later levels:

- **New knowledge** → a DS (policy → Confluence/Drive; decision → ticket/page).
- **Corrections** → guide the user to fix the underlying record in its DS.
- **Human-verified summaries** → a DS.

Because access is enforced per-DS on every read and write, **new data inherits the right protections automatically** — a doc written into a restricted Drive folder is restricted; a ticket created in a private project stays private. No separate permission system to keep in sync.

### 1.3 Broaden the consumers

The MCP-to-DS path is not specific to one agent. The same services can back other clients — including the **commercial or self-hosted tools from Layer 0**, repointed at our MCP services so they proxy the end-user's identity instead of relying solely on their own connectors (and, for index-based tools, their own copy of the data).

**Third-party trust boundary (inline hardening):** external tools are a distinct trust zone. For each one, define **credential scope** (least-privilege slice), **data minimization** (which DSs, not all), **retention/training constraints**, and **breach containment**. A tool querying under its own service credentials must faithfully proxy the end-user's identity so per-DS enforcement isn't bypassed.

> **Limitation.** To find anything, every tool must **query each DS and fan out across all of them** on every request — slow, token-expensive, inconsistent across tools, and prone to dead ends. There is no shared, reusable view of what exists or where it is.

---

## Level 2 — Discovery Layer computed outputs (no catalog yet)

**Goal:** stop re-searching the DSs from scratch by precomputing reusable **Discovery Layer (DL)** outputs derived from them.

DL is a *computed* layer, never a hand-maintained knowledge base, and never a second source of truth. It is **AI-generated by default** (a user may hand-author an artifact, in which case it's tagged `human-created`). Most DL is **recomputable** from the DSs at any time.

DL content carries lightweight **tags**, realized with whatever the store already supports (a column, a label, a page property) — provenance/verification, freshness/trust, classification, and propagated ACL metadata. No bespoke tagging system.

DL outputs are produced by a **scheduled or manual AI skill** that reads DS content (respecting ACLs), computes the output, and writes it to a chosen store via MCP. The skill is the **most privileged reader**, scoped **least-privilege per DS**, and it **captures each item's source ACL at read time** (a miss silently widens access).

The store is chosen **per output type**, along two axes — *who consumes it* and *how much integrity it needs*:

### 2.1 Human-readable artifacts

Summaries, digests, curated indexes → written into any DS where people already work (a Google Doc, a Confluence page). Must be **provenance-marked `AI-generated`**, and written under a clear identity (the user's SSO for attended runs, a non-human Google account for unattended). Unverified until a person reviews it, at which point it becomes **`human-verified`** DS content under that reviewer's identity.

*Hardening (inline):* these live in version-history DSs, so attribution and audit come from the DS's own version history — revert is the recovery path. No special write regime.

### 2.2 Machine retrieval signals

Indexes, prioritized pointers, retrieval hints, freshness/obsolescence signals, and **propagated ACL metadata** → a store chosen for scale (a Google Sheet at small scale; Postgres or BigQuery later). This is a storage-engine choice, not an architectural one.

*Hardening (inline):*
- **Now DL holds a copy, so it must enforce on it.** Unlike Level 1 (where each DS enforced itself), a materialized store needs propagated ACL metadata. For DSs that can't express Google Groups (Slack channels, Atlassian roles, Salesforce profiles, Workday models), an **admin mapping process** with a named owner normalizes native ACLs to Groups — **default-deny** for unmatched records, **most-restrictive-wins** on conflict. Here the mapping is the **primary** mechanism.
- **ACL metadata is a *hint*, not a gate.** It's used for routing/pre-filtering only; real enforcement stays at the target store (the DS's native permissions, or query-time predicates where DL serves from its own store). A tampered hint can't widen access.
- **Access-control freshness.** Propagated ACL is a cache, and a stale cache leaks access after a revocation. Refresh permissions on a schedule **decoupled** from content-staleness refresh; for sensitive categories, re-validate against the live DS/Group at query time or enforce a **maximum propagation lag with a fail-closed default**.
- **Mosaic effect.** A cross-DS aggregation has no single source ACL and can be more sensitive than any input. It inherits the **most-restrictive intersection** of its sources' groups and is **restricted by default**. If its sensitivity exceeds what the target store can enforce, **don't materialize it** — store a pointer/instruction telling permitted users to recompute it under their own identity at query time.
- **Promotion.** When a signal store outgrows a Sheet, promote to a non-versioned store (Postgres/warehouse) under **governed-writer controls**: no long-lived keys (e.g., Workload Identity Federation), a rotation schedule, least privilege, and audit logging on all writes.

### 2.3 Confirmation / trust signals

Users confirm that an output is useful or accurate. These confirmations **originate in DL** from user feedback and exist in **no DS** — they are **durable DL-origin data**, the one part of DL that is *not* recomputable. **Revert is their only recovery.**

- **Start in a Google Sheet:** native sharing gates writers, every write is attributed to an SSO identity, version history is the audit log.
- **Promote** to a store fronted by a service enforcing verified identity, rate-limiting, and write-time provenance (e.g., Postgres + app) when scale, untrusted writers, or high-stakes ranking demand write-time enforcement. Being non-recomputable, they need their own backup/retention.

> **Limitation.** DL now deliberately **spreads outputs across many stores** — a Doc here, a Sheet there. To use them, every tool must hard-code that storage topology, or fan out and search every store — reintroducing the Level 1 problem one layer up. There is **no single known place to start**.

---

## Level 3 — The catalog (a single Google Sheet)

**Goal:** give every consumer **one lookup** to discover where any DL output lives, decoupled from storage decisions.

The catalog is DL's "yellow pages": a directory you consult to find *where* an output lives (`entry_type + subject → location`), then follow the pointer. It indexes DL's **topology**, not DS content, so a subject's pointers can migrate from a Sheet to BigQuery by changing one catalog row — with no change to any agent.

It is the one artifact nothing points *to*, so it lives at a **well-known address** agents know a priori; everything else is discovered through it.

**Implemented as a single Google Sheet — chosen for transparency.** A Sheet gives native sharing, SSO-attributed edits, and version history *for free*, and anyone can open it and see exactly what the catalog claims. It is treated as **just another DS artifact**: any user with native edit access may write it, edits are attributed via SSO and logged by version history, and a bad edit is reverted. Suits low-cardinality pointers (dozens to low-hundreds of subjects). The schema is in [lik-architecture-concise.md §2](lik-architecture-concise.md).

**How it's created and kept honest.** A **skill writing under an ordinary non-human Google account** (e.g., `summarizer@navapbc.com`) registers each computed output's location as it runs, appearing in version history like any editor. Because version history is *corrective, not preventive*, each run also **validates entries / dangling pointers and re-derives the rows it owns** (`row_provenance = 'skill'`), bounding any misdirection window; hand-authored rows it can't re-derive rely on revert.

*Hardening (inline):*
- **Enforcement never trusts the catalog's stored ACL hint** — real access is enforced at the target store, so a tampered catalog row can't widen access. This is why the Sheet can stay openly editable.
- **Promotion.** When subject count or pointer volume outgrows a Sheet, promote the *same logical schema* to **Postgres or any indexed DB** — consumers still do one `(entry_type, subject)` lookup. A catalog in a non-versioned store takes on the **governed-writer discipline** and adds its own audit columns (`created_at` / `updated_at` / `updated_by`), which the Sheet realization doesn't need.

> **Result.** Tools have one known starting point instead of fanning out per query. This is the core of "data democracy": authorized users reach knowledge without knowing where any artifact physically lives.

---

## Parallel Track — Deterministic data pipeline & warehouse

**Goal:** serve operational reporting (BI dashboards) and scale DL's machine-retrieval signals, via the **same MCP interface** as everything else.

**This is not a fourth step — it's an independent track.** It shares Levels 1–3's foundations (MCP exposure, SSO, the catalog) but doesn't depend on their *order*: build it whenever the BI use case matters, before or after Level 3. Equally, Levels 1–3 stand on their own without it.

It is a **deterministic path** — no AI in the loop:

```
DSs → Deterministic Pipeline → Warehouse → BI Dashboards
```

- **Deterministic pipelines** handle known, repeatable transforms — dashboard tables, aggregations, metrics, reporting indexes, scheduled extracts — typically materialized in a **warehouse**. They propagate/assign ACL metadata and register their outputs in the catalog (Level 3), exactly like the AI skill does.
- **The warehouse is exposed via MCP like any other DS.** An agent or app queries it through the same `verified-SSO-token` path; the catalog points to warehouse tables (`store_kind = warehouse`, `bq://dataset.table`) just as it points to a Doc or a Sheet. To consumers, the warehouse is simply one more discoverable store.
- The warehouse is also **one option for DL's machine-retrieval backing store at scale** — the natural promotion target from §2.2 when signal volume is large. It is *one possibility*, not a requirement of the architecture.

*Hardening (inline):* the warehouse is a non-versioned store, so its writers (pipelines and any DL-signal promotion landing here) run under the **governed-writer controls** — no long-lived keys, rotation, least privilege, audit logging. For each DS feeding a *materialized* warehouse store, document whether Group attachment is possible and, where not, how native ACLs normalize (the admin mapping is the **primary** mechanism there).

> Because it's a parallel track, it can be deferred entirely, or pulled forward ahead of Level 3 if reporting is the more urgent need.

---

## Coverage check

Every element of [lik-architecture-concise.md](lik-architecture-concise.md) lands in a layer:

| Concept | Layer |
|---|---|
| Build-vs-buy, commercial apps, falsification baseline, gap backlog | 0 |
| Self-hosted platforms | 0 (adopt) / 1.3 (consume our MCP) |
| Third-party trust boundary | 0 / 1.3 |
| DSs as source of truth, MCP exposure | 1 |
| Google SSO + Groups, identity rules, native per-DS enforcement | 1.1 |
| Admin mapping process (normalize native ACLs → Groups for materialized stores) | 2.2 / Parallel Track |
| Write model (new / corrections / verified summaries) | 1.2 |
| DL computed outputs, tags, recomputable-vs-durable | 2 |
| AI skill (privileged reader, source-ACL capture, provenance marking) | 2 |
| Human-readable artifacts | 2.1 |
| Machine retrieval signals, ACL-hint enforcement, freshness contract, mosaic effect | 2.2 |
| Confirmation / trust signals (durable DL-origin) | 2.3 |
| The catalog, schema, non-human-account skill, validate/re-derive | 3 |
| Sheet→Postgres promotion, governed-writer controls | 2.2 / 3 / Parallel Track (inline) |
| Deterministic pipeline, warehouse, BI dashboards | Parallel Track |

## Why this strategy

Each layer is a **falsifiable bet**, and the order is chosen so each one's spend is justified by evidence from the layer before it:

- **Layer 0** establishes whether a bought tool is already good enough, and — win or lose — yields the gap backlog that justifies any build at all. This operationalizes the build-vs-buy open question and the front-loaded falsification experiment from [lik-architecture-concise.md §11](lik-architecture-concise.md): buy first, A/B against the bought baseline, build only the gaps.
- **Level 1** proves SSO-gated MCP access is enough for real work.
- **Level 2** proves precomputed outputs beat fan-out search.
- **Level 3** proves a single transparent catalog beats per-store lookups.
- The **deterministic pipeline** runs as a parallel track, adding reporting whenever BI demands it.

Ship one, learn, then spend on the next — rather than committing to the full system up front.
