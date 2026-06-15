Following are examples of how LIK concepts map to current solutions.

- *DL skill* takes *DS records* and creates *DL data*
- *Organization skill* queries *DL data* and *DS records* to answer user questions/requests

| LIK concept | Project Indexes | OPIS PR assistant |
| --- | --- | --- |
| DS records | Confluence pages and uploaded artifacts from Slack | GitHub PRs |
| DL skill | Knowledge Graph Bot via Slack | AWS Lambda |
| (DL data) Human-readable artifacts | Confluence spaces (Project Index) | Retrieved chunks (must query vector DB) |
| (DL data) Machine retrieval signals | Confluence page labels, tags, metadata | Semantic embeddings and metadata in vector DB |
| DL Confirmation signals | Each Confluence space's Update History | (TODO) engineers like, dislike, and comment on GitHub PRs |
| DL Catalog | Project Index Directory | Query vector DB |
| Organization skill | Knowledge Graph Bot (via Slack) or Confluence Rovo | (TODO) chatbot UI and MCP service |

---

### [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ)
* DS records: Confluence pages and uploaded artifacts from Slack
* DL skill: Knowledge Graph Bot via Slack
* DL data
    * Human-readable artifacts: Confluence spaces (Project Index)
    * Machine retrieval signals: Confluence page labels, tags, metadata (e.g., each Confluence space's [Update History's ](https://navasage.atlassian.net/wiki/spaces/PIVAAIS/pages/3078684730/Update+History))
* DL Confirmation signals: N/A
* DL Catalog: [Project Index Directory](https://navasage.atlassian.net/wiki/spaces/KGWS/pages/2705752067/Project+Index+Directory)
* Organization skill: Knowledge Graph Bot (via Slack) or Confluence Rovo

#### (Yoom's preliminary testing on top of Project Indexes)
* DS records: (provided by Project Indexes)
* DL skill: (provided by Project Indexes)
* DL data: (provided by Project Indexes)
* DL Confirmation signals: TODO
* DL Catalog: adds (Confluence) Catalog entries via `discovery-catalog-sync`
* Organization skill: `dl-project-index-query`


---

### OPIS (RAG-based) PR assistant
* DS records: GitHub PRs
* DL skill: AWS Lambda
* DL data
    * Human-readable artifacts: retrieved chunks (must query vector DB)
    * Machine retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: (TODO) engineers to like, dislike, and comment on GitHub PRs
* DL Catalog: query vector DB
* Organization skill: (TODO) chatbot UI and MCP service

### [In-progress] OPIS (RAG-based) Generalized
* DS records: GitHub, Confluence, Jira, and Slack
* DL skill: AWS Lambda
* DL data
    * Human-readable artifacts: retrieved chunks (must query vector DB)
    * Machine retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: ?
* DL Catalog: via querying vector DB
* Organization skill: (TODO) chatbot UI and MCP service

### (Using RAG-based solution as a DS)
* DS records: solution's vector DB
* DL skill: solution's ingestion into vector DB
* DL data
    * Human-readable artifacts: index/summary of content in vector DB
    * Machine retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: add entry
* DL Catalog: add Catalog entries of summarized DL data
* Organization skill: via MCP



---

Template -- Solution X
* DS records: 
* DL skill: 
* DL data
    * Human-readable artifacts: 
    * Machine retrieval signals: 
* DL Confirmation signals:
* DL Catalog: 
* Organization skill:

