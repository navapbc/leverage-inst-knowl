---
date: 2026-07-27
topic: agent-picker-sections-and-management-guardrail
---

# Agent picker: named sections and a management-agent guardrail

## Summary

Group the agent picker into named sections instead of one flat list, and let a section be marked
"management" (write-capable). Management sections are hidden by default and revealed by a per-user
"Show management agents" checkbox on the Settings page, with a warning that these agents write data.

---

## Problem Frame

The lik-ui home page renders every configured agent as a single flat list in roster order, with no
grouping. As the roster grows (four agents today, more coming), a flat list gives users no way to tell
apart agents that safely *read* their knowledge (search, query, cross-source referencing) from agents
that *write to shared state*. The Catalog Registration Agent, for example, upserts rows into the shared
Discovery Layer Catalog. A user browsing the picker has no signal that selecting it will mutate data the
whole organization depends on, and can pick it as casually as a read-only search agent.

The cost is accidental misuse: someone runs a write-capable agent without realizing what it does. The
concern is *stumbling into* these agents, not a malicious actor — every user is already an authenticated,
trusted member behind Google login.

---

## Requirements

**Sectioned picker**
- R1. The agent picker groups agents into named sections, rendered as headings, instead of one flat list.
  Section names are arbitrary and defined per deployment (e.g. "Search", "Query", "Management").
- R2. Each agent declares which section it belongs to. An agent with no declared section falls into a
  default/uncategorized group so the picker renders correctly even when section data is missing.
- R3. Section names and per-agent section assignment are configured in the lik-ui roster (the existing
  home for lik-ui display concerns), not in the shared agent definitions.

**Management guardrail**
- R4. A section can be marked as "management" (write-capable). Management sections are hidden from the
  picker by default.
- R5. The Settings page has a "Show management agents" checkbox. When checked, management sections become
  visible in the picker; when unchecked, they are hidden again.
- R6. The checkbox is accompanied by a warning that management agents write data and should only be used
  by people who understand what they do.
- R7. The show/hide choice is a per-user preference that persists across pages and visits until the user
  changes it. It defaults to OFF (management agents hidden).
- R8. Enforcement is cosmetic: the toggle only controls picker visibility. A management agent reached by
  a direct URL is not blocked. This is an intentional guardrail, not an access-control boundary.

---

## Acceptance Examples

- AE1. **Covers R4, R5, R7.** Given a fresh user with the toggle at its default, when they open the agent
  picker, management-section agents (e.g. Catalog Registration) are not shown; when they enable "Show
  management agents" in Settings and return to the picker, those agents appear under their section.
- AE2. **Covers R7.** Given a user who enabled the toggle, when they navigate away and return later, the
  toggle is still enabled and management agents remain visible — the choice stuck.
- AE3. **Covers R8.** Given a user with the toggle OFF, when they navigate directly to a management
  agent's connection/chat URL, the app still lets them proceed (visibility hiding does not block access).
- AE4. **Covers R2.** Given an agent in the roster with no section declared, when the picker renders, that
  agent appears under a default/uncategorized group rather than being dropped or breaking the page.

---

## Success Criteria

- A user scanning the picker can tell read-only agents apart from write-capable ones, and does not
  encounter management agents unless they have deliberately opted in.
- A maintainer can assign an agent to a section and mark a section management by editing the roster and
  opening a PR — no code change per agent.
- The team understands, and has accepted in writing, that this is a usability guardrail: any logged-in
  user can enable the toggle and use a management agent, and direct URLs are not blocked.
- ce-plan can implement without inventing the grouping model, where section data lives, the toggle's
  default, or the persistence expectation.

---

## Scope Boundaries

- No real authorization / RBAC, no admin-user identity, no email allowlist, no Google-group membership.
- No server-side blocking of hidden agents; direct URL access to management agents stays open.
- No database-backed user table or per-user role storage introduced for this feature.
- No changes to agents' MCP tool-call permission policies (`always_allow` / `ask`) — that is a separate,
  existing mechanism in the agent definitions.
- Section membership does not change agent behavior or capability; it is display/grouping metadata only.

---

## Key Decisions

- **Restriction attaches to a section, not a per-agent flag.** The user chose arbitrary named sections; a
  section is declared "management" and the single toggle reveals all such sections. This avoids an
  orthogonal per-agent boolean and keeps one grouping concept.
- **Section + management config lives in the lik-ui roster, not the shared agent definitions.** Grouping
  is a lik-ui display concern; keeping it out of `claude_platform/` keeps agent definitions store-agnostic
  and reusable. Consistent with the roster already owning display concerns (labels come from the SDK; the
  roster owns ordering and environment).
- **Guardrail, not a gate.** The write-mutation risk is real, but the accepted mitigation is preventing
  *accidental* use, not unauthorized use. Cosmetic hiding is deliberately chosen over enforcement to keep
  the app simple, since all users are already trusted and authenticated. A true boundary is a future RBAC
  effort, consciously deferred.
- **Toggle defaults OFF and is sticky per user.** Safe default (management agents hidden) with a
  low-friction opt-in that the user does not have to re-set every visit.

---

## Dependencies / Assumptions

- Assumes the lik-ui roster (per-deployment, PR-reviewed) is the right place for section and management
  metadata, consistent with the roster already being a checked-in, per-deployment config.
- Assumes a per-user sticky preference can be stored without a new user table — the app already runs
  signed session middleware, which is a candidate store. Exact mechanism is planning's call.
- The Catalog Registration Agent is the concrete first member of a management section; the design must
  generalize to future write-capable agents without per-agent code.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R7][Technical] Where the per-user toggle preference is stored (signed session cookie vs. other)
  and its lifetime relative to login/logout.
- [Affects R1][Technical] How sections are ordered in the picker and how a section with zero currently
  visible agents renders (e.g. hidden management section when the toggle is OFF).
