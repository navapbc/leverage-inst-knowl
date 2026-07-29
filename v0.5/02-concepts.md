# Core Concepts

*The vocabulary used throughout these docs, in plain language. For the technical design, see <u>Architecture</u>.*

## The concepts and terminology

1. **Data Sources (DSs)** — the systems where knowledge is actually created, corrected, and governed (Drive, Confluence, Jira, GitHub, Slack, Salesforce, Workday, …). These hold the **primary knowledge** and stay **authoritative** for it: every lasting change is written here, and each system keeps controlling who may see what. An individual unit stored in a DS — a Confluence page, a Jira ticket, a Slack thread, a GitHub PR — is a **DS record**. What separates a plain DS record from a **DL record** is **purpose, not how it was produced or what it contains**: a DL record is a DS-stored artifact whose job is to be an *entry point an AI agent looks at first* — a summary, index, pointer, or signal that makes the underlying knowledge faster to find. Because a DL record lives in a DS, that DS stores, backs up, and governs it like any other record. Most DL records are generated automatically and rebuilt on demand, but a person may author or edit one — even adding original content — and it stays a DL record as long as its purpose is to be that entry point.

2. **Discovery Layer (DL)** — prepared material whose only job is to make knowledge **easy to find and reuse**, so tools don't re-search everything from scratch. Each piece is a **DL output**. What makes something DL is **purpose, not how it was produced**: it exists to be a fast entry point into the knowledge, not to be authored as knowledge for its own sake. **Two things are easy to conflate here, so keep them apart.** *Derived* describes the content's relation to the sources — it summarizes or points at what they already hold rather than adding new knowledge (a rule of thumb: remove the underlying records and a typical DL output has nothing left to describe). *Automatically generated* (`ai-generated`) describes who produced it. **Neither implies the other:** a person can hand-author derived material — a summary they write by hand is derived yet `human-created`. Most DL is both derived and auto-generated, but that's a common pairing, not a rule. And DL's safety doesn't rest on its content being purely derived anyway: it is still governed by the source it lives in, still cites what it points to, and still carries freshness signals.

   By **where it lives and who keeps it safe**, every DL output is one of three:
   - **A DL record** — the common case, and most of DL: an artifact written into a Data Source (such as a Confluence page) whose purpose is to be an AI entry point — a summary, index, pointer, or signal — marked `discovery-layer` to flag that role (the marker exists so the registrar can *discover* the record; a human-registered entry point may forgo it — see **Catalog-registration** below). Because it lives in a Data Source, **that source stores, backs it up, and governs it** like any other record, and reverting to an earlier version is its recovery. DL records divide by how they stay current: **automatic** ones are generated and rebuilt from the sources on demand (disposable); once a person edits, verifies, or hand-authors one it becomes **durable** — the automated rebuild never silently overwrites that copy: it leaves it alone, or surfaces a proposed update for the owner to accept, reject, or reconcile.
   - **The Catalog** — one well-known directory mapping a *topic* to *where its material lives*, so a tool does **one lookup** then follows the pointer instead of searching every system (move a piece and you change one line, not the tools). It's built only from the **DL records** — not the full sources — so there's far less to process. Those records hold the same "what exists and where" at finer granularity; the Catalog is the coarse, topic-level view over them. Rows a skill registered are recomputed and don't need to be backed up; the human-registered rows can't be regenerated, so those are backed up — the Catalog as a whole is not safe to drop and rebuild.
   - **Confirmation signals** — people vouching that the source behind an answer was right (or flagging it wrong). A confirmation attaches to the **cited DS record or DL output the answer drew from**, never to the AI's response text — which is why answers always cite their sources. A **Query skill** records one when a person gives positive or negative feedback on a cited source. It can't be re-derived, so it must be **kept deliberately** rather than simply rebuilt — as must a human-registered Catalog row; what's special about a confirmation is that it has no copy in any Data Source at all, so DL's own store is its only home.

3. **DL-creation skills** — the automated *producers*. Each reads the Data Sources and writes DL records, tagging each with the metadata a registrar needs to catalog it (its key, its audience, and the sources it came from); each runs on its own service identity, on a schedule or on demand. **There are many, not one** — a given skill is customized to the kind of source data it handles, so it can process and validate that source the way its owning team needs. Producing a DL record is a distinct job from cataloging it.

4. **Catalog-registration** — getting a DL record listed in the Catalog. There are **two non-exclusive paths**:
   - **By skill (the registrar).** A *Catalog-registration skill* **discovers** the DL records producers have written — the ones carrying the agreed DL-record marker (usually `discovery-layer`) — and **registers** them so tools can look them up, keeping the Catalog current as records appear, move, or go stale. It indexes DL records rather than authoring them — it never rebuilds a record's content; re-deriving DL *content* stays with the **DL-creation skill** (the producer, above) that wrote it. This path works by **enumerating marked records**, so it **depends on the marker** — a producer must tag what it wants catalogued.
   - **By manual (human) registration.** A person working with an agent **designates** an existing artifact — a page, doc, or sheet they already know is the best entry point for a topic — and registers it directly. There is no discovery scan, so the **`discovery-layer` marker is optional**: the Catalog entry itself records the entry-point role, and the person needn't be able to edit (or tag) the artifact to list it. Such an entry is **human-owned** — no skill re-derives it.

   Either way the Catalog only ever lists DL records: the skill path registers records a producer marked; the manual path *makes* the designated artifact a DL record by listing it as an entry point.

5. **Query skills** — the *guides*. Given a question, a skill steers an AI agent to the right material or the right source. Mostly they only help an agent *find* answers faster — never widen access, because every search runs under the asking person's own permissions. The one thing they produce is a **confirmation signal**: when a person gives feedback on a cited source, the skill records it. **There are many, not one** — each covers a topic or question type. A skill built for a known topic can go straight to the relevant material, skipping the Catalog; the Catalog is the fallback for questions no skill already knows how to answer.

Two relationships tie these together:

- The **DL-creation skill** takes **DS records** and creates **DL output**.
- The **Catalog-registration skill** finds those **DL records** and registers them in the **Catalog**.
- The **Query skill** queries **DL output** and **DS records** to answer a person's question.

## Progressive disclosure: answering in cheap steps

The Catalog and the Discovery Layer let an agent find an answer in increasingly specific steps, instead of loading everything at once. Each step costs more than the one before, and most questions are answered before reaching the bottom.

1. **Catalog** *(the entry point)* — one lookup to learn *what exists and where*.
2. **Discovery Layer** *(narrowing down)* — follow the pointer to prepared material already distilled from the sources.
3. **Data Sources** *(the original records)* — open the full records only when the question demands them.
4. **On-demand discovery** *(following links)* — from inside a record, follow links to related records as needed.

## Analogy: an office building

| LIK concept | Office building | Why it fits |
| --- | --- | --- |
| DS records | The individual offices, where the real work and records are kept | Authoritative for what they hold; each office controls who it lets in. |
| DL output | Handouts and digests *about* what the offices do — at reception, on floor screens, in a kiosk | Entry points so you don't visit every office; most are regenerated automatically, some can be hand-written. |
| Confirmation signals | Visitor feedback cards — "Suite 4B actually solved my problem" | People vouching an answer was good; kept on the card, not inside the office. |
| Catalog | The lobby directory — topic → where its handout is posted | The board everyone checks first; points to *where the handout lives*, not into the offices. |
| DL-creation skills | Information officers, each assigned to certain offices — they tour them and write the handouts | Produce the derived material; each specializes in the offices it knows. |
| Catalog-registration skill | The directory clerk — collects the posted handouts and keeps the lobby directory current | Indexes what the officers produce; doesn't write handouts, just lists where each one lives. |
| Query skills | Concierges, each an expert on certain topics — given your question, one points you to the right handout or office | Steer you; can only send you where you're already allowed in. |

A few nuances:
- The lobby directory indexes *where handouts live*, never the offices' contents — so a wrong line can misdirect you, but it can't unlock a door.
- An office can post its own "certified" plaque (trust native to the source), separate from visitor feedback cards; the concierge weighs both.
- There isn't one concierge or one information officer but **several, each specialized**. A concierge who already knows your topic walks you straight to the right handout without checking the directory first.

### Other analogies

**A restaurant**
- **DS:** the **kitchens** cook the real food.
- **DL:** a **meal-prep service** turns that into ready-to-eat boxes.
- **Catalog:** a **directory at the pickup counter** tells you where each prepped item sits.
- **Confirmation signals:** **diner reviews** say which dishes were good.

**Maps / GPS**
- **DS:** the **physical streets** are ground truth.
- **DL:** a **map** is a derived, simplified rendering kept in sync.
- **Catalog:** an **atlas's index** ("this region is on sheet 42").
- **Confirmation signals:** **user reports** — "this road is closed."
