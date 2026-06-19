# Leveraging Institutional Knowledge (LIK) — Overview

*A plain-language introduction. For real-world mappings see [lik-2-examples.md](lik-2-examples.md); for the technical design, [lik-3-architecture-concise.md](lik-3-architecture-concise.md); for the build plan, [lik-4-strategy.md](lik-4-strategy.md).*

## The problem

A company's knowledge is scattered across many systems — Google Drive, Confluence, Jira, GitHub, Slack, Gmail, Salesforce, Workday, and more. To answer one question, every AI agent, every app, and every person has to search all of those systems, over and over. That is slow, expensive, inconsistent from one tool to the next, and prone to missing the answer that is most trusted or most current.

## The idea

Leave the knowledge where it already lives. On top of it, add a lightweight layer that makes finding things fast — **without** copying everything into one place and **without** creating a second, competing "source of truth." The layer is *mostly computed*: the bulk of it is derived from the original systems and rebuilt on demand, so it needs no careful tending. A small, slow-growing part — people's confirmations and saved answers — can't be rebuilt, and that part is backed up deliberately.

## Guiding Principles

Every design choice in the later docs traces back to these.

- **Very low maintenance** — minimize the code and extra data we have to keep running. The bulk of the layer is recomputed from the sources, so it can be rebuilt or discarded rather than carefully tended; only a small, slow-growing part (people's confirmations and saved answers) must be kept and backed up.
- **Loosely coupled** — keep the pieces independent so any one — a store, a source, a tool — can be swapped without rewriting the rest, and no single vendor becomes hard to leave.
- **Intuitive (easy to understand and adopt)** — lean on standards (e.g., MCP) and common patterns rather than bespoke mechanisms, so people and tools pick it up quickly.
- **Flexible** — adaptable to a wide range of questions, data, and tools: many small, specialized skills instead of one rigid system.
- **One source of truth** — durable knowledge always stays in its original system. The layer holds only computed copies, pointers, and signals — never a competing master record.
- **Secure by default** — least privilege, deny when unsure, and access always enforced by the *original system*, never by the layer's own metadata. A wrong entry can misdirect a lookup but can never unlock a door.
- **Build on existing sign-in** — most systems are already reached through Google single sign-on, so access reuses that existing login and its group permissions instead of standing up a new identity or permission system to maintain. (Sources that don't already use Google groups for permissions need a one-time mapping — see the architecture for details.)
- **Earn each step** — add each capability only once the previous one's limits prove it's needed; spend follows evidence, not ambition.

## The concepts and terminology

1. **Data Sources (DSs)** — the systems where knowledge is actually created, corrected, and governed (Drive, Confluence, Jira, GitHub, Slack, Gmail, Salesforce, Workday, …). These hold the **primary knowledge** — records that exist for their own sake — and stay the **source of truth**: every lasting change is written here, and each system keeps controlling who may see what.

2. **Discovery Layer (DL)** — a layer of *prepared material derived from the Data Sources*: summaries, indexes, pointers, and freshness/trust signals. Its whole reason to exist is to make relevant knowledge **easy to find and reuse** — pertinent DS records can be cataloged, ranked, and/or rated so tools don't re-search everything from scratch. It is **derived** material — never primary knowledge authored for its own sake (that's a Data Source), and never a second source of truth. A quick test: a DL output exists only *because* there's something to discover — remove the underlying records and a summary, index, or signal has nothing left to describe. **Most** of it is *recomputable* — rebuilt from the sources on demand (typically by an AI), so while it stays AI-owned it's cheap to update and safe to discard. Rebuilds overwrite only what the AI still owns, never a person's work: **editing or verifying an output transfers ownership**, making it durable — exempt from future rebuilds and backed up deliberately, like the parts people authored from scratch (a summary someone wrote, the confirmation signals below).

3. **Catalog** — the Discovery Layer's "yellow pages": one well-known place that maps a *topic* to *where its prepared material lives*. A tool does **one lookup**, then follows the pointer — instead of searching every system. Move a piece of material and you change one line in the catalog, not the tools that use it.

4. **DL-creation skills** — the automated *producers*. Each reads the Data Sources, writes the Discovery Layer's prepared material, and keeps the catalog current; each runs on its own service identity, on a schedule or on demand. **There are many, not one** — a given skill is customized to the kind of source data it handles (its type, location, and owning team/project/program), so it can process and validate that source the way that team or program needs and produce a specific kind of output in a specific place.

5. **Query skills** — the *guides*. Given a question, a skill steers an AI agent to the right prepared material or the right source. They can only help an agent *find* answers faster — never widen access, because every search runs under the asking person's own permissions. **There are many, not one** — each covers a topic or question type. A skill built for a known topic can go **straight to the relevant prepared material**, skipping the catalog lookup entirely; the catalog is the fallback for questions no skill already knows where to answer.

6. **Confirmation signals** — people vouching that the source behind an answer was right (or flagging it wrong). A confirmation attaches to a **cited source the answer drew from** — a record in a Data Source, or prepared material in the layer — never to the AI's response text itself; that's why answers always cite their sources, so each vouch lands on a specific source rather than the wording of the reply. One of the durable, *people-sourced* parts of the Discovery Layer (above): it can't be re-derived from the sources, so it is kept and backed up deliberately.

Two relationships tie these together:

- The **DL-creation skill** takes **DS records** and creates **DL data**.
- The **Query skill** queries **DL data** and **DS records** to answer a person's question.

## Progressive disclosure: answering in cheap steps

The catalog and the Discovery Layer let an agent find an answer in increasingly specific steps, instead of loading everything at once. Each step costs more than the one before, and most questions are answered before reaching the bottom.

1. **Catalog** *(the entry point)* — one lookup to learn *what exists and where* (the high-level roadmap).
2. **Discovery Layer** *(narrowing down)* — follow the pointer to prepared material already distilled from the sources (a summary, index, or signal).
3. **Data Sources** *(the original records)* — open the full records only when the question demands them.
4. **On-demand discovery** *(following links)* — from inside a record, follow links to related records to expand understanding as needed.

## Analogy: an office building

| LIK concept | Office building | Why it fits |
| --- | --- | --- |
| DS records | The individual offices, where the real work and records are kept | The source of truth; each office controls who it lets in (its own permissions). |
| DL data | Handouts and digests *about* what the offices do — posted at reception, on floor screens, in a kiosk | Derived so you don't have to visit every office; scattered across spots; most can be regenerated from the offices anytime. |
| Confirmation signals | Visitor feedback cards — "Suite 4B actually solved my problem" | People vouching an answer was good; kept on the card, not inside the office. |
| Catalog | The lobby directory — topic → where its prepared material is posted | The one board everyone checks first; points to *where the handout lives*, not what's inside the offices. Move a handout and you change one directory line, not the offices. |
| DL-creation skills | Information officers, each assigned to certain offices — they tour those offices, write the handouts, and keep the directory current | Produce the derived material; each specializes in the offices (sources) it knows. |
| Query skills | Concierges, each an expert on certain topics — given your question, one points you to the right handout or office | Steer you; can only send you where you're already allowed in — the offices' own locks still decide. |

A few nuances:
- The lobby directory indexes *where prepared materials live*, never the offices' contents — so a wrong directory line can misdirect you, but it can't unlock a door.
- An office can post its own "certified" plaque (trust native to the source), separate from visitor feedback cards (DL confirmation signals); the concierge weighs both.
- There isn't one concierge or one information officer but **several, each specialized**. A concierge who already knows your topic can walk you straight to the right handout without checking the lobby directory first; the directory is there for questions no concierge has memorized.

### Other analogies

**A restaurant**
- DS: The **kitchens** cook the real food. 
- DL: A **meal-prep service** turns that into ready-to-eat boxes and a tasting menu.
- Catalog: A **directory at the pickup counter** — "boxed salads: case 3; tasting menu: shelf B" — tells you where each *prepped* item sits; it points at the boxes, not the recipes.
- Confirmation signals: **Diner reviews** say which dishes were actually good.

**Maps / GPS**
- DS: The **physical streets and buildings** are the ground truth.
- DL: A **map** is a derived, simplified rendering kept in sync with reality.
- Catalog: An **atlas's index** — "this region is on sheet 42"; it tells you which derived map sheet to open, not what's on the ground.
- Confirmation signals: **User reports** — "this road is closed," "great coffee here".

## Artifacts at a glance

Every artifact the strategy creates, where it lives, who writes it, and how it's used. The **Discovery Layer outputs** are grouped by **how they start**: **computed** (AI-derived, recomputable, discardable while AI-owned) or **human-originated** (durable, backed up, revert is the only recovery). The split isn't permanent — a *computed* output a person edits or verifies becomes durable and **human-owned**, joining the second group; the skill won't clobber it, because before recomputing anything it checks the last revision was its own.

- **DS records** — new knowledge, corrections, human-created or human-verified summaries
  - *Resides in:* the relevant Data Source (Confluence, Drive, Jira, GitHub, Slack, etc.)
  - *Written by:* the user's agent, under the **user's own SSO**
  - *Read/used by:* anyone with DS permission, via MCP
  - *Durability:* the **source of truth** — durable; everything else derives from it
  - *Access control:* the DS's own native ACLs; new data inherits its location's protections automatically

### AI Agent Skills

- **Query skill** — shareable "where to look and how to ask" guidance
  - *Resides in:* a shared skill library, available to any employee
  - *Written by:* a **named human owner**; versioned
  - *Read/used by:* every employee's agent, at query time
  - *Durability:* durable, hand-authored
  - *Access control:* none needed — it's guidance, not enforcement, and can never widen access

- **DL-creation skill** — the automated *producer* of Discovery Layer outputs
  - *Resides in:* runs under its **own non-user service identity** (per-DS service principals)
  - *Written by:* developers / skill authors
  - *Read/used by:* n/a — it's the engine that writes the DL outputs below
  - *Durability:* code; durable
  - *Access control:* keyless rotated credentials, least-privilege per DS, audit-logged writes

### Computed DL outputs *(AI-derived; recomputable and discardable while AI-owned)*

*Two of these cross into human-originated the moment a person edits or verifies them — summaries (per output) and the catalog (per row).*

- **Summaries & indexes** *(Discovery Layer output)* — distilled prose, digests, and human-readable indexes
  - *Resides in:* a [Confluence page](lik-dl-storage.md#confluence-pages)
  - *Written by:* the DL-creation skill's **service identity** (tagged `AI-generated`); promoted to `human-verified` under a reviewer's identity
  - *Read/used by:* people in the sharing group
  - *Durability:* **recomputable while AI-owned**; a person editing or verifying it makes that copy **durable and human-owned** (it joins *Human-originated* below), and the skill stops overwriting it — it recomputes only outputs whose last revision was its own
  - *Access control:* group-share, fail-closed; native store grant (Drive sharing, Confluence restriction)

- **Retrieval signals** *(Discovery Layer output)* — indexes, pointers, retrieval/freshness/obsolescence hints
  - *Resides in:* a small service-fronted table → BigQuery / [Postgres](lik-dl-storage.md#postgres-the-service-fronted-store) at scale
  - *Written by:* the DL-creation skill's **service identity** (governed-writer controls in non-versioned stores)
  - *Read/used by:* tools/agents (via Query skills) at query time
  - *Durability:* **recomputable** from the DSs
  - *Access control:* group-share, fail-closed; store-native group/role grant

- **Catalog** *(Discovery Layer output — the index over the others)* — the "yellow pages" mapping `type + subject → location`
  - *Resides in:* a **[Confluence page](lik-dl-storage.md#confluence-pages) at a well-known address** → [Postgres](lik-dl-storage.md#postgres-the-service-fronted-store) / indexed DB at scale
  - *Written by:* the DL-creation skill's **service account** (e.g., `summarizer@navapbc.com`) — autonomously for the rows it computes, and under a **verified human assertion** for human-created rows (the same split Level 4 uses: a person supplies the pointer, the service writes the row)
  - *Read/used by:* **every consumer** — the first stop to find where any DL output lives
  - *Durability:* skill-owned rows re-derived each run (computed); its **human-created rows belong to the human-originated class** — durable, revert-only
  - *Access control:* reads open for transparency; all writes go through the service account — no direct row editing

### Human-originated DL outputs *(durable, not recomputable; backed up, revert is the only recovery)*

*Plus any computed output above that a person has since edited or verified — that act makes it durable and moves it here.*

- **Persisted synthesis** *(Discovery Layer output)* — a cross-DS answer saved as a new human-created DL artifact
  - *Resides in:* a [Confluence page or Google Doc](lik-dl-storage.md) (a DS-hosted store), registered in the catalog
  - *Written by:* the **user's own agent under their SSO** (human-authored DL output), born `human-verified`
  - *Read/used by:* people in the sharing group, via the catalog — like any other artifact
  - *Durability:* **durable, NOT recomputable** — revert is the only recovery; needs its own backup/retention
  - *Access control:* DL group-share, fail-closed; audience no broader than its most-restricted source

- **Confirmation signals** *(Discovery Layer output)* — user trust and correction feedback
  - *Resides in:* a [Confluence-page table](lik-dl-storage.md#confluence-pages) → a [service-fronted Postgres store](lik-dl-storage.md#postgres-the-service-fronted-store) at scale
  - *Written by:* a **service account** (the confirming user captured as `confirmed_by`); rate-limited / de-duped at write
  - *Read/used by:* Query skills at query time, to shape ranking
  - *Durability:* **durable, NOT recomputable** — revert is the only recovery; needs its own backup/retention
  - *Access control:* group-share for reads; users never get direct write access

### Deterministic Pipelines

- **Warehouse tables / BI outputs** — deterministic reporting, no AI in the loop
  - *Resides in:* a warehouse (e.g., BigQuery)
  - *Written by:* **deterministic pipelines** (governed-writer controls)
  - *Read/used by:* BI dashboards; agents/apps via MCP; also a promotion target for retrieval signals
  - *Durability:* **recomputable** (deterministic)
  - *Access control:* the same fail-closed group model; BigQuery IAM honors Google Groups directly

## Where to go next

- **[lik-2-examples.md](lik-2-examples.md)** — how these concepts map to systems Nava already runs (Project Indexes, OPIS).
- **[lik-3-architecture-concise.md](lik-3-architecture-concise.md)** — the technical design: components, schema, access control, write model.
- **[lik-4-strategy.md](lik-4-strategy.md)** — the build plan: buy first, then build progressively where a bought tool falls short.
- **[lik-dl-storage.md](lik-dl-storage.md)** — the storage reference: how each backing store (Confluence, Google Drive, Postgres) behaves.
