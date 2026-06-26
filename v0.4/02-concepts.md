# Core Concepts

*The vocabulary used throughout these docs, in plain language. For the technical design, see <u>Architecture</u>.*

## The concepts and terminology

1. **Data Sources (DSs)** — the systems where knowledge is actually created, corrected, and governed (Drive, Confluence, Jira, GitHub, Slack, Salesforce, Workday, …). These hold the **primary knowledge** and stay **authoritative** for it: every lasting change is written here, and each system keeps controlling who may see what. An individual unit stored in a DS — a Confluence page, a Jira ticket, a Slack thread, a GitHub PR — is a **DS record**. Most DS records are primary knowledge; but a Discovery-Layer summary, index, or signal written into a DS is *also* a DS record (below) — stored and backed up by the DS like any other, yet marked as derived and never authoritative.

2. **Discovery Layer (DL)** — *prepared material derived from the Data Sources* whose only job is to make knowledge **easy to find and reuse**, so tools don't re-search everything from scratch. Each piece is a **DL output**. It is **derived** material — never primary knowledge authored for its own sake, and never a competing authority. (A quick test: remove the underlying records and a DL output has nothing left to describe.)

   By **where it lives and who keeps it safe**, every DL output is one of three:
   - **A DS record** — the common case, and most of DL: a summary, index, pointer, or signal written into a Data Source (such as a Confluence page) and marked `discovery-layer`. Because it lives in a Data Source, **that source stores and backs it up** like any record, and reverting to an earlier version is its recovery. Most are rebuilt from the sources on demand; once a person edits or verifies one, the rebuild leaves that copy alone instead of regenerating it.
   - **The Catalog** — one well-known directory mapping a *topic* to *where its material lives*, so a tool does **one lookup** then follows the pointer instead of searching every system (move a piece and you change one line, not the tools). It's built only from the `discovery-layer` DS records — not the full sources — so there's far less to process. Those records hold the same "what exists and where" at finer granularity; the Catalog is the coarse, topic-level view over them, recomputed rather than backed up.
   - **Confirmation signals** — people vouching that the source behind an answer was right (or flagging it wrong). A confirmation attaches to the **cited DS record or DL output the answer drew from**, never to the AI's response text — which is why answers always cite their sources. A **Query skill** records one when a person gives positive or negative feedback on a cited source. It can't be re-derived, so it's the **one part of DL that must be kept deliberately** rather than simply rebuilt.

3. **DL-creation skills** — the automated *producers*. Each reads the Data Sources, writes DL outputs, and keeps the Catalog current; each runs on its own service identity, on a schedule or on demand. **There are many, not one** — a given skill is customized to the kind of source data it handles, so it can process and validate that source the way its owning team needs.

4. **Query skills** — the *guides*. Given a question, a skill steers an AI agent to the right material or the right source. Mostly they only help an agent *find* answers faster — never widen access, because every search runs under the asking person's own permissions. The one thing they produce is a **confirmation signal**: when a person gives feedback on a cited source, the skill records it. **There are many, not one** — each covers a topic or question type. A skill built for a known topic can go straight to the relevant material, skipping the Catalog; the Catalog is the fallback for questions no skill already knows how to answer.

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
| DS records | The individual offices, where the real work and records are kept | Authoritative for what they hold; each office controls who it lets in. |
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
