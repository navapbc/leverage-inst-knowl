# Core Concepts

*The vocabulary used throughout these docs, in plain language. For the technical design, see [04-architecture.md](04-architecture.md).*

## The concepts and terminology

1. **Data Sources (DSs)** — the systems where knowledge is actually created, corrected, and governed (Drive, Confluence, Jira, GitHub, Slack, Salesforce, Workday, …). These hold the **primary knowledge** and stay the **source of truth**: every lasting change is written here, and each system keeps controlling who may see what. An individual unit of that knowledge — a Confluence page, a Jira ticket, a Slack thread, a GitHub PR — is a **DS record** (data source record), the thing every summary, pointer, and confirmation ultimately refers back to.

2. **Discovery Layer (DL)** — a layer of *prepared material derived from the Data Sources*: summaries, indexes, pointers, and content-freshness/trust signals. Each such piece — a summary, an index, a pointer, a signal, the Catalog itself — is a **DL output**. Its whole reason to exist is to make relevant knowledge **easy to find and reuse**, so tools don't re-search everything from scratch. It is **derived** material — never primary knowledge authored for its own sake (that's a Data Source), and never a second source of truth. A quick test: a DL output exists only *because* there's something to discover — remove the underlying records and a summary, index, or signal has nothing left to describe.

   **Most** of it is *recomputable* — rebuilt from the sources on demand, so it's cheap to update and safe to discard. But **editing or verifying an output transfers ownership**: that copy becomes durable, exempt from future rebuilds, and backed up deliberately — like the parts people authored from scratch.

3. **Catalog** — the Discovery Layer's "yellow pages": one well-known place that maps a *topic* to *where its prepared material lives*. A tool does **one lookup**, then follows the pointer — instead of searching every system. Move a piece of material and you change one line in the Catalog, not the tools that use it.

4. **DL-creation skills** — the automated *producers*. Each reads the Data Sources, writes the Discovery Layer's prepared material, and keeps the Catalog current; each runs on its own service identity, on a schedule or on demand. **There are many, not one** — a given skill is customized to the kind of source data it handles, so it can process and validate that source the way its owning team needs.

5. **Query skills** — the *guides*. Given a question, a skill steers an AI agent to the right prepared material or the right source. They can only help an agent *find* answers faster — never widen access, because every search runs under the asking person's own permissions. **There are many, not one** — each covers a topic or question type. A skill built for a known topic can go straight to the relevant material, skipping the Catalog; the Catalog is the fallback for questions no skill already knows how to answer.

6. **Confirmation signals** — people vouching that the source behind an answer was right (or flagging it wrong). A confirmation attaches to a **cited DS record or DL output the answer drew from** — never to the AI's response text itself; that's why answers always cite their sources. This is one of the durable, people-sourced parts of the layer: it can't be re-derived, so it is kept and backed up deliberately.

Two relationships tie these together:

- The **DL-creation skill** takes **DS records** and creates **DL output**.
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
| DS records | The individual offices, where the real work and records are kept | The source of truth; each office controls who it lets in. |
| DL output | Handouts and digests *about* what the offices do — at reception, on floor screens, in a kiosk | Derived so you don't visit every office; most can be regenerated anytime. |
| Confirmation signals | Visitor feedback cards — "Suite 4B actually solved my problem" | People vouching an answer was good; kept on the card, not inside the office. |
| Catalog | The lobby directory — topic → where its handout is posted | The board everyone checks first; points to *where the handout lives*, not into the offices. |
| DL-creation skills | Information officers, each assigned to certain offices — they tour them, write the handouts, keep the directory current | Produce the derived material; each specializes in the offices it knows. |
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
