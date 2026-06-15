Following are examples of how LIK concepts map to current Nava solutions.

- *DL-creation skill* takes *DS records* and creates *DL data*
- *Query skill* queries *DL data* and *DS records* to answer user questions/requests

### Analogies (intuition)

**A library.** This one is almost literal — a library's card catalog *is* a catalog.

| LIK concept | Library | Why it fits |
| --- | --- | --- |
| DS records | The books and archives on the shelves | Where the actual content lives and is updated — the source of truth. |
| DL data | The librarian's summaries, study guides, and "new this week" displays | Derived from the books to save you reading them; can always be rebuilt from the shelves, never replaces them. |
| Confirmation signals | Reader review slips — "this book answered my question" | Humans vouching that an answer was *actually* good; this lives on the slip, not inside the book. |
| Catalog | A directory of the librarian's *guides* — which guide exists and where it's posted | Indexes the derived guides and their **locations**, not the books' contents; re-post a guide elsewhere and only this one directory line changes. (Note: *not* the card catalog — that indexes books, i.e. DS content.) |
| DL-creation skill | The librarian who reads the books and writes the guides | Produces the derived material. |
| Query skill | The reference librarian who knows which section to send you to | Steers your search; never decides what you're *allowed* to read (that's the library's own rules). |

A nuance from the strategy: a book can carry its *own* "peer-reviewed" stamp (trust native to the DS), separate from reader slips (DL confirmation signals) — and the reference librarian weighs both.

**A restaurant.** The **kitchens** cook the real food (DS). A **meal-prep service** turns that into ready-to-eat boxes and a tasting menu (DL). **Diner reviews** say which dishes were actually good (confirmation signals). A **directory at the pickup counter** — "boxed salads: case 3; tasting menu: shelf B" — tells you where each *prepped* item sits (catalog); it points at the boxes, not the recipes.

**Maps / GPS.** The **physical streets and buildings** are the ground truth (DS). A **map** is a derived, simplified rendering kept in sync with reality (DL). **User reports** — "this road is closed," "great coffee here" — are confirmation signals. An **atlas's index** — "this region is on sheet 42" — is the catalog: it tells you which derived map sheet to open, not what's on the ground.

**On the catalog specifically** (the easy one to get backwards): it indexes *where DL outputs live*, not what's inside the sources — like a **building's lobby directory** (Company → Suite 4B). It sends you to the right office without describing what the company does, and when a tenant moves you change one line, not the offices. In every analogy above, "catalog" is this kind of location directory over the *derived* artifacts — never an index of raw DS content.

---

## Current Nava solutions

| LIK concept | Project Indexes | OPIS PR assistant |
| --- | --- | --- |
| DS records | Confluence pages and uploaded artifacts from Slack | GitHub PRs |
| DL-creation skill | Knowledge Graph Bot via Slack | AWS Lambda |
| (DL data) Human-readable artifacts | Confluence spaces (Project Index) | Retrieved chunks (must query vector DB) |
| (DL data) Machine retrieval signals | Confluence page labels, tags, metadata | Semantic embeddings and metadata in vector DB |
| DL Confirmation signals | manual validation? | (TODO) engineers like, dislike, and comment on GitHub PRs |
| DL Catalog | Project Index Directory | Query vector DB |
| Query skill | Knowledge Graph Bot (via Slack) or Confluence Rovo | (TODO) chatbot UI and MCP service |

---

### [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ)
* DS records: Confluence pages and uploaded artifacts from Slack
* DL-creation skill: Knowledge Graph Bot via Slack
* DL data
    * Human-readable artifacts: Confluence spaces (Project Index)
    * Machine retrieval signals: Confluence page labels, tags, metadata (e.g., each Confluence space's [Update History's ](https://navasage.atlassian.net/wiki/spaces/PIVAAIS/pages/3078684730/Update+History))
* DL Confirmation signals: manual validation?
* DL Catalog: [Project Index Directory](https://navasage.atlassian.net/wiki/spaces/KGWS/pages/2705752067/Project+Index+Directory)
* Query skill: Knowledge Graph Bot (via Slack) or Confluence Rovo

#### (Yoom's preliminary testing on top of Project Indexes)
* DS records: (provided by Project Indexes)
* DL-creation skill: (provided by Project Indexes)
* DL data: (provided by Project Indexes)
* DL Confirmation signals: TODO
* DL Catalog: adds (Confluence) Catalog entries via `discovery-catalog-sync`
* Query skill: `dl-project-index-query`


---

### OPIS (RAG-based) PR assistant
* DS records: GitHub PRs
* DL-creation skill: AWS Lambda
* DL data
    * Human-readable artifacts: retrieved chunks (must query vector DB)
    * Machine retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: (TODO) engineers to like, dislike, and comment on GitHub PRs
* DL Catalog: query vector DB
* Query skill: (TODO) chatbot UI and MCP service

### [In-progress] OPIS (RAG-based) Generalized
* DS records: GitHub, Confluence, Jira, and Slack
* DL-creation skill: AWS Lambda
* DL data
    * Human-readable artifacts: retrieved chunks (must query vector DB)
    * Machine retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: ?
* DL Catalog: via querying vector DB
* Query skill: (TODO) chatbot UI and MCP service

### (Using RAG-based solution as a DS)
* DS records: solution's vector DB
* DL-creation skill: solution's ingestion into vector DB
* DL data
    * Human-readable artifacts: index/summary of content in vector DB
    * Machine retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: add entry
* DL Catalog: add Catalog entries of summarized DL data
* Query skill: via MCP



---

Template -- Solution X
* DS records: 
* DL-creation skill: 
* DL data
    * Human-readable artifacts: 
    * Machine retrieval signals: 
* DL Confirmation signals:
* DL Catalog: 
* Query skill:

