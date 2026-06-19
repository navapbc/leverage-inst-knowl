# Discovery Layer — Storage Reference

*The canonical reference for how each backing store behaves. The [overview](lik-1-overview.md), [architecture](lik-3-architecture-concise.md), and [strategy](lik-4-strategy.md) decide **which** output lands in **which** store; this file documents **how** each store behaves once chosen — so those docs can link here instead of repeating the mechanics.*

Discovery Layer (DL) outputs deliberately live in more than one store, picked by **who consumes the output** and **how much write-time integrity it needs**. Two properties drive every choice and recur throughout the other docs:

- **In-place update vs. create-only** — can a re-derivation revise the *same* artifact at a *stable* address, or does it spawn a new file each run? Anything DL refreshes on a schedule (signals, the catalog, confirmation tables, re-derived summaries) needs in-place update.
- **Versioned vs. non-versioned** — does the store give attribution, an audit log, and revert *for free*, or must a [governed-writer regime](#governed-writer-controls) supply them?

The three stores below sit at different points on both axes. (A warehouse — e.g. BigQuery — is a fourth option for machine signals at scale; its details stay in the [strategy doc's Parallel Track](lik-4-strategy.md).)

---

## Confluence pages

The default for anything human-readable and for small-scale tables.

| Property | Behavior |
|---|---|
| **Write model** | **In-place update** — each re-derivation revises the *same* page at a stable address, rather than spawning a new file. Tables (catalog, confirmations) are appended and de-duplicated against the same page. |
| **Versioning** | Native **version history** — supplies attribution, the audit log, and **revert as the recovery path**, with no extra machinery. |
| **Identity** | Edits are attributed to an SSO identity. A skill writes under a **non-human service account** (e.g. `summarizer@navapbc.com`) that appears in version history like any editor. |
| **Access enforcement** | Page/space restriction to a **Confluence group synced from a Google Group** (Atlassian Access / SCIM). *Prereq: Guard/SCIM group provisioning must be configured.* |
| **Governance** | Treated as **"just another DS artifact"** — no separate write-governance regime, because version history is the audit trail and revert is the recovery. For a shared single-entry artifact (the catalog), route every write through the skill service account — human-created rows come via a verified assertion (no direct editing), not from individual editors. |

**Used for:** human-readable artifacts (summaries, digests, curated indexes); the catalog at small scale; machine-signal and confirmation **tables at small scale**, before they outgrow a page.

---

## Google Drive / Docs / Sheets

| Property | Behavior |
|---|---|
| **Write model** | **Create-only** — the available Drive connector can *create* a file but **cannot update one in place**. Any output revised on each re-derivation therefore **cannot live in a Doc or Sheet**. This is the single reason Confluence, not a Doc/Sheet, backs every in-place-updated DL output. |
| **Versioning** | Drive has native version history, but the create-only limit makes it unusable as a re-derivation target regardless. |
| **Access enforcement** | Native sharing to a **Google Group** — direct, no sync layer. |

**Used for:** one-shot outputs that are written once and not revised in place (e.g. a Level 4 persisted synthesis saved as a Google Doc).

---

## Postgres (the service-fronted store)

The promotion target when a Confluence-page table outgrows its scale (beyond low-hundreds of subjects/pointers), when writers are untrusted, or when high-stakes ranking demands hard write-time enforcement.

| Property | Behavior |
|---|---|
| **Write model** | In-place; reached through an **MCP service** — the same interface agents use for the Data Sources. |
| **Versioning** | **Non-versioned** — no free attribution, audit log, or revert. It must add its **own audit columns** (`created_at` / `updated_at` / `updated_by`) and rely on **backup/retention** for recovery. |
| **Access enforcement** | No native Google Group grant. Needs a **`Google Group → Postgres role` bridge**, or a fronting service that resolves the caller's groups into a **row-level-security predicate**. (Index the access-group column — GIN in Postgres — for query-time filtering.) |
| **Governance** | A non-versioned store, so its writer runs under the [governed-writer controls](#governed-writer-controls). |
| **Backup/retention** | Required for any **non-recomputable** data it holds — confirmation signals and human-created artifacts. Recomputable rows (signals, catalog) recover by re-derivation instead. |

**Served through scoped tools, never raw SQL.** The MCP service exposes **intent-named tools** — e.g. `confirm_source`, `upsert_signal`, `register_catalog_entry` — each enforcing its own rules *at write time* (rate-limiting, de-duplication, "reject a confirmation whose citation doesn't resolve"). A generic `run_sql` would hand that enforcement back to the caller and forfeit the reason for moving off a page. The validation lives in the tool.

**Two writer modes:**
- **Service-only** — machine signals and catalog rows, written by the skill's service identity with no user in the loop.
- **Service + user assertion** — a write attributed to a verified user (e.g. a confirmation's `confirmed_by`, or a Level 4 row's `created_by`); the tool needs the user's token both to attribute the write and to rate-limit per person.

**Used for:** machine signals, the catalog, and confirmation tables at scale; high-stakes ranking; untrusted writers needing hard write-time enforcement.

---

## How a Google Group is honored, per store

Enforcement is always the **store's own native group/role grant** — there is no separate enforcement layer to keep in sync.

| Store | How a specified group is honored |
|---|---|
| **Google Drive / Docs / Sheets** | Native sharing to the Google Group — direct. |
| **Confluence** | Page/space restriction to a Confluence group synced from the Google Group (Atlassian Access / SCIM). *Prereq: Guard/SCIM provisioning configured.* |
| **Postgres** | A `Google Group → Postgres role` bridge, or a fronting service that resolves the caller's groups into a row-level-security predicate. |

Where a source isn't already group-based (Slack, Jira, Salesforce, Workday), an admin must provision a matching Google Group or the output stays default-deny.

---

## Governed-writer controls

The discipline every **non-versioned** store's writer runs under (Postgres here; a warehouse in the Parallel Track). The writer identity is a single point of failure — a compromised credential could poison access hints and trust signals for every query — so require:

- **No long-lived keys** (e.g. Workload Identity Federation).
- A **rotation schedule**.
- **Least privilege** — write only to the designated DL locations.
- **Audit logging** on every write.

Versioned stores (a Confluence page) are deliberately **not** under this regime: access is enforced at the target store and the skill's validate/re-derive pass replaces the service-account controls, with version-history revert as recovery.
