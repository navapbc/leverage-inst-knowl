---
date: 2026-07-29
topic: ad-hoc-catalog-registration
---

# Ad-hoc Catalog Registration

## Summary

A new agent-facing skill lets an end-user register an existing Data Source artifact (a Confluence
page, Google doc/sheet) into the Catalog mid-chat, as a human-owned row. It generalizes the existing
Level 4 human-registration path from "an answer I just synthesized" to "any artifact I point at as an
entry point." The backend already supports this; the work is a new skill plus small v0.5 doc
clarifications.

---

## Problem Frame

Today the only way a record enters the Catalog is the automated path: a DL-creation skill writes and
tags a record, then the Catalog-registration skill (the registrar) discovers it by its `discovery-layer`
marker and registers it. The one human path that exists — Level 4 saved synthesis — is scoped to an
answer the agent *just authored in-session* under the user's SSO.

That leaves a gap: while chatting, a user often already knows a specific page is the best entry point
for a topic (a team's onboarding page, a canonical spec, a rollup sheet), but has no way to promote it
to one-lookup discovery without waiting for a producer skill to be built and deployed for that source.
The cost is coverage latency — good entry points stay undiscoverable until an offline skill catches up
with the topics people actually ask about.

---

## Actors

- A1. End-user: points the agent at an existing artifact mid-chat and asks to register it; chooses the
  discovery key and whether they are vouching for it.
- A2. Agent (running the ad-hoc skill): fetches the target via the DS MCP, proposes the key, populates
  row fields, and calls the registration tool under the user's identity.
- A3. Governed writer (existing): performs the Catalog write, attributing it to the user's verified SSO
  identity. No new component.

---

## Key Flows

- F1. Register an existing artifact as an entry point
  - **Trigger:** user says, in effect, "register this page as the entry point for <topic>."
  - **Actors:** A1, A2, A3
  - **Steps:**
    1. Agent resolves the target and fetches it once via the DS MCP to read title, last-updated,
       content, and a content-state marker.
    2. Agent proposes an `entry_type` (from the established vocabulary) and a `subject`; user confirms
       or adjusts.
    3. Agent asks whether the user is **vouching** (row ranks as the default entry point) or just
       **flagging a pointer** (ranks below vouched rows).
    4. Agent asks for the audience, defaulting to no broader than the source (default-deny if
       unspecified).
    5. If the user can write to the target and wants the role visible in the source, agent optionally
       tags it `discovery-layer`; otherwise it skips tagging.
    6. Agent registers a human-owned Catalog row via the existing tool.
  - **Outcome:** the artifact is discoverable in one `(entry_type, subject)` lookup, ranked per the
    vouch choice; no skill will ever re-derive it.
  - **Covered by:** R1, R2, R3, R4, R5, R6, R7

---

## Requirements

**Registration behavior**
- R1. The skill registers an *existing* DS artifact the user points at (not only an in-session
  synthesis) as a **human-owned** Catalog row (`row_provenance = human`), attributed to the user's
  verified identity.
- R2. Registering **designates** the target an entry-point DL record. Tagging the source with the
  `discovery-layer` marker is **optional** — offered only when the user has write access and wants the
  role visible in the source. The Catalog row itself is the authoritative record of the entry-point role.
- R3. Because tagging is optional, **write access to the target is not required** to register it. A user
  can register a page they can only read.

**Discovery key**
- R4. The skill guides the user to an `entry_type` from the established vocabulary that describes *what
  the artifact is* as an entry point. It never invents a registration-specific type (no `manual` /
  `ad-hoc` value), and coining a brand-new `entry_type` is a deliberate, discouraged-by-default step —
  because a novel key nobody queries is effectively undiscoverable.

**Trust and ranking**
- R5. When registering, the skill asks the user whether they are **vouching** or just **flagging a
  pointer**, and sets `verification` accordingly (`human-verified` with the user recorded as verifier,
  or `unverified`). This is framed as a ranking choice — vouched rows sort as the default entry point on
  their key — not a correctness metaphysics.
- R6. `provenance` is defaulted silently on this path (no user decision) — it drives no consumer or
  ranking behavior for a human-owned row; `row_provenance = human` already carries the "never re-derive"
  meaning.

**Field population**
- R7. The skill populates the remaining row fields from the fetched artifact: the pointer and how to
  fetch it, a content-state marker for staleness detection, and an audience no broader than the source
  (default-deny if unspecified). `computed_by` is set to the ad-hoc skill's own name.

---

## Acceptance Examples

- AE1. **Covers R5.** Given a `(entry_type, subject)` key that already has a skill-registered pointer,
  when the user registers a second artifact on the same key and chooses "vouching," then the user's row
  is returned as the top-ranked pointer for that key.
- AE2. **Covers R2, R3.** Given a Confluence page the user can read but not edit, when the user registers
  it, then a human-owned Catalog row is created and the source page is left untagged (no write to the DS).
- AE3. **Covers R4.** Given the user proposes a novel `entry_type` no consumer queries, when they proceed,
  then the skill first surfaces that the row will be hard to discover and requires deliberate confirmation
  rather than accepting it as the default.
- AE4. **Covers R5.** Given the user chooses "just a pointer," when the row is registered, then
  `verification = unverified` and it ranks below any vouched row on the same key.

---

## Success Criteria

- A user can, without leaving the chat and without write access to the target, make an existing page
  discoverable in one Catalog lookup, and control whether it ranks as the default entry point.
- The Catalog invariant "only ever indexes DL records" still reads true after the doc updates: a
  registered artifact is a DL record by purpose, whether or not it carries the marker.
- A downstream planner can implement the skill without re-deciding any product behavior above — the only
  open items are the ones explicitly deferred below.

---

## Documentation Updates (v0.5)

The core of the original ask. Each is a clarification/scope-widening, not a concept reversal.

- `v0.5/02-concepts.md` — Concept 4 (Catalog-registration skill) gains a **second entry path**:
  user-initiated ad-hoc registration, alongside discovery-by-marker. Soften the DL-record definition's
  "marked `discovery-layer`" so the marker is the realization for the *discovery* path, not a
  requirement for a human-registered entry point.
- `v0.5/04-strategy.md` — Generalize Level 4's human-registration path beyond in-session synthesis to
  **any pre-existing artifact the user designates**; note the registering user need not be the artifact's
  author.
- `v0.5/05-architecture.md` — §2: the role marker is **required for skill-discovered records** (the
  registrar enumerates by it) and **optional for human-registered records** (the row carries the role).
  §3: extend "who designates what qualifies" to include a user designating a pre-existing artifact at
  registration time. §4: add the ad-hoc human-registration data flow.
- `v0.5/08-open-questions.md` — add the spam / quality-gating question (below).

---

## Implementation Notes

Confirmed against the code; no new backend is required.

- `register_catalog_entry` already accepts `row_provenance = 'human'`, and the upsert's conflict clause
  is skill-only (`WHERE row_provenance = 'skill'`), so every human registration inserts a new pointer and
  duplicates on a key coexist as ranked rows (`lik-mcp/src/lik_mcp/catalog.py`).
- User attribution is automatic: the write is stamped with the authorized SSO identity server-side
  (`lik-mcp/src/lik_mcp/server.py`).
- `verification` is a lookup-time ranking key — the lookup sorts `human-verified` first
  (`lik-mcp/src/lik_mcp/catalog.py`), which is why R5's vouch choice is consumer-facing.
- The deliverable is a new agent skill (no `lik-` prefix per repo convention), deployed via the platform
  skill path; it composes the existing MCP tools (DS fetch-by-pointer + `register_catalog_entry`).

---

## Scope Boundaries

- Adding a *new offline `sync-catalog`/producer skill* on user request (built, tested, redeployed). That
  is authoring a registrar/producer skill — a dev+deploy workflow, not a runtime feature — and the
  "there are many skills" concept already covers it.
- Any new backend or MCP tool work. The existing tool and governed-writer path suffice.
- Automatic re-derivation or maintenance of ad-hoc rows. Human-owned rows are never re-derived by design;
  staleness is flagged and surfaced to the owner, as for any human row.
- Bulk / batch ad-hoc registration. This path is one artifact at a time, initiated in conversation.

---

## Key Decisions

- Designation-at-registration, marker optional: registering designates the target a DL record; the
  Catalog row carries the role, so the marker (whose only job is enumerable discovery) is not needed on
  the human path — which also removes the write-access requirement.
- Ask `verification` at register time; default `provenance` silently: `verification` feeds lookup
  ranking (consumer-facing), so it earns a question; `provenance` drives nothing on a human row.
- No registration-specific `entry_type`: `entry_type` is a discovery key describing the artifact, not a
  provenance marker; `row_provenance` already records that a human registered it.
- `computed_by` = the ad-hoc skill's name on the human path: harmless (ignored by the skill-only upsert
  key) and it records which skill wrote the row.
- **Metadata exposure accepted.** A manual row's `subject`/`location` are visible to Catalog readers under
  open reads even when the target is restricted — the Catalog exposes *existence/location, not content*,
  and enforcement stays at the source. Acceptable for the internal, trusted-user scope, so the
  keyed-lookup floor is **not** required to filter manual rows by `access_groups`.
- **Self-asserted `human-verified` accepted.** A registrant may vouch for their own row and rank it as the
  default entry point without a second voter or the confirmation path's distinct-voter floor. Acceptable
  given registrants are trusted staff.
- **Attribution resolved.** The Catalog schema carries both `created_by` and `updated_by`; a human row is
  attributed to the registrant's SSO identity (server-stamped). No reconciliation is outstanding.

---

## Dependencies / Assumptions

- The DS MCP exposes fetch-by-pointer and a content-state marker for the target's store kind (required to
  populate the row and detect staleness). True for the store kinds in scope (Confluence, Google
  docs/sheets) per the storage reference.
- The `discovery-layer` role tag reflects one realization of the role marker; making it optional on the
  human path does not affect the skill/discovery path, which still enumerates by the marker.

---

## Outstanding Questions

### Resolve Before Planning

- (none — product behavior is settled above.)

### Deferred to Planning

- [Affects R1, R5][Technical] Spam / quality-gating of ad-hoc rows: should a human-registered row need a
  minimum confirmation count before its ranking boost applies, or is `verification` at register time
  enough? Add the framing to `08-open-questions.md`; do not build gating now.
- [Affects R7][Technical] `computed_by` model constraint: the field is required with no default. Confirm
  passing the skill name satisfies the model as-is, or whether the tool should make it nullable for human
  rows.
- [Affects R7][Technical] `provenance` default for the human path when the target may itself be
  AI-generated — a field-population edge the planner sets a default for.
- [Affects R2, R5][Security] Key-metadata validation: nothing corroborates that the `subject`/`entry_type`
  a registrant supplies matches the artifact (the skill path reads these from the record's own tags).
  Whether/how to check before a manual row can rank (`08-open-questions.md`).
- [Affects R1][Design] Row cap / expiry: the designation path has no default-off, cap, or review
  expectation (unlike saved syntheses); decide a bound so backed-up, never-re-derived rows don't erode
  "low maintenance" (`08-open-questions.md`).
- [Affects R7][Security] Sensitivity default for manual rows: default `restricted`; decide whether a
  registrant may ever set `cleared` (`08-open-questions.md`).
- [Affects R7][Technical] Registrar re-validation identity: ongoing pointer/drift validation runs under a
  service identity that may lack access to a restricted target; decide how human rows are re-validated and
  where the target's content-state marker lives for drift (`08-open-questions.md`).
- [Affects R2][Design] DL-record integrity / vector guardrail: how the §3 qualification gates bind a
  registrant, and how "embed DL-record text only" applies to a human row whose target is raw source
  (`08-open-questions.md`).
