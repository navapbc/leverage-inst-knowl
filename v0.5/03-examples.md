# Examples — Mapping to Current Nava Solutions

*How the <u>Concepts</u> map to systems Nava already runs. Each solution has **its own DL-creation skill and its own Query skill**, specialized to its sources and questions — a concrete illustration that there are *many* of each skill, not one.*

## At a glance

| LIK concept | Project Indexes | OPIS PR assistant |
| --- | --- | --- |
| DS records | Confluence pages and uploaded artifacts from Slack | GitHub PRs |
| DL-creation skill | Knowledge Graph Bot via Slack | AWS Lambda |
| (DL output) Summaries & indexes | Confluence spaces (Project Index) | Retrieved chunks (must query vector DB) |
| (DL output) Retrieval hints & metadata | Confluence page labels, tags, metadata | Semantic embeddings and metadata in vector DB |
| DL Confirmation signals | manual validation? | (TODO) engineers like, dislike, comment on PRs |
| DL Catalog | Project Index Directory | Query vector DB |
| Query skill | Knowledge Graph Bot (via Slack) or Confluence Rovo | (TODO) chatbot UI and MCP service |

---

## [Project Indexes](https://navasage.atlassian.net/wiki/x/A4BGoQ)

* DS records: Confluence pages and uploaded artifacts from Slack
* DL-creation skill: Knowledge Graph Bot via Slack
* DL output
    * Summaries & indexes: Confluence spaces (Project Index)
    * Retrieval hints & metadata: Confluence page labels, tags, metadata (e.g., each space's [Update History](https://navasage.atlassian.net/wiki/spaces/PIVAAIS/pages/3078684730/Update+History))
* DL Confirmation signals: manual validation?
* DL Catalog: [Project Index Directory](https://navasage.atlassian.net/wiki/spaces/KGWS/pages/2705752067/Project+Index+Directory)
* Query skill: Knowledge Graph Bot (via Slack) or Confluence Rovo

### Yoom's preliminary testing on top of Project Indexes

* DS records, DL-creation skill, DL output: provided by Project Indexes
* DL Confirmation signals: TODO
* DL Catalog: adds Catalog entries via `sync-catalog-from-project-indexes`
* Query skill: `query-project-index`

---

## OPIS (RAG-based) PR assistant

* DS records: GitHub PRs
* DL-creation skill: AWS Lambda
* DL output
    * Summaries & indexes: retrieved chunks (must query vector DB)
    * Retrieval hints & metadata: semantic embeddings and metadata in vector DB
* DL Confirmation signals: (TODO) engineers to like, dislike, and comment on GitHub PRs
* DL Catalog: query vector DB
* Query skill: (TODO) chatbot UI and MCP service

### [In progress] OPIS Generalized

* DS records: GitHub, Confluence, Jira, and Slack
* DL-creation skill: AWS Lambda
* DL output: retrieved chunks + semantic embeddings/metadata in vector DB
* DL Confirmation signals: ?
* DL Catalog: via querying vector DB
* Query skill: (TODO) chatbot UI and MCP service

### Using a RAG-based solution as a Data Source

* DS records: the solution's vector DB
* DL-creation skill: the solution's ingestion into the vector DB
* DL output: index/summary of content + semantic embeddings/metadata
* DL Confirmation signals: add entry
* DL Catalog: add Catalog entries of summarized DL output
* Query skill: via MCP
