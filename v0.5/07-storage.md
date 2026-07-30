# Storage Reference

*How each backing store behaves once chosen. The <u>Architecture</u> and <u>Strategy</u> decide **which** resource lands in **which** store; this file documents **how** each store behaves — so those docs refer here instead of repeating the mechanics.*

Discovery Layer (DL) resources deliberately live in more than one store, picked by **who consumes the resource** and **how much write-time integrity it needs**. Two properties drive every choice:

- **In-place update vs. create-only** — can a re-derivation revise the *same* record at a *stable* address, or does it spawn a new file each run? Anything DL refreshes on a schedule (the Catalog, confirmation signals, re-derived summaries) needs in-place update.
- **Versioned vs. non-versioned** — does the store give attribution, an audit log, and revert *for free*, or must a governed-writer regime supply them?

The three stores below sit at different points on both axes.

---

## Confluence pages

The default for anything human-readable and for small-scale tables.

| Property | Behavior |
|---|---|
| **Write model** | **In-place update** — each re-derivation revises the *same* page at a stable address. |
| **Versioning** | Native **version history** — supplies attribution, the audit log, and **revert as recovery**, with no extra machinery. |
| **Identity** | Edits attributed to an SSO identity. A DL-creation skill writes under **its own credential** — typically a non-human service account (e.g., `summarizer@navapbc.com`), separate from the service-fronted store's governed writer — appearing in version history like any editor. The writing identity is **not** what marks provenance (that rides on change-detection, <u>Architecture</u> §5), so it is not architecturally fixed. |
| **Access enforcement** | Page/space restriction to a **Confluence group synced from a Google Group** (Atlassian Access / SCIM). *Prereq: Guard/SCIM group provisioning configured.* |
| **Governance** | Treated as **"just another DS record"** — no separate write-governance regime, because version history is the audit trail and revert is recovery. |

**Used for:** summaries, indexes, and other human-readable DL resources. *(The Catalog and confirmation signals are not stored here — they need keyed lookup and write-time enforcement, so they live in the service-fronted store below.)*

---

## Google Drive / Docs / Sheets

| Property | Behavior |
|---|---|
| **Write model** | **Create-only** — the available Drive connector can *create* a file but **cannot update one in place**. Any output revised on each re-derivation therefore **cannot live in a Doc or Sheet**. This is the single reason Confluence, not a Doc/Sheet, backs every in-place-updated DL resource. |
| **Versioning** | Drive has native version history, but the create-only limit makes it unusable as a re-derivation target regardless. |
| **Access enforcement** | Native sharing to a **Google Group** — direct, no sync layer. |

**Used for:** one-shot outputs written once and not revised in place (e.g., a Level 4 persisted synthesis saved as a Google Doc).

---

## Postgres (the service-fronted store)

The home for DL's structured data — the **Catalog** and **confirmation signals** — reached through an MCP service. Both need keyed lookup, write-time enforcement, and (for confirmations) untrusted-writer controls, so they live here from the start.

| Property | Behavior |
|---|---|
| **Write model** | In-place; reached through an **MCP service** — the same interface agents use for the Data Sources. |
| **Versioning** | **Non-versioned** — no free attribution, audit log, or revert; it carries explicit `created_at` / `updated_at` / `updated_by` audit columns and relies on **backup/retention** for recovery. |
| **Access enforcement** | No native Google Group grant. Needs a **`Google Group → Postgres role` bridge**, or a fronting service that resolves the caller's groups into a **row-level-security predicate**. (Index the access-group column — GIN — for query-time filtering.) |
| **Governance** | A non-versioned store, so its writer runs under the governed-writer controls. |
| **Backup/retention** | Required for the **non-recomputable** data it holds — confirmation signals, plus any human-created Catalog rows a non-versioned store can't revert. Skill-computed signals and Catalog rows recover by re-derivation; human-created/verified *records* aren't stored here — they live in a DS, which backs them up. |

**Served through scoped tools, never raw SQL.** The MCP service exposes **intent-named tools** — e.g., `confirm_source`, `register_catalog_entry` — each enforcing its own rules *at write time* (rate-limiting, de-duplication, "reject a confirmation whose citation doesn't resolve"). A generic `run_sql` would hand that enforcement back to the caller and forfeit the reason for moving off a page.

**Vector-DB variant for the Catalog (opt-in).** The Catalog store may instead be a vector DB (or Postgres with `pgvector`) that embeds each DL record's text, so a consumer can match a *fuzzy* question by similarity rather than only by exact key. It sits behind the same scoped MCP tools — `register_catalog_entry` still writes rows; a similarity-search capability is added alongside keyed lookup. It can be **added later, not up front**: the embedding is a rebuildable index over text the row's pointer can always re-fetch, so enabling it is a non-destructive column-add plus a backfill — nothing at cataloging time must be preserved for it. The variant carries extra obligations implementers must meet (semantics in <u>Architecture</u> §3):
- **Keyed lookup still required** — exact `(entry_type, subject)` retrieval via metadata filtering stays the floor; similarity is additive, and no consumer may assume it exists.
- **Embed DL-record text only** — never raw Data-Source content, which would rebuild the index-based-copy custody risk of the Level 0 tools (<u>Strategy</u> Level 0).
- **Access-group pre-filter** — restrict candidates to the caller's groups (the row-level-security predicate above) *before* similarity ranking; an unfiltered hit leaks record text, not just a pointer.
- **Partition by sensitivity** — keep `restricted` and `cleared` vectors in separate indexes; embeddings can leak the content they encode, so a mixed index takes on its most-restricted member's sensitivity. **Settle this before embedding restricted content**: unlike enabling the variant itself, separating vectors that were already co-mingled is not a trivial retrofit.
- **Re-embed on re-derivation** — refresh a record's vector when its content-state changes, or the similarity match goes stale (freshness handled as in <u>Architecture</u> §2).

**Two governed-writer modes** (both writes go through the single governed writer; they differ only in whether a user is attributed):
- **Autonomous** — Catalog rows the registrar derives, with no user in the loop.
- **User-attributed** — a write attributed to a verified user (a confirmation's `confirmed_by`, or a human-owned row's `updated_by`); the governed writer still performs the write, but needs the user's token both to attribute it and to rate-limit per person.

**Used for:** the Catalog and confirmation signals; high-stakes ranking; untrusted writers needing hard write-time enforcement.

---

## How a Google Group is honored, per store

Enforcement is always the **store's own native group/role grant** — no separate enforcement layer to keep in sync.

| Store | How a specified group is honored |
|---|---|
| **Google Drive / Docs / Sheets** | Native sharing to the Google Group — direct. |
| **Confluence** | Page/space restriction to a Confluence group synced from the Google Group (Atlassian Access / SCIM). *Prereq: Guard/SCIM provisioning configured.* |
| **Postgres** | A `Google Group → Postgres role` bridge, or a fronting service that resolves the caller's groups into a row-level-security predicate. |

Where a source isn't already group-based (Slack, Jira, Salesforce, Workday), an admin must provision a matching Google Group or the output stays default-deny.

---

## Governed-writer controls

The discipline every **non-versioned** store's writer runs under (Postgres here; a warehouse in the Parallel Track). One **governed writer** serves the whole store — the Catalog and confirmation signals alike (defined in <u>Access Control</u>). The writer identity is a single point of failure — a compromised credential could poison access hints and trust signals for every query — so require:

- **No long-lived keys** (e.g., Workload Identity Federation).
- A **rotation schedule**.
- **Least privilege** — write only to the designated DL locations.
- **Audit logging** on every write.

Versioned stores (a Confluence page) are deliberately **not** under this regime: a DL-creation skill writes there under its own credential (typically a service account), access is enforced at the target store, and the skill's validate/re-derive pass replaces the governed-writer controls, with version-history revert as recovery.
