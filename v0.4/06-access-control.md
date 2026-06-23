# Access Control & Identity

*How access is enforced and how identity travels through the system. Per-store mechanics (how each store honors a group, governed-writer controls) are in <u>Storage</u>.*

## Model: Google SSO + Google Groups

The whole design reuses the existing Google sign-in rather than standing up a new identity or permission system. Access is **always enforced by the system that owns the data**, never by the Discovery Layer's own metadata.

**For Data Sources:** sensitive data stays protected by the source app; roles via Groups where possible; Groups attached to DS data when supported. Where not supported, an **admin mapping process** with a **named owner**, **default-deny** for unmatched records, and **most-restrictive-wins** conflict resolution. Mapping criteria: source DS, tag/label, category, project/client/team/function, governance rule.

Most DSs don't express permissions as Google Groups (Slack channels, Atlassian roles, Salesforce profiles, Workday models). For each DS feeding a *materialized* DL store, document whether Group attachment is possible and, where not, how native ACLs normalize. There the mapping is the **primary** mechanism.

**For the Discovery Layer:** propagated ACL metadata is used for routing only; real enforcement is the target store's. Where an artifact lives in a DS, that DS's native permissions enforce. Write governance is per store (see <u>Storage</u>).

## Identity rules

- **Read:** MCP services require a **verified Google OIDC/OAuth token** (audience-validated); the verified email *claim* authorizes access. Identity is carried across each `agent → MCP → DS` hop via **on-behalf-of token exchange** — each MCP service obtains a store-native **per-user** identity, since a DS won't accept a Google-audience token directly. **How** it obtains one varies by DS and must be confirmed per connector: some support direct token exchange, others require a one-time per-user OAuth consent with a stored refresh token, and some have no per-user delegation path at all. A DS in that last category cannot be read under per-user enforcement and is **out of scope until one exists** — never fall back to a shared service identity for user reads. Applies equally to AI agents and automation (e.g., Zapier).
- **Write to DSs:** the user's verified SSO identity, via the DS's normal permissions.
- **Write to DL:** depends on the store —
  - *Non-versioned store* (warehouse, Postgres): a **governed writer identity** with the controls below.
  - *Version-history DS* (Confluence): ordinary DS edit under SSO; a skill uses a non-human service account. No special regime.
  - A skill writing summaries & indexes into a DS needs **least-privilege native edit access** to the locations it writes.

**Identity is never self-asserted.** An email is an identifier, never an authenticator. Every call carries a verified token, never a claimed name.

## The permission-freshness contract

This is about **permission freshness** — whether access has been revoked — a separate concern from the **content freshness** described in <u>Architecture</u>. The two have opposite risk profiles and refresh on independent cycles.

Propagated ACL metadata is a **cache**; a stale cache leaks access after revocation. **Permission refresh is decoupled from content-staleness refresh.** For sensitive categories, DL either re-validates against the live DS/Group at query time, or enforces a **maximum propagation lag** with a **fail-closed default**.

The skill must capture each item's **source ACL at read time** — failure silently widens access.

## Computed / aggregated artifacts

A cross-DS aggregation has no single source ACL. Rather than computing a most-restrictive intersection at runtime, each materialized output is assigned **one sensitivity tier / audience group** named by the skill author (**default-deny** until cleared). Blending tiers in one output is a smell — split the output.

A genuinely cross-tier output is served either by an **admin-provisioned audience group** whose membership *is* the intended union, or — absent a standing audience — by storing **pointers/instructions** directing permitted users to recompute under their own SSO at query time. The skill never computes an intersection. Before writing, the skill asserts the named group is no broader than every input source's audience; on failure the output stays default-deny.

## Three sharing states

Every DL output carries one of:

1. **Shared with a specified Google Group** — the group that should see it.
2. **Explicitly unrestricted** — an affirmative flag set to open the output org-wide.
3. **Unspecified → default-deny** — shared only with a restricted fallback group. Absence of a decision is never "open."

Enforcement is the **store's own native group/role grant** (mechanics per store in <u>Storage</u>). Where a source isn't already group-based, an admin must provision a matching Google Group or the output stays default-deny.

## Governed-writer controls (non-versioned stores)

A non-versioned store's writer identity is a single point of failure — a compromised credential poisons ACLs, hints, and trust for every query. So it runs under: **no long-lived keys** (e.g., Workload Identity Federation), a **rotation schedule**, **least privilege** (write only to designated DL locations), and **audit logging** on every write. Full mechanics in <u>Storage</u>.

**A Catalog in a version-history DS is deliberately *not* under that regime** — access enforced at the target store + the skill's validate/re-derive pass replace the service-account controls. Confirmation/trust signals on a Confluence page are non-recomputable, so revert is their only recovery.

## Third-party integration trust boundary

External tools (Glean, GoSearch, self-hosted platforms) are a distinct trust zone. Because DL aggregates across DSs, connecting one uncontrolled tool creates a bulk re-export path for source-restricted data. For each external consumer define: **credential scope** (least-privilege slice), **data minimization** (which portion of DL, not all), **retention/training constraints**, and **breach containment**.

A tool querying under its own service credentials must faithfully proxy the end-user's identity so DL enforcement isn't bypassed — **enforced, not assumed**: require a verifiable end-user assertion (signed user token / OBO) and **reject any request carrying only a service credential with no user identity**.
