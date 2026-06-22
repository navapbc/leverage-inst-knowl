# Implementation Strategy

*The phased build plan. Concepts are defined in [02-concepts.md](02-concepts.md); the design in [04-architecture.md](04-architecture.md); access in [05-access-control.md](05-access-control.md); stores in [06-storage.md](06-storage.md). Unresolved decisions are in [08-open-questions.md](08-open-questions.md).*

**The strategy** — buy first, then build progressively only where a bought tool falls short. Each level is an **evidence-driven bet**: one standalone capability, justified by a limitation in the level before it, so each build is earned by evidence from the prior level. Ship a level, learn from it, and build the next if warranted. Every level ends with a **limitation** — the reason the next one exists.

The levels, each detailed below:

- **Level 0 — Buy and learn.** Adopt a commercial tool for value today and a baseline, yielding the backlog of gaps that justifies any build at all.
- **Level 1 — Direct access via MCP.** Our own agent reads and writes the source systems where knowledge already lives, under the user's SSO.
- **Level 2 — Discovery Layer (DL) outputs.** Precompute reusable results so the agent stops re-searching from scratch.
- **Level 3-Confirmations.** Capture the human "this source was right" trust signal Level 2 can't compute — a person vouching that a cited DS record or DL output was right (or wrong).
- **Level 3-Catalog.** One lookup to discover where any DL output lives.
- **Level 4 — Flywheel.** Saved answers become new DL outputs, so coverage grows from the questions people actually ask.

**Acronyms used below:** **MCP** (Model Context Protocol) — the service interface agents/apps use to read and write DSs (and later DL) under a verified user identity. **ACL** — per-record permissions. **SSO** — single sign-on (Google SSO + Google Groups). **OIDC/OAuth** — the protocols producing the verified identity token.

---

## (Optional) Level 0 — Buy a commercial tool and learn

**Goal:** get immediate value and a measurable baseline by adopting an existing tool *before* building anything — and use the experience to decide what, if anything, is worth building.

Commercial enterprise-search / AI-retrieval products already connect to these DSs, enforce permissions, and provide AI retrieval out of the box. Buy one and run it for a few months:

- **Commercial apps** — Glean, GoSearch, SearchUnify.
- *Lower-cost variant:* self-hosted open-source — Onyx CE, PipesHub, SWIRL — if data residency or budget rules out commercial apps.

**What we get beyond the tool itself:**
- A **working capability today**, with no build cost.
- A **baseline** to measure any future build against — the honest comparison is "our build vs. this tool," not "our build vs. nothing."
- A **catalogued backlog of gaps**: specific use cases, each a `(data source, user question)` pair, where the bought tool does poorly — cross-source aggregations it can't compute, stale/untrusted answers, secured-but-discoverable content it can't reach, rankings it gets wrong. These become the build backlog for the levels below.

**How to run it:** pick a pilot user group, connect a few high-value DSs, have users log real questions and rate answers. Track precisely *where* it fails.

**Expected limitations.** A turnkey tool is a black box: you can't change its ranking or add cross-source aggregations / confirmation signals it doesn't natively support. Its **data-handling model** varies and matters — confirm it during evaluation; wherever a copy exists, test third-party data-custody controls. *Index-based* tools (Glean, GoSearch) crawl sources into their own index (a derived copy + bulk re-export surface); *federated* tools (SearchUnify) query at read time without a full copy; many are *hybrid*. If no gaps are worth the cost, the strategy correctly stops here.

---

## Level 1 — Direct DS access via MCP

**Goal:** address Level 0's gaps by building our own agent that reads and writes knowledge in the systems where it already lives, governed by Google SSO.

The DSs stay the source of truth. Nothing is copied or precomputed yet. Each DS is exposed through an **MCP service**, and the agent reads/writes through it.

### 1.1 Single agent, read-only
A local Claude Cowork-style agent connects to a few approved DSs via MCP and reads on the user's behalf. Each MCP service requires a **verified Google OIDC/OAuth token**; identity is carried across every `agent → MCP → DS` hop via **on-behalf-of token exchange**, so the agent only ever sees what the signed-in person can see. The DS applies its **native permissions** directly — no separate enforcement layer. *(Each user grants per-DS OAuth consent once; the MCP service stores and refreshes their tokens.)*

### 1.2 Read-write to DSs
The agent writes back under the **user's own SSO**, through each DS's normal permissions. The write model is deliberately narrow and stays fixed for all later levels:
- **New knowledge** → a DS (policy → Confluence/Drive; decision → ticket/page).
- **Corrections** → guide the user to fix the underlying record in its DS.
- **Human-verified summaries** → a DS.

Because access is enforced per-DS on every read and write, **new data inherits the right protections automatically** — a doc written into a restricted folder is restricted. No separate permission system to keep in sync.

### 1.3 Query skills — encode *how* to answer
A raw agent doesn't know the org's retrieval conventions. Capture that know-how once as a **Query skill** — reusable instructions that guide the agent for certain question types — and share it with any employee. A skill can: query a particular DS first for a question type; expand internal acronyms/codenames and prefer canonical phrasing; scope to certain folders/spaces/projects; prefer named authoritative sources; follow a fallback chain instead of fanning out; always cite links and surface last-updated dates; route by team/client/project.

This is the cheapest way to encode retrieval know-how by hand; DL later automates the scalable *data* behind it — pointers, aggregations, freshness — while the skill itself persists. A skill is **owned and versioned** so skill drift has a responsible fixer — as the gap backlog reveals where agents go wrong, skill updates will be needed. **Expect many Query skills** — each covers a topic/question type with its own maintainers.

Crucially, a skill is **guidance, not enforcement** — which is why it's safe to share with everyone. Every query still runs under the user's SSO, so the DS's permissions decide what comes back. A bad skill can misdirect, but can never leak data the user wasn't entitled to. Never rely on a skill to *restrict* access — access control enforcement is always the DS's job.

### Broadening the consumers
The MCP-to-DS path isn't specific to one agent. The same services can back the **Level 0 commercial/self-hosted tools**, repointed at our MCP services so they proxy the end-user's identity. This is where the **third-party trust boundary** ([05](05-access-control.md#third-party-integration-trust-boundary)) applies: require a verifiable end-user assertion alongside any service credential, and reject requests carrying only a service credential.

**Expected limitations.** Where no skill covers a question, a tool must **fan out across every DS** on each request — slow, token-expensive, inconsistent, prone to dead ends. Skills cut blind fan-out for the questions they cover but don't remove the underlying problem. The residuals that motivate Level 2: **no reuse of computed results** — even a perfectly-routing skill re-runs the full cross-source retrieval and aggregation live on every query, so the same expensive work is repaid by every user every time; precomputing once and reading many amortizes the cost and gives everyone the same answer. **Hand-authored guidance must be hand-maintained** — a skill's pointers and scoping are written and updated by a person, so they **drift** as projects and DSs change, and upkeep grows with coverage.

---

## Level 2 — Discovery Layer computed outputs (no Catalog yet)

**Goal:** stop re-searching from scratch by precomputing reusable **DL outputs** — automating and scaling what the §1.3 skills did by hand.

DL outputs are produced by a **DL-creation skill** under its **own non-user service identity**. DL inputs are untrusted: the skill treats DS content as data, not instructions, and an output's sharing group always comes from the skill's instructions, never inferred from content. Every output is *derived material whose purpose is reuse* — never primary knowledge (that stays a DS record); the line is **role, not location**.

### 2.1 DL-creation skills — automate *what* to precompute
**Expect many DL-creation skills**, each customized to the source it handles and emitting a specific output type to a specific store. Each runs on a schedule or on demand, querying **one or more DSs** and producing outputs that can link across them. Each skill's identity is realized as a per-DS service principal (a Slack bot, a Jira/Salesforce service account, a Workday ISU, a GCP service account), granted **least-privilege read**, authenticating with **keyless, rotated credentials**, writing with audit logging. Scheduled re-derivation also bounds staleness: a run that finds a source deleted or access revoked drops or re-restricts the derived output. *(Distinct from the §1.3 Query skills — these are the automated producers.)*

### 2.2 Authorship and durability
| State | Written by | Durability |
|---|---|---|
| `AI-generated` | DL-creation skill | **Recomputable** from the DSs — the default |
| `human-verified` | A reviewer, under their own SSO | **Durable** — revert is the only recovery |
| `human-created` | A human author directly | **Durable** — revert is the only recovery |

A person reviewing an AI-generated output promotes it to `human-verified`; version history records who. The two durable states are the DL outputs that can't be rebuilt — they need their own backup/retention (as do confirmations, §3.1).

### 2.3 Access control
Every output carries one sharing state — a specified Google Group, explicitly unrestricted, or unspecified → default-deny ([05](05-access-control.md)). Enforcement is the store's own native group/role grant; **one sensitivity tier per output**, and the author **names the group in the instructions** (the skill never chooses at runtime). Before writing, the skill asserts the named group is no broader than every input's audience; on failure the output stays default-deny.

### 2.4 Summaries & indexes
Distilled prose, digests, indexes → written into a DS (such as a Confluence page), updatable in place so each re-derivation revises the same page. Starts `AI-generated`; a reviewer promotes to `human-verified`.

### 2.5 Retrieval signals
Indexes, prioritized pointers, retrieval hints, content-freshness/obsolescence signals → written into a DS or a **service-fronted table** (for example in BigQuery or Postgres at scale). Updated in place as content freshness changes. A signal store is non-versioned, so its writer runs under [governed-writer controls](06-storage.md#governed-writer-controls); in Postgres it also needs the group → role bridge.

### 2.6 The service-fronted store — one MCP write/read path
The signal store (§2.5), the confirmation store (§3.1-Confirmations), and a promoted Catalog (Level 3-Catalog) can be implemented as the **same thing** (typically a database), reached through an **MCP service** — the interface agents already use for DSs. For simplicity, treat it as **one component**.

- **Scoped tools, never raw SQL** — intent-named tools (`confirm_source`, `upsert_signal`, `register_catalog_entry`) each enforce their own rules at write time; reads are equally scoped (`lookup_confirmations` by citation, version optional — pinned for staleness gating, omitted to total across versions). The validation lives in the tool; that's the whole reason a store graduates to a database.
- **Two writer modes** — *service-only* (signals, Catalog rows) and *service + user assertion* (a confirmation carrying the confirming user's verified identity as `confirmed_by`).
- **What the service owns** — reads resolve the caller's Google Groups into a row-level-security predicate; governed-writer controls on its connection; backup/retention for the confirmation tables (the durable, non-recomputable exception).
- **Start as one service** fronting all three types, with separate roles/tables per type. Split only if confirmations' write-enforcement later needs isolation the others don't.

**Expected limitations.** Two open problems, each solvable independently: **no human trust signal** (DL ranks by what's *derivable* — content freshness, provenance, co-occurrence — but nothing captures whether a person vouched for a cited source as *correct*); **no single entry point** (outputs scatter across stores, so every tool must hard-code topology or fan out — the Level 1 problem one layer up).

### After Level 2 — two independent extensions
Level 3-Confirmations and Level 3-Catalog each address one limitation, with no dependency on each other — both require Level 2, neither requires the other. Build in whichever order the gap backlog favors.

---

## Level 3-Confirmations — User confirmations

**Goal:** capture the one trust signal Level 2 can't compute — a person vouching that a cited source (a DS record or DL output) *was right* or wrong, not the generated answer — and feed it into retrieval. Produced by people, not derived, so confirmations join the human-authored outputs (§2.2) as **non-recomputable**; **revert is their only recovery**.

### 3.1 Confirmation signals
A user confirms that a **DL output** or **DS record** an AI built its response from is trustworthy. These originate in DL, are not DS records (and can't be derived from any DS), and are **non-recomputable data**. *(Confirming an answer that exists in no DL or DS yet is a different gesture — a request to **create** one; that's Level 4.)*

- **Linking a signal to its data.** A confirmation attaches only if the response is traceable via the §1.3 "always cite source links" convention — the citation is the join key. The confirm path **rejects a confirmation whose citation doesn't resolve**. Each signal records the **version of the confirmed data**, so a later edit doesn't silently inherit earned trust.
- **How a user confirms** — an affordance in the tool (thumbs-up scoped per cited source), conversationally to the agent (which calls an **MCP confirm tool** — agent-native parity with the button), or as a **negative signal** when a user corrects the underlying record (§1.2).
- **A service account writes the confirmation** — users never get direct write access. The confirming user's verified identity is captured as `confirmed_by`; routing through the service enforces validation, **rate-limiting / de-duplication** (at most one confirmation per user per cited source-version), and a minimum count of distinct confirmers before trust affects ranking.
- **Store:** can start as a [Confluence-page table](06-storage.md#confluence-pages); **promote** to the [service-fronted Postgres store](06-storage.md#postgres-the-service-fronted-store) (§2.6) when scale / untrusted writers / high-stakes ranking demand hard write-time enforcement. Durable and non-recomputable, so it needs its own backup/retention.

### 3.2 Using confirmation signals at query time
The §3.1 table is just another §2.5 retrieval signal: a Query skill does a **targeted keyed lookup** on the cited pointer (optionally pinned to a version), fetching only the matching rows and lets accumulated trust shape the response, under the user's SSO. **Trust can also live in the DS itself** (a "verified" page, an accepted ticket, an owner's sign-off) — the skill weighs DS-native and DL trust together. How aggressively, lightest to most invasive:

- **A. Presentation only** — annotate "confirmed accurate by N people" or "reported inaccurate on <date>." Safest; never hides data.
- **B. Version-aware** — **staleness gating** (downgrade if the record changed since confirmed) and **recency decay**.
- **C. Ranking** — **tie-breaker** (prefer the more-confirmed of similar candidates), **rank boost**, or **threshold/filter** (aggressive; prefer soft demotion).
- **D. Audience weighting** — weight confirmations from the asker's group or a topic's owners above a stranger's.

**Choosing:** start with **A + staleness gating (B)**; add the **tie-breaker (C)** once volume is trustworthy; defer hard filters and audience weighting until the gap backlog demands them. **Trust advises, never gates** — a record the user is entitled to is never hidden by low trust.

### 3.3 Signal lifecycle: promote and age out
- **Backpropagate to the DS (with user validation).** Once a record accumulates enough confirmations, a user can promote that trust into the source itself (mark the page "verified," accept the ticket) under their own SSO; the matching DL signals become redundant and are removed/archived. Gated on user validation, never automatic — a write to the source of truth is far harder to undo than a DL revert.
- **Age out on a moving window.** A confirmation counts toward the live signal only while recent; past the window it's **archived, not deleted** — kept for audit, no longer weighed.

---

## Level 3-Catalog — The Catalog

**Goal:** give every consumer **one lookup** to discover where any DL output lives, decoupled from storage decisions.

The Catalog is DL's "yellow pages" (`entry_type + subject → location`), indexing DL's **topology**, not DS content — so a subject's pointers can migrate between stores by changing one row, with no agent change. It only ever does **exact-match lookup on its keys**; turning a fuzzy question into the right `(entry_type, subject)` key is the **Query skill's** job, so the Catalog needs no semantic search or vector index. It lives at a **well-known address** agents know a priori.

**This mirrors an emerging industry standard.** Google's [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (v0.1 draft, June 12, 2026) reserves an `index.md` at a known location that lists what a directory contains so an agent can map it before opening any document. Our Catalog is the same idea applied to the whole DL — with one difference: an OKF `index.md` is small enough to read whole, whereas an agent resolves a question to a key and fetches only the matching row.

**Can be implemented as a [Confluence page](06-storage.md#confluence-pages)** — chosen for transparency and in-place editing. Treated as **just another DS artifact**, with one tightening: because it's the single entry point everyone hits first, **all writes go through a DL-creation skill's service account** (autonomously for computed rows, under a verified human assertion for human-created rows — §4.3); no direct row editing. Consumers treat a **missing/malformed row as a cache miss** — fall back to the skill's routing or a **bounded fan-out** (a capped search of the few most-likely stores, never the unbounded Level 1 fan-out). Schema in [04-architecture.md §3](04-architecture.md#catalog-schema).

**What gets cataloged.** Registration is **per `(entry_type, subject)` key**, not per artifact. An output qualifies only when it is **externally addressable** (answers a stable key a *non-producer* would look up), **meant to be discovered** (not a producer's private intermediate), and **worth a stable pointer** (a durable address surviving re-derivation). The **producer decides**: a skill registers what its author designated; a Level 4 synthesis when the user opts to save it. The rule: *register a reusable answer, keyed by a stable `(entry_type, subject)`, that consumers beyond the producer should discover.*

**Kept honest.** The skill registers each output's location as it runs. Because version history is *corrective, not preventive*, each run also **validates entries / dangling pointers and re-derives the rows it owns** (`row_provenance = 'skill'`); human-created rows rely on revert.

*Hardening:* the Catalog stores **pointers, not permissions** — a tampered row can *misdirect* but never *widen* access (enforcement is the target store's). **Promotion:** when subject count outgrows a page, promote the *same schema* to [Postgres / indexed DB](06-storage.md#postgres-the-service-fronted-store) served by the §2.6 service — consumers still do one lookup; the well-known address is preserved via a stable alias so the backing store can change underneath.

**Query skills now evolve.** What §1.3 did by hand — a maintained routing table — the Catalog now provides as computed, scalable data. A skill stops hard-coding DS routing and routes through the Catalog when it doesn't already know where the answer lives. A **topic-scoped skill can skip the Catalog** entirely, pointing straight at outputs it already knows; the Catalog is the **fallback** for questions a skill can't place directly. Consulting it is always a **targeted keyed lookup, not a full read** — the skill resolves intent to a key and fetches only the matching row(s), in both the Confluence-page and promoted-DB realizations.

---

## Level 4 — Flywheel: saved answers become new DL outputs

**Goal:** grow DL coverage from the questions people actually ask. When a Query skill synthesizes a cross-DS answer that exists in no DL output yet, it offers to persist that synthesis as a new durable artifact — so the next person retrieves it instead of re-deriving it.

The gap this closes: Level 2's skills must **guess** what to precompute, and Level 3-Confirmations only captures trust on outputs that *already exist*. Level 4 makes every saved novel synthesis a candidate DL output, so coverage grows **demand-driven**. Builds on Level 1 (the §1.3 Query skills and §1.2 write model) and uses Level 3-Catalog for discoverability; does *not* depend on Level 3-Confirmations.

### 4.1 The save-to-create gesture
When the skill synthesizes a cross-DS answer matching no existing DL output, it offers to **create** it — *"Create a Confluence page / Google Doc from this answer?"* The skill detects the trigger (it knows whether it answered from an existing output or had to fan out). The user can save the **whole synthesis or just the good section**. **Opt-in and user-driven** — the user vouches for both the content and the action; no silent writes.

### 4.2 What gets written, and where
A **human-created DL output** (§2.2) — a §2.4 summary, born durable. Not a DS record (that's primary knowledge authored for its own sake; this is *derived* material for reuse). Lives in a DS-hosted store (a Confluence page or Google Doc), written under the **user's own SSO** (which §2.2 allows for human-authored outputs), born **`human-created`** — durable, not recomputable, attributed in version history. Access follows the **DL group-share model** ([05](05-access-control.md)) — one tier, audience no broader than its most-restricted source — *not* §1.2 single-location inheritance, because a cross-source synthesis can blend tiers. Registered in the Catalog (§4.3); from there it behaves like any §2.4 summary.

### 4.3 Registering in the Catalog
The artifact is written by the user's agent under their SSO, but the **Catalog row is not** — every Catalog write routes through a DL-creation skill's service account. The same split confirmations use: **the user creates the artifact; a service registers the pointer.** After writing, the skill calls `register_catalog_entry` with the user's verified assertion; the service writes under **its own identity** (preserving the narrow-writer rule) and captures the creating user as `created_by`. The tool enforces at write time: **pointer resolves**, **sensitivity** (declared audience no broader than the artifact's actual ACLs), and **de-dup** (an existing row for the same key is updated in place). The row is marked **human-created**: the validation pass validates the pointer but doesn't recompute the row — revert is its recovery.

### 4.4 The flywheel
1. A user asks something with no DL answer; the skill fans out and synthesizes.
2. The user saves the answer.
3. The synthesis is now a durable DL output, discoverable via the Catalog.
4. The next person retrieves it in one step instead of re-fanning out — and can confirm it, accruing trust.

Usage surfaces answers worth saving; saved answers become new outputs; new outputs make answers faster; faster answers drive more usage. Coverage grows toward the questions people actually ask.

### Guardrails
- **One sensitivity tier per artifact** — place a cross-source synthesis no broader than its **most-restricted input**; default-deny in doubt.
- **No duplication storms** — check the Catalog for an existing artifact on the same key and update in place rather than spawning near-duplicates.
- **Trust the source, not the synthesis, long-term** — a saved synthesis isn't re-derived, so it goes stale; §3.2 staleness signals flag it, and §3.3 backpropagation lets its trust eventually move into the source DSs, after which the standalone synthesis can be archived.

**Expected limitation.** The flywheel only covers subjects that get **asked about and confirmed** — a cold-start topic nobody queried has no DL output. So Level 4 complements Level 2's proactive precomputation rather than replacing it.
