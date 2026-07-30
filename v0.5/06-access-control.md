# Access Control & Identity

*How access is enforced and how identity travels through the system. Per-store mechanics (how each store honors a group, governed-writer controls) are in <u>Storage</u>.*

## Model: Google SSO + Google Groups

The whole design reuses the existing Google sign-in rather than standing up a new identity or permission system. Access is **always enforced by the system that owns the data**, never by the Discovery Layer's own metadata.

**For Data Sources:** sensitive data stays protected by the source app; roles via Groups where possible; Groups attached to DS data when supported. Where not supported, an **admin mapping process** with a **named owner**, **default-deny** for unmatched records, and **most-restrictive-wins** conflict resolution. Mapping criteria: source DS, tag/label, category, project/client/team/function, governance rule.

Most DSs don't express permissions as Google Groups (Slack channels, Atlassian roles, Salesforce profiles, Workday models). For each DS feeding a *materialized* DL store, document whether Group attachment is possible and, where not, how native ACLs normalize. There the mapping is the **primary** mechanism.

**For the Discovery Layer:** propagated ACL metadata is used for routing only; real enforcement is the target store's. Where a record lives in a DS, that DS's native permissions enforce. Write governance is per store (see <u>Storage</u>).

## Identity rules

- **Read:** MCP services require a **verified Google OIDC/OAuth token** (audience-validated); the verified email *claim* authorizes access. Identity is carried across each `agent → MCP → DS` hop via **on-behalf-of token exchange** — each MCP service obtains a store-native **per-user** identity, since a DS won't accept a Google-audience token directly. **How** it obtains one varies by DS and must be confirmed per connector: some support direct token exchange, others require a one-time per-user OAuth consent with a stored refresh token, and some have no per-user delegation path at all. A DS in that last category cannot be read under per-user enforcement and is **out of scope until one exists** — never fall back to a shared service identity for user reads. Applies equally to AI agents and automation (e.g., Zapier).
- **Write to DSs:** the user's verified SSO identity, via the DS's normal permissions.
- **Write to DL:** depends on the store —
  - *Service-fronted store* (non-versioned): **the governed writer** — one identity for the Catalog and confirmation signals alike (defined below).
  - *Version-history DS* (Confluence): ordinary DS edit under SSO; a DL-creation skill writes under **its own credential** (typically a non-human service account) — a **separate** identity from the governed writer, not under the governed-writer regime.
  - A skill writing summaries & indexes into a DS needs **least-privilege native edit access** to the locations it writes.

**Identity is never self-asserted.** An email is an identifier, never an authenticator. Every call carries a verified token, never a claimed name.

## The permission-freshness contract

This is about **permission freshness** — whether access has been revoked — a separate concern from the **content freshness** described in <u>Architecture</u>. The two have opposite risk profiles and refresh on independent cycles.

Propagated ACL metadata is a **cache**; a stale cache leaks access after revocation. **Permission refresh is decoupled from content-staleness refresh.** For sensitive categories, DL either re-validates against the live DS/Group at query time, or enforces a **maximum propagation lag** with a **fail-closed default**.

The skill must capture each item's **source ACL at read time** — failure silently widens access.

## Computed / aggregated records

A cross-DS aggregation has no single source ACL. Rather than computing a most-restrictive intersection at runtime, each materialized output is assigned **one sensitivity tier / audience group** named by the skill author (**default-deny** until cleared). Blending tiers in one output is a smell — split the output.

A genuinely cross-tier output is served either by an **admin-provisioned audience group** whose membership *is* the intended union, or — absent a standing audience — by storing **pointers/instructions** directing permitted users to recompute under their own SSO at query time. The skill never computes an intersection. Before writing, the skill asserts the named group is no broader than every input source's audience; on failure the output stays default-deny.

**User-saved syntheses (Level 4) differ.** A person, not a skill, authors the record, so there is no skill author to name the group ahead of time. The **saving user sets the audience** under their own SSO and is **responsible** for choosing one no broader than the sources the synthesis drew on (**default-deny** if they specify nothing). The skill may surface the sources' restrictions to inform that choice, but it never sets access itself. The cross-tier caution above still applies — the user makes the call.

## Three sharing states

Every DL resource carries one of:

1. **Shared with a specified Google Group** — the group that should see it.
2. **Explicitly unrestricted** — an affirmative flag set to open the output org-wide.
3. **Unspecified → default-deny** — shared only with a restricted fallback group. Absence of a decision is never "open."

Enforcement is the **store's own native group/role grant** (mechanics per store in <u>Storage</u>). Where a source isn't already group-based, an admin must provision a matching Google Group or the output stays default-deny.

## The governed writer (service-fronted store)

**One non-human identity writes everything in the service-fronted store.** The Catalog and confirmation signals share a **single governed writer** — the store's only writer, which no user connects as directly. Skills reach it through the store's MCP interface. It does **not** impersonate individual users, and there is **not** a separate identity per skill or per kind of row: which skill produced a row, and whether a row is skill- or human-owned, is recorded in the row's own provenance, never by using distinct writer accounts.

*Everything below is written under that one identity:*
- a **Catalog pointer** the registrar derived from a discovered DL record — a skill-owned row;
- a **Catalog pointer** for a synthesis a user opted to register — a human-owned row that records the registering user as its creator;
- a **confirmation signal** capturing a user's vouch — recording the user it was confirmed by.

What separates these is data on the row (who created it, whether skill- or human-owned), not a distinct credential. This one writer is a single point of failure — a compromised credential poisons ACLs, hints, and trust for every query — so it runs under: **no long-lived keys** (e.g., Workload Identity Federation), a **rotation schedule**, **least privilege** (write only to designated DL locations), and **audit logging** on every write. Full mechanics in <u>Storage</u>.

**DL resources in a version-history DS (summaries, indexes) are deliberately *not* under this regime** — a DL-creation skill writes them under its own credential (typically a service account, a **separate** identity from the governed writer); access is enforced at the target store, and the DL-creation skill's re-derive pass and the registrar's validation pass replace the governed-writer controls, with version-history revert as recovery. The **Catalog and confirmation signals**, by contrast, live in the service-fronted store and *do* run under these controls; their non-recomputable data recovers by backup, not revert.

## Third-party integration trust boundary

External tools (Glean, GoSearch, self-hosted platforms) are a distinct trust zone. Because DL aggregates across DSs, connecting one uncontrolled tool creates a bulk re-export path for source-restricted data. For each external consumer define: **credential scope** (least-privilege slice), **data minimization** (which portion of DL, not all), **retention/training constraints**, and **breach containment**.

A tool querying under its own service credentials must faithfully proxy the end-user's identity so DL enforcement isn't bypassed — **enforced, not assumed**: require a verifiable end-user assertion (signed user token / OBO) and **reject any request carrying only a service credential with no user identity**.
