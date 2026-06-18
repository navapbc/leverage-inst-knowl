---
date: 2026-06-18
topic: postgres-mcp-connector
---

# Implementation Plan — Postgres MCP Connector and the Skill That Uses It

A high-level roadmap for building the **service-fronted store** defined in [lik-strategy.md §2.6](../../lik-strategy.md): one MCP service in front of a Postgres database, plus the skills that write to and read from it. This plan covers all three Discovery Layer (DL) output types — **catalog, machine retrieval signals, and confirmations** — in a single service from the start.

This is a roadmap, not an engineering spec: it sets phases, decisions, and success criteria, and leaves tool schemas and table designs to the build phase.

---

## 1. What we're building, in plain terms

Today the DL's catalog, signals, and confirmations can live on Confluence pages. As they grow, they move into a database we own. We do **not** let the AI talk to that database directly. Instead we put a small **service** in front of it that speaks MCP — the same interface agents already use to reach Google Drive, Confluence, and the other source systems. The service offers a short menu of specific actions ("record this confirmation," "register where this output lives") and does the database work itself.

Two pieces, then:

- **The connector** — the MCP service plus its Postgres database. It owns every read and write, and enforces the rules.
- **The skill** — the instructions that tell an agent *when* and *how* to call the connector. There are two skill roles, both already named in the strategy: the **DL-creation skill** that writes outputs (the producer) and the **Query skill** that reads them at question time (the consumer).

The goal a non-technical reader should take away: the database stays behind a wall, the AI only ever uses a fixed set of safe actions, and everything is logged.

---

## 2. What's already decided (so we don't relitigate it)

These come straight from the strategy and are inputs to the plan, not open questions:

- **One service, three output types**, with separate database roles and tables per type to limit the damage if one is compromised (§2.1, §2.6).
- **Scoped actions, never raw SQL.** Each action enforces its own rules at the moment of writing. This is the entire reason for moving off a Confluence page (§2.6, §3.1).
- **Two writer modes:** the producer skill writes signals and catalog rows under a *service* identity with no user involved; confirmations are written by the service but carry the *confirming user's* verified identity (§2.6, §3.1).
- **Reads honor the group-share model** via a Google Group → Postgres row-access mapping (§2.3, §2.6).
- **Confirmations are durable and non-recomputable** and need their own backup; signals and catalog rows can be rebuilt from the source systems (§2.6, §3.1).

---

## 3. Platform assumptions and the GCP dependency

The connector's language and host are left open — it can run on any runtime. But two dependencies inherit from the strategy and are not free choices:

- **Identity is Google-based.** Sign-in is Google SSO and audiences are Google Groups. The connector must accept a verified Google token and read the caller's group membership.
- **Access control needs a Google Group → Postgres role bridge.** This is the one place GCP/Google is unavoidable: something must translate "this caller is in Group X" into "this caller may read these rows." Whether that lives in the connector or in a small sidecar is an open decision (§5).

Everything else — the database engine (Postgres), the MCP framework, the deployment target — is a build-team choice. Note that the strategy names BigQuery as the *warehouse* option for the parallel reporting track; that is separate from this Postgres store and not in scope here.

---

## 4. Open decisions to make before building

- **Runtime and MCP framework** for the connector (language, official MCP SDK vs. custom).
- **Where the group→role bridge lives** — inside the connector resolving groups into a row filter at query time, or a provisioned `Google Group → Postgres role` grant maintained out of band.
- **Hosting and credential model** — confirm the keyless-credential mechanism (the strategy's example is Workload Identity Federation) and where audit logs land.
- **Backup/retention specifics** for the confirmation tables — frequency, retention window, and who owns recovery.
- **Build order across the three output types** — even building all three, we should sequence which goes to production first (recommendation in §8).

---

## 5. The connector (MCP service + Postgres)

**Responsibilities the service owns end to end:**

- Exposing a small set of **named actions** — roughly: register a catalog entry, look up a catalog entry, write/update a retrieval signal, read signals, record a confirmation, read confirmations. Each action validates its own inputs and runs fixed, parameterized queries.
- **Authenticating every call** with a verified Google token and rejecting any request that lacks one.
- **Resolving the caller's groups into a row filter on reads**, so a caller only ever sees rows their groups permit (the §2.3 model).
- **Enforcing write rules** that are the reason this store exists: for confirmations, at most one per user per cited source-version, a citation that actually resolves, and rate-limiting/de-duplication; for catalog rows, validating pointers and re-deriving skill-owned rows.
- **Running under governed-writer controls** on its database connection: keyless rotated credentials, least privilege, and audit logging on every write.

**Two writer modes the service must support:**

- *Service-only* — signals and catalog rows. The producer skill's service identity writes; no end user is involved.
- *Service + user assertion* — confirmations. The service account performs the write but records the confirming user's verified identity (`confirmed_by`) and uses the user token to attribute and rate-limit. This is a different shape from the Level 1 connectors, which pass the user's identity straight through to a source system; here the service writes under its *own* identity to a store we own.

---

## 6. The data (three groups, different durability)

Three logical groups of tables behind the one service, each with its own database role:

- **Catalog** — the "yellow pages" mapping `type + subject → location`. Low volume. Skill-owned rows are re-derived each run; a few hand-authored rows rely on revert. Recomputable.
- **Machine retrieval signals** — indexes, pointers, freshness/obsolescence hints, updated in place. Recomputable from the source systems.
- **Confirmations** — durable human trust signals that exist in no source system. **Not recomputable** — these alone need real backup/retention, and revert is the only recovery.

Detailed columns and schema are deferred to the build phase; the strategy's catalog schema reference is in lik-architecture-concise.md §2.

---

## 7. The skill side

- **DL-creation skill (producer).** Runs on a schedule or on demand under its service identity. After computing an output, it calls the connector to register the catalog entry and write the signal — it never writes to Postgres directly. For confirmations, the agent calls the connector's confirm action when a user signals trust (a button, or "yes, that's right" in conversation), passing the user's verified identity.
- **Query skill (consumer).** Runs under the *user's* SSO at question time. It reads signals and confirmations through the connector to shape ranking, and (once the catalog is promoted) consults the catalog first to find where an output lives. Because it runs as the user, it only ever sees rows the group model permits.

The skill work is mostly instructions plus the calls to the connector's actions; the enforcement and data handling live in the connector, not the skill.

---

## 8. Phased roadmap

Building all three output types, but sequenced so the simplest, recomputable case proves the path before we take on durable data.

**Phase 0 — Foundations.** Stand up Postgres, the empty MCP service skeleton, Google-token verification, and the group→role bridge. Decide the open items in §4. *Done when* a no-op authenticated call works end to end and an unauthenticated call is rejected.

**Phase 1 — Signals (recomputable, lowest risk).** Add the write/read signal actions and wire the producer skill to register signals and catalog pointers for them. *Done when* the producer writes signals through the connector and a Query skill reads them under the user's identity, with reads correctly filtered by group.

**Phase 2 — Catalog.** Add register/lookup catalog actions and the per-run validate-and-re-derive behavior. Preserve a stable well-known address so the backing store can change without breaking consumers. *Done when* a consumer resolves `(type, subject) → location` through one lookup and a missing row degrades to fallback rather than an error.

**Phase 3 — Confirmations (durable, hardest enforcement).** Add the confirm action with the full write-time rules (one-per-user-per-version, citation must resolve, rate-limit/de-dup, `confirmed_by` attribution) and the backup/retention regime. *Done when* duplicate and unresolved-citation confirmations are rejected, valid ones are attributed and counted, and a restore from backup has been tested.

**Phase 4 — Hardening and handoff.** Confirm audit logging, credential rotation, least-privilege roles per output type, and the §3.3 upkeep mechanisms (age-out window, back-propagation to the source record). *Done when* a security review passes and ownership is assigned.

---

## 9. How we'll know it worked (verification per phase)

- **Auth:** every action rejects calls with no verified user; reads return only group-permitted rows (test with two users in different groups).
- **No raw SQL surface:** confirm the service exposes only the named actions — there is no general query action to misuse.
- **Write enforcement:** automated tests for duplicate confirmations, unresolved citations, and rate limits.
- **Recompute vs. restore:** prove signals and catalog rebuild from source; prove confirmations restore from backup (they cannot be rebuilt).
- **Consumer fallback:** a missing or malformed catalog row falls back to Query-skill routing instead of erroring.

---

## 10. Risks to watch

- **Tool creep toward generic writes.** The moment someone adds a convenience "run this query" action, the enforcement guarantee is gone. Keep actions intent-named and narrow.
- **Group→role drift.** If group membership and row access fall out of sync, reads either leak or over-restrict. The bridge needs an owner and a sync check.
- **Confirmations are a one-way commitment.** They can't be rebuilt; a lost backup is lost trust data. Treat their backup as the highest-stakes item in the plan.
- **Scope pressure from the warehouse track.** Keep this Postgres store distinct from the BigQuery reporting warehouse; they share the MCP interface but not the data or the writers.

---

## 11. Open questions for the team

- Does the group→role bridge live in the connector or as provisioned Postgres grants?
- What is the confirmation backup window and recovery owner?
- Which runtime/MCP framework, and where does it deploy?
- Who owns the connector and the producer skill once Phase 4 hands off?
