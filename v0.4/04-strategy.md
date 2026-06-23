# Implementation Strategy

*The phased build plan — the roadmap most readers can stop at. Each level points to the deeper files for mechanics: terms in <u>Concepts</u>, design in <u>Architecture</u>, access in <u>Access Control</u>, stores in <u>Storage</u>, unresolved calls in <u>Open Questions</u>.*

**The strategy** — buy first, then build progressively only where a bought tool falls short. Each level is an **evidence-driven bet**: one standalone capability, justified by a limitation in the level before it, so each build is earned by evidence from the prior level. Ship a level, learn from it, build the next only if warranted. Every level ends with the **limitation** that motivates the next.

The levels, each detailed below:

- **Level 0 — Buy and learn.** Adopt a commercial tool for value today and a baseline, yielding the backlog of gaps that justifies any build at all.
- **Level 1 — Direct access via MCP.** Our own agent reads and writes the source systems where knowledge already lives, under the user's SSO.
- **Level 2 — Discovery Layer (DL) outputs.** Precompute reusable results so the agent stops re-searching from scratch.
- **Level 3-Confirmations.** Capture the human "this source was right" trust signal Level 2 can't compute.
- **Level 3-Catalog.** One lookup to discover where any DL output lives.
- **Level 4 — Flywheel.** Saved answers become new DL outputs, so coverage grows from the questions people actually ask.

**Acronyms:** **MCP** (Model Context Protocol) — the service interface agents/apps use to read and write DSs (and later DL) under a verified user identity. **SSO** — single sign-on (Google SSO + Google Groups). Identity mechanics — verified tokens, on-behalf-of exchange — are in <u>Access Control</u>.

---

## (Optional) Level 0 — Buy a commercial tool and learn

**Goal:** get immediate value and a measurable baseline by adopting an existing tool *before* building anything — and use the experience to decide what, if anything, is worth building.

Commercial enterprise-search / AI-retrieval products already connect to these DSs, enforce permissions, and provide AI retrieval out of the box. Buy one and run it for a few months:

- **Commercial apps** — Glean, GoSearch, SearchUnify.
- *Lower-cost variant:* self-hosted open-source — Onyx CE, PipesHub, SWIRL — if data residency or budget rules out commercial apps.

**What we get beyond the tool itself:**
- A **working capability today**, with no build cost.
- A **baseline** to measure any future build against — the honest comparison is "our build vs. this tool," not "our build vs. nothing."
- A **catalogued backlog of gaps**: specific `(data source, user question)` pairs where the bought tool does poorly — cross-source aggregations it can't compute, stale/untrusted answers, secured-but-discoverable content it can't reach, rankings it gets wrong. These become the build backlog for the levels below.

**How to run it:** pick a pilot user group, connect a few high-value DSs, have users log real questions and rate answers. Track precisely *where* it fails.

**Expected limitations.** A turnkey tool is a black box: you can't change its ranking or add cross-source aggregations / confirmation signals it doesn't natively support. Its **data-handling model** varies and matters — confirm it during evaluation, and wherever a copy exists, test third-party data-custody controls (*index-based* tools like Glean/GoSearch crawl sources into their own index — a derived copy + bulk re-export surface; *federated* tools like SearchUnify query at read time; many are *hybrid*). If no gaps are worth the cost, the strategy correctly stops here.

---

## Level 1 — Direct DS access via MCP

**Goal:** address Level 0's gaps by building our own agent that reads and writes knowledge in the systems where it already lives, governed by Google SSO.

The DSs stay the source of truth. Nothing is copied or precomputed yet. Each DS is exposed through an **MCP service**, and the agent reads/writes through it.

### 1.1 Single agent, read-only
A local Claude Cowork-style agent connects to a few approved DSs via MCP and reads on the user's behalf. The agent only ever sees what the signed-in person can see — the DS applies its **native permissions** directly, with no separate enforcement layer. (Token verification and on-behalf-of exchange across each `agent → MCP → DS` hop: <u>Access Control</u>.) The agent doesn't just route to a single record — it can read across the records it's permitted to and **synthesize** an answer from many at once, whether they sit in one DS or several. A skill guides that synthesis; saving such an answer is exactly what Level 4 builds on.

### 1.2 Read-write to DSs
The agent writes back under the **user's own SSO**, through each DS's normal permissions. The write model is deliberately narrow and stays fixed for all later levels: **new knowledge** → a DS; **corrections** → guide the user to fix the underlying record in its DS; **human-verified summaries** → a DS. Because access is enforced per-DS on every write, **new data inherits the right protections automatically** — a doc written into a restricted folder is restricted, with no separate permission system to keep in sync. (Full write model: <u>Architecture</u> §6.)

### 1.3 Query skills — encode *how* to answer
A raw agent doesn't know the org's retrieval conventions. Capture that know-how once as a **Query skill** — reusable instructions guiding the agent for certain question types — and share it with any employee. A skill can query a particular DS first, expand internal acronyms, scope to certain folders/projects, prefer named authoritative sources, and follow a fallback chain instead of fanning out. **Expect many Query skills**, each **owned and versioned** so drift has a responsible fixer. **Ownership rule:** a skill exists only with a named owner (the team that owns the topic for Query skills, the source-owning team for DL-creation skills) and a demonstrated gap it closes. No owner, no skill — orphaned skills are retired, not left to rot.

**Citing sources is mandatory, not optional.** Every answer records a structured, resolvable reference to each source it used — `store_kind + location + locator + version` (the same shape the Catalog uses, <u>Architecture</u> §3). This is precisely what lets a person later confirm *which* source was right (Level 3); an answer with no resolvable citation simply can't be confirmed.

Crucially, a skill is **guidance, not enforcement** — which is why it's safe to share with everyone. Every query still runs under the user's SSO, so the DS's permissions decide what comes back. A bad skill can misdirect but can never leak data the user wasn't entitled to; never rely on a skill to *restrict* access.

### Broadening the consumers
The MCP-to-DS path isn't specific to one agent. The same services can back the **Level 0 tools**, repointed at our MCP services so they proxy the end-user's identity — the **third-party trust boundary** in <u>Access Control</u> (require a verifiable end-user assertion; reject service-credential-only requests).

**Expected limitations.** Where no skill covers a question, a tool must **fan out across every DS** — slow, token-expensive, inconsistent. The residuals that motivate Level 2: **no reuse of computed results** — even a perfectly-routing skill re-runs the full cross-source retrieval live on every query, so the same expensive work is repaid by every user every time; precomputing once and reading many amortizes it and gives everyone the same answer. **Hand-authored guidance must be hand-maintained** — a skill's pointers and scoping **drift** as projects and DSs change, and upkeep grows with coverage.

---

## Level 2 — Discovery Layer computed outputs (no Catalog yet)

**Goal:** stop re-searching from scratch by precomputing reusable **DL outputs** — automating and scaling what the §1.3 skills did by hand.

DL outputs are produced by a **DL-creation skill** under its **own non-user service identity**. DL inputs are untrusted: the skill treats DS content as data, not instructions, and an output's sharing group always comes from the skill's instructions, never inferred from content. Every output is *derived material whose purpose is reuse* — never primary knowledge (that stays a DS record); the line is **role, not location**.

### 2.1 DL-creation skills — automate *what* to precompute
**Expect many DL-creation skills**, each customized to the source it handles and emitting a specific output type to a specific store, on a schedule or on demand, querying **one or more DSs** and linking across them. Each runs under a least-privilege per-DS service principal with keyless, rotated, audit-logged credentials (mechanics: <u>Access Control</u> governed-writer controls, <u>Storage</u>). Scheduled re-derivation also bounds staleness: a run that finds a source deleted or access revoked drops or re-restricts the derived output. *(Distinct from the §1.3 Query skills — these are the automated producers.)*

### 2.2 Authorship and durability
An output is born `ai-generated` and **recomputable** from the DSs — the default. A reviewer can promote it to `human-verified`, or a person can author one directly (`human-created`); both are **durable** — because they live in a DS, that DS backs them up, and revert is the only recovery. (The three DL output kinds and provenance tags: <u>Architecture</u> §2.) The one non-recomputable output DL stores and backs up itself is the confirmation signal (§3.1).

### 2.3 Access control
Every output carries **one sharing state** — a specified Google Group, explicitly unrestricted, or unspecified → default-deny — enforced by the store's own native group/role grant, **one sensitivity tier per output**. The author names the group in the instructions (the skill never chooses at runtime), and before writing the skill asserts that group is no broader than every input's audience. (Full model: <u>Access Control</u>.)

### 2.4 DL output types
Distilled prose, digests, indexes, prioritized pointers, retrieval hints, and content-freshness/obsolescence signals → written into a DS (such as a Confluence page), tagged `discovery-layer`, updated in place so each re-derivation revises the same page. Freshness and pointer metadata also surface as Catalog columns (<u>Architecture</u> §3).

**Expected limitations.** Two open problems, each solvable independently: **no human trust signal** (DL ranks by what's *derivable* — freshness, provenance, co-occurrence — but nothing captures whether a person vouched for a source as *correct*); **no single entry point** (outputs scatter across stores, so every tool must hard-code topology or fan out — the Level 1 problem one layer up).

### After Level 2 — two independent extensions
Level 3-Confirmations and Level 3-Catalog each address one limitation, with **no dependency on each other** — both require Level 2, neither requires the other. Build in whichever order the gap backlog favors.

Both can share **one service-fronted store** (typically a database): the confirmation store and a promoted Catalog can be the **same component**, reached through the MCP interface agents already use, with separate roles/tables per type. Split only if confirmations' write-enforcement later needs isolation the Catalog doesn't. (Scoped tools, writer modes, backup/retention: <u>Storage</u>.)

---

## Level 3-Confirmations — User confirmations

**Goal:** capture the one trust signal Level 2 can't compute — a person vouching that a cited source (a DS record or DL output) *was right* or wrong, not the generated answer — and feed it into retrieval. Produced by people, not derived, so confirmations are **non-recomputable**; **revert is their only recovery**.

### 3.1 Confirmation signals
A user confirms that a **DL output** or **DS record** an AI built its response from is trustworthy. The **citation is the join key**: a confirmation attaches only if the response cited its source (the §1.3 convention), the confirm path **rejects a confirmation whose citation doesn't resolve**, and each signal records the **version of the confirmed data** so a later edit doesn't silently inherit earned trust. Because a citation can resolve to the *wrong* record, the confirm step shows the user the exact source it's about to vouch for (title + last-updated) and requires **explicit per-source confirmation** — so a mis-citation surfaces as a visible mismatch instead of silently crediting the wrong record. A **service account writes the confirmation** under the confirming user's verified identity (`confirmed_by`) — users never write directly — enforcing rate-limiting / de-duplication and a minimum count of distinct confirmers before trust affects ranking. *(Confirming an answer that exists in no DL or DS yet is instead a request to **create** one — that's Level 4.)* Store: a Confluence-page table, promoted to the shared service-fronted store at scale (<u>Storage</u>).

### 3.2 Using confirmation signals at query time
A Query skill does a **targeted keyed lookup** on the cited pointer and lets accumulated trust shape the response, under the user's SSO — weighing DS-native trust (a "verified" page, an accepted ticket) alongside DL trust. Apply it in stages, lightest first:

- **A. Presentation only** — annotate "confirmed accurate by N people." Safest; never hides data.
- **B. Version-aware** — **staleness gating** (downgrade if the record changed since confirmed) and recency decay.
- **C. Ranking** — tie-breaker, rank boost, or threshold/filter (aggressive; prefer soft demotion).
- **D. Audience weighting** — weight confirmations from the asker's group or a topic's owners above a stranger's.

**Choosing:** start with **A + staleness gating (B)**; add the tie-breaker (C) once volume is trustworthy; defer hard filters and audience weighting until the backlog demands them. **Trust advises, never gates** — a record the user is entitled to is never hidden by low trust.

### 3.3 Signal lifecycle
- **Backpropagate to the DS (with user validation).** Once a record accumulates enough confirmations, a user can promote that trust into the source itself (mark the page "verified," accept the ticket) under their own SSO; the matching DL signals become redundant and are archived. Never automatic — a write to the source of truth is far harder to undo than a DL revert.
- **Age out on a moving window.** A confirmation counts only while recent; past the window it's **archived, not deleted** — kept for audit, no longer weighed.

---

## Level 3-Catalog — The Catalog

**Goal:** give every consumer **one lookup** to discover where any DL output lives, decoupled from storage decisions.

The Catalog is DL's "yellow pages" (`entry_type + subject → location`), indexing DL's **topology**, not DS content — so a subject's pointers can migrate between stores by changing one row, with no agent change. It does only **exact-match lookup on its keys** (turning a fuzzy question into the right key is the **Query skill's** job, so no semantic search is needed) and lives at a **well-known address** agents know a priori. This mirrors Google's emerging [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md), applied to the whole DL. Design, schema, what-qualifies-for-registration, and dangling-pointer resilience are all in <u>Architecture</u> §3; promotion mechanics in <u>Storage</u>.

A broken pointer is never fatal: a consumer treats it as a **cache miss** and falls back to skill routing or a **bounded fan-out** (a capped search of the few most-likely stores, never the unbounded Level 1 fan-out), so dangling links cost latency, not correctness. The Catalog stores **pointers, not permissions** — a tampered row can *misdirect* but never *widen* access (enforcement is the target store's).

**Query skills now evolve.** What §1.3 did by hand — a maintained routing table — the Catalog provides as computed, scalable data. A skill stops hard-coding DS routing and routes through the Catalog when it doesn't already know where the answer lives. A **topic-scoped skill can skip the Catalog** entirely; the Catalog is the **fallback** for questions a skill can't place directly. Consulting it is always a **targeted keyed lookup, not a full read**.

---

## Level 4 — Flywheel: saved answers become new DL outputs

**Goal:** grow DL coverage from the questions people actually ask. When a Query skill synthesizes an answer (from many records, in one DS or several) that exists in no DL output yet, it offers to persist that synthesis as a new durable artifact — so the next person retrieves it instead of re-deriving it.

The gap this closes: Level 2's skills must **guess** what to precompute, and Level 3-Confirmations only captures trust on outputs that *already exist*. Level 4 makes every saved novel synthesis a candidate DL output, so coverage grows **demand-driven**. Builds on Level 1 (the §1.3 Query skills and §1.2 write model). Level 3-Catalog is **optional but strongly recommended**: without it a saved synthesis still exists and is reachable by skill routing or bounded fan-out, but the Catalog is what makes it discoverable in one lookup. Does *not* depend on Level 3-Confirmations.

### 4.1 The save-to-create gesture
When the skill synthesizes an answer matching no existing DL output, it offers to **create** it — *"Create a Confluence page / Google Doc from this answer?"* The skill knows whether it answered from an existing output or had to assemble one from scratch. The user can save the **whole synthesis or just the good section**. **Opt-in and user-driven** — the user vouches for both the content and the action; no silent writes.

### 4.2 What gets written, and how
A **`human-created` DL output** — durable, not recomputable, attributed in version history — written under the **user's own SSO** into a DS-hosted store (a Confluence page or Google Doc), marked `discovery-layer`. The write **splits**: the user authors the artifact under their SSO, then — where a Catalog exists — a service account registers a Catalog pointer with the user as `created_by` (the same narrow-writer split confirmations use). The pointer is recommended, not required: it's what makes the artifact discoverable in one lookup, but the artifact is valid and reachable by fan-out without it. Access follows the **DL group-share model** — one tier, audience no broader than its most-restricted source — *not* §1.2 single-location inheritance, because a synthesis can draw on records with different restrictions and so blend tiers. (Write split: <u>Architecture</u> §4; registration enforcement: <u>Architecture</u> §3.)

### 4.3 The flywheel
1. A user asks something with no DL answer; the skill fans out and synthesizes.
2. The user saves the answer.
3. The synthesis is now a durable DL output — discoverable in one lookup once registered in the Catalog, and still reachable by fan-out if it isn't.
4. The next person retrieves it in one step instead of re-fanning out — and can confirm it, accruing trust.

Usage surfaces answers worth saving; saved answers become new outputs; new outputs make answers faster; faster answers drive more usage.

**Guardrails:** one sensitivity tier per artifact (default-deny in doubt); check the Catalog for an existing artifact on the same key and update in place rather than spawning near-duplicates; and because a saved synthesis isn't re-derived, it goes stale — §3.2 staleness flags it, and §3.3 backpropagation eventually moves its trust into the source DSs, after which the standalone synthesis can be archived.

**Expected limitation.** The flywheel only covers subjects that get **asked about** — a cold-start topic nobody queried has no DL output. So Level 4 complements Level 2's proactive precomputation rather than replacing it.
