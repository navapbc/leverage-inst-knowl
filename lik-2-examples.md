How LIK concepts map to current Nava solutions. For the concepts themselves (and the office-building analogy), see [lik-1-overview.md](lik-1-overview.md).

Each solution below has **its own DL-creation skill and its own Query skill**, specialized to its sources and questions (e.g., Project Indexes' Knowledge Graph Bot vs. OPIS's AWS Lambda) — a concrete illustration that there are *many* of each skill, not one.
# Current Nava solutions

| LIK concept | Project Indexes | OPIS PR assistant |
| --- | --- | --- |
| DS records | Confluence pages and uploaded artifacts from Slack | GitHub PRs |
| DL-creation skill | Knowledge Graph Bot via Slack | AWS Lambda |
| (DL data) Summaries & indexes | Confluence spaces (Project Index) | Retrieved chunks (must query vector DB) |
| (DL data) Retrieval signals | Confluence page labels, tags, metadata | Semantic embeddings and metadata in vector DB |
| DL Confirmation signals | manual validation? | (TODO) engineers like, dislike, and comment on GitHub PRs |
| DL Catalog | Project Index Directory | Query vector DB |
| Query skill | Knowledge Graph Bot (via Slack) or Confluence Rovo | (TODO) chatbot UI and MCP service |

---

## [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ)
* DS records: Confluence pages and uploaded artifacts from Slack
* DL-creation skill: Knowledge Graph Bot via Slack
* DL data
    * Summaries & indexes: Confluence spaces (Project Index)
    * Retrieval signals: Confluence page labels, tags, metadata (e.g., each Confluence space's [Update History's ](https://navasage.atlassian.net/wiki/spaces/PIVAAIS/pages/3078684730/Update+History))
* DL Confirmation signals: manual validation?
* DL Catalog: [Project Index Directory](https://navasage.atlassian.net/wiki/spaces/KGWS/pages/2705752067/Project+Index+Directory)
* Query skill: Knowledge Graph Bot (via Slack) or Confluence Rovo

### (Yoom's preliminary testing on top of Project Indexes)
* DS records: (provided by Project Indexes)
* DL-creation skill: (provided by Project Indexes)
* DL data: (provided by Project Indexes)
* DL Confirmation signals: TODO
* DL Catalog: adds (Confluence) Catalog entries via `discovery-catalog-sync`
* Query skill: `dl-project-index-query`


---

## OPIS (RAG-based) PR assistant
* DS records: GitHub PRs
* DL-creation skill: AWS Lambda
* DL data
    * Summaries & indexes: retrieved chunks (must query vector DB)
    * Retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: (TODO) engineers to like, dislike, and comment on GitHub PRs
* DL Catalog: query vector DB
* Query skill: (TODO) chatbot UI and MCP service

## [In-progress] OPIS (RAG-based) Generalized
* DS records: GitHub, Confluence, Jira, and Slack
* DL-creation skill: AWS Lambda
* DL data
    * Summaries & indexes: retrieved chunks (must query vector DB)
    * Retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: ?
* DL Catalog: via querying vector DB
* Query skill: (TODO) chatbot UI and MCP service

## (Using RAG-based solution as a DS)
* DS records: solution's vector DB
* DL-creation skill: solution's ingestion into vector DB
* DL data
    * Summaries & indexes: index/summary of content in vector DB
    * Retrieval signals: semantic embeddings and metadata in vector DB
* DL Confirmation signals: add entry
* DL Catalog: add Catalog entries of summarized DL data
* Query skill: via MCP
