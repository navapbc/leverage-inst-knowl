---
title: "feat: Agent picker sections and management-agent guardrail"
type: feat
status: completed
date: 2026-07-27
origin: docs/brainstorms/2026-07-27-01-agent-picker-sections-and-management-guardrail-requirements.md
---

# feat: Agent picker sections and management-agent guardrail

## Summary

Add a `section` to each roster entry and a top-level section declaration to `agents.toml`, carry that
data through startup name→id resolution into `AgentOption`, and render the home picker grouped by
section. Sections marked `management` are hidden unless a per-user "Show management agents" toggle
(stored in the session cookie) is on; the toggle lives on the Settings page with a data-write warning.

---

## Problem Frame

The home picker renders every agent as a flat list in roster order ([app_auth.py:196-213](lik-ui/src/lik_ui/app_auth.py#L196-L213), [templates/agents.html](lik-ui/src/lik_ui/templates/agents.html)), giving users no way to tell read-only agents (search, query) apart from write-capable ones. The Catalog Registration Agent writes to the shared Catalog, yet is selectable as casually as a search agent — the risk is accidental misuse, not a malicious actor (all users are authenticated behind Google login). See origin: [2026-07-27-01-...-requirements.md](docs/brainstorms/2026-07-27-01-agent-picker-sections-and-management-guardrail-requirements.md).

---

## Requirements

- R1. Picker groups agents into named sections rendered as headings, not a flat list. *(origin R1)*
- R2. Each agent declares its section; no-section agents fall into a default group that still renders. *(origin R2)*
- R3. Section + management metadata live in the lik-ui roster (`agents.toml`), not the shared agent definitions. *(origin R3)*
- R4. A section can be marked "management"; management sections are hidden by default. *(origin R4)*
- R5. Settings page has a "Show management agents" checkbox that reveals/hides management sections. *(origin R5)*
- R6. The checkbox carries a warning that management agents write data. *(origin R6)*
- R7. The choice is a per-user preference, persists across pages/visits, defaults OFF. *(origin R7)*
- R8. Enforcement is cosmetic: the toggle controls picker visibility only; direct URLs to management agents are not blocked. *(origin R8)*

**Origin acceptance examples:** AE1 (covers R4/R5/R7), AE2 (covers R7), AE3 (covers R8), AE4 (covers R2).

---

## Scope Boundaries

- No RBAC, admin identity, email allowlist, or Google-group membership.
- No server-side blocking of management agents; `/connections` and `/chat` are unchanged (R8).
- No new user table or DB-backed preference storage.
- No changes to agents' MCP tool-call permission policies (`always_allow` / `ask`).
- Section membership is display metadata only; it does not change agent behavior or capability.

---

## Context & Research

### Relevant Code and Patterns

- Roster parsing: `Settings.agent_roster` ([settings.py:141-159](lik-ui/src/lik_ui/settings.py#L141-L159)) parses `[[agents]]` blocks into `AgentRosterEntry` ([settings.py:27-34](lik-ui/src/lik_ui/settings.py#L27-L34)); `AgentOption` is the resolved id form ([settings.py:37-48](lik-ui/src/lik_ui/settings.py#L37-L48)).
- Name→id resolution at startup: `resolve_agent_options` ([agents.py:115-128](lik-ui/src/lik_ui/agents.py#L115-L128)), wired once in `build_app` and stored on `app.state.agents`.
- Home route builds the picker list and renders `agents.html` ([app_auth.py:196-213](lik-ui/src/lik_ui/app_auth.py#L196-L213)). Per-agent label/model/system come live from `agents_client.describe` — not stored in the roster.
- Session cookie is the established per-user store: `request.session[...]` via `SessionMiddleware` ([app.py:67](lik-ui/src/lik_ui/app.py#L67)); used for `user`, `oauth_login`, `oauth_connect`. `/logout` clears it ([app_auth.py:191-194](lik-ui/src/lik_ui/app_auth.py#L191-L194)).
- Settings page GET + POST-then-redirect pattern: `register_account_routes` ([account.py](lik-ui/src/lik_ui/account.py)), `settings.html` uses `<form method="post">` + `?flag=1` redirect for feedback.
- Current roster: [agents.toml](lik-ui/src/lik_ui/agents.toml); test fixture: [tests/fixtures/agents.toml](lik-ui/tests/fixtures/agents.toml).

### Institutional Learnings

- Roster-as-checked-in-file rationale and constraints: origin lineage [2026-07-23-agents-config-as-checked-in-file-requirements.md](docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md). Keep names (not ids) in the file; label stays SDK-sourced.

---

## Key Technical Decisions

- **`agents.toml` gains a top-level `[[sections]]` list + a per-agent `section` field.** Each `[[sections]]` block declares `name`, its position in the list is the display order, and an optional `management = true` marks it hidden-by-default. This puts section ordering and management status in one readable place and resolves both origin deferred questions. Chosen over a bare per-agent boolean because arbitrary named sections (origin R1) need a name/order home anyway.
- **Section/management data flows through `AgentOption`, not re-derived in the view.** `AgentRosterEntry` and `AgentOption` each gain `section: str` and `is_management: bool`; `resolve_agent_options` copies them through alongside the resolved ids. The home route groups already-resolved options — no second roster read.
- **Preference stored in the signed session cookie**, key e.g. `show_management_agents`, absent ⇒ OFF. Sticks across visits; cleared on logout (acceptable per R7). No DB.
- **Cosmetic enforcement only.** Filtering happens solely in the home route's grouping step; `/connections` and `/chat` are not touched (R8).
- **Grouping is view-layer, roster stays label-free.** Labels/model/system continue to come from `agents_client.describe` per-request; only section/management (pure display metadata owned by lik-ui) is added to the roster.

---

## Open Questions

### Resolved During Planning

- Section ordering: declaration order of `[[sections]]`; agents within a section keep roster order; the default (no-section) group renders last.
- Empty/hidden section rendering: a section with zero visible agents renders no heading; a management section renders nothing (heading included) when the toggle is OFF.
- Preference persistence mechanism: signed session cookie (`SessionMiddleware`), not a DB.

### Deferred to Implementation

- Exact TOML key names (`management` vs `restricted`; `section` field spelling) and the session key string — finalize during implementation for readability.
- Whether an agent naming an undeclared section is a hard startup error or falls into the default group — lean toward default-group tolerance (matches R2's "still renders" intent); confirm against the production startup-guard posture in `require_production_config`.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

Proposed `agents.toml` shape (directional):

    default_environment = "lik-ui-env"

    [[sections]]
    name = "Search"

    [[sections]]
    name = "Management"
    management = true

    [[agents]]
    agent = "Knowledge Search Agent"
    section = "Search"

    [[agents]]
    agent = "Catalog Registration Agent"
    section = "Management"

Data flow:

    agents.toml ──parse──> AgentRosterEntry(section, is_management)
        ──resolve ids──> AgentOption(agent_id, environment_id, section, is_management)
        ──home route: read session toggle, drop is_management options when OFF,
          group by section in declared order──> agents.html (headings + cards)

---

## Implementation Units

- U1. **Roster schema: sections and management metadata**

**Goal:** Teach the roster format and models about sections and which sections are management.

**Requirements:** R2, R3, R4

**Dependencies:** None

**Files:**
- Modify: `lik-ui/src/lik_ui/settings.py` (`AgentRosterEntry`, `AgentOption`, `agent_roster` parsing + header docs)
- Modify: `lik-ui/src/lik_ui/agents.toml` (add `[[sections]]`, add `section` to each `[[agents]]`, update header comment)
- Modify: `lik-ui/tests/fixtures/agents.toml` (mirror the new shape, include one management section)
- Test: `lik-ui/tests/test_settings.py` (or the existing roster-parsing test module)

**Approach:**
- Add `section: str` and `is_management: bool` to `AgentRosterEntry` and `AgentOption`.
- Parse a top-level `[[sections]]` list into an ordered name→management map; for each agent, resolve `is_management` from its `section`'s entry. Preserve section declaration order for later grouping (e.g. return sections order alongside entries, or expose an ordered `sections` property).
- An agent with no `section`, or a section not declared in `[[sections]]`, → default group, `is_management = False` (see Deferred question on strictness).
- Keep a missing file → empty list; malformed TOML still raises (unchanged).

**Patterns to follow:** existing `agent_roster` property and `AgentRosterEntry`/`AgentOption` models in [settings.py](lik-ui/src/lik_ui/settings.py).

**Test scenarios:**
- Happy path: a roster with two sections (one `management = true`) parses to entries carrying correct `section` and `is_management`.
- Edge case: agent with no `section` → default group, `is_management` False.
- Edge case: agent referencing an undeclared section → default group (or documented error, per chosen strictness).
- Edge case: `default_environment` fallback still applies with the new fields present.
- Edge case: missing file → empty list; malformed TOML raises (regression guard).

**Verification:** parsing a fixture roster yields entries with populated `section`/`is_management`; existing roster tests still pass.

---

- U2. **Carry section/management through startup resolution**

**Goal:** Propagate section metadata from the name roster into the resolved `AgentOption`s the app serves.

**Requirements:** R1, R4

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/agents.py` (`resolve_agent_options`)
- Test: `lik-ui/tests/test_agents.py`

**Approach:**
- In `resolve_agent_options`, copy `section` and `is_management` from each `AgentRosterEntry` onto the constructed `AgentOption` alongside resolved ids. No behavior change when there is no client (still returns `[]`).
- Expose section display order to the home route — either resolved options preserve order and the route re-reads declared section order from settings, or `resolve_agent_options` returns the ordered section list too. Prefer sourcing order from settings to keep `AgentOption` flat.

**Patterns to follow:** existing `resolve_agent_options` loop ([agents.py:115-128](lik-ui/src/lik_ui/agents.py#L115-L128)).

**Test scenarios:**
- Happy path: a fake `AgentsClient` + multi-section roster resolves to `AgentOption`s with matching `section`/`is_management`.
- Edge case: stub/no-client path still returns `[]`.
- Error path: unresolved agent name still raises (regression guard).

**Verification:** resolved `AgentOption`s carry section metadata; startup on the stub path is unchanged.

---

- U3. **Settings toggle: session-backed preference + checkbox + warning**

**Goal:** Let a user turn management-agent visibility on/off from Settings, persisted per-user.

**Requirements:** R5, R6, R7

**Dependencies:** None (independent of U1/U2; wire-up meets them in U4)

**Files:**
- Modify: `lik-ui/src/lik_ui/account.py` (pass current toggle state into `settings_page`; add a POST route to set it)
- Modify: `lik-ui/src/lik_ui/templates/settings.html` (checkbox form + data-write warning card)
- Test: `lik-ui/tests/test_account.py` (or the settings-route test module)

**Approach:**
- Add a small helper to read the preference from `request.session` (absent ⇒ False) and one to set it; keep the session-key string in one place.
- `GET /settings` passes the current value to the template so the checkbox reflects state.
- Add `POST /settings/agent-visibility` that reads the checkbox from the form, writes the session value, and redirects back to `/settings` (mirror the existing POST-then-redirect pattern). A checkbox submits only when checked, so treat absence as OFF.
- Template: a card with the checkbox, a submit, and a warning that management agents write data and should only be used by those who understand them.

**Patterns to follow:** POST-then-redirect handlers and `?flag=1` feedback in [account.py](lik-ui/src/lik_ui/account.py); form/card markup in [settings.html](lik-ui/src/lik_ui/templates/settings.html).

**Test scenarios:**
- Covers AE1. Happy path: POST with checkbox on sets session true; GET /settings then renders the box checked.
- Covers AE1. Happy path: POST with checkbox absent sets session false; GET renders unchecked.
- Covers AE2. Edge case: after setting true, a later GET in the same session still reads true (stickiness).
- Edge case: fresh session (no key) → GET renders unchecked (default OFF).
- Edge case: the warning text is present in the rendered settings page.

**Verification:** toggling the checkbox changes the stored session preference and the rendered checkbox state across requests.

---

- U4. **Sectioned, filtered home picker**

**Goal:** Render the picker grouped by section, hiding management sections unless the toggle is on.

**Requirements:** R1, R2, R4, R7, R8

**Dependencies:** U1, U2, U3

**Files:**
- Modify: `lik-ui/src/lik_ui/app_auth.py` (`home` route: read toggle, filter, group by section)
- Modify: `lik-ui/src/lik_ui/templates/agents.html` (render section headings + per-section agent cards)
- Test: `lik-ui/tests/test_app_auth.py` (or the home-route test module)

**Approach:**
- In `home`, read the visibility preference (same helper as U3). Build the per-agent info dicts as today (label/model/system from `describe`), then drop `is_management` options when the toggle is OFF.
- Group the remaining options by section in declared section order; the default (no-section) group renders last. Pass an ordered list of `{section_name, is_management, agents}` groups to the template.
- Do NOT touch `/connections` or `/chat` — a direct URL to a management agent still resolves (R8). Optionally leave a code comment noting this is intentional.
- `agents.html`: replace the single flat `{% for a in agents %}` with an outer loop over groups (heading per non-empty group) and the existing card markup inside. Keep the empty-state message when no groups have agents.

**Patterns to follow:** existing home-route describe-enrichment loop ([app_auth.py:200-213](lik-ui/src/lik_ui/app_auth.py#L200-L213)); existing card + `<details>` markup and `{% else %}` empty state in [agents.html](lik-ui/src/lik_ui/templates/agents.html).

**Test scenarios:**
- Covers AE1. Happy path: toggle OFF → management-section agents absent from the rendered picker; non-management sections present with headings.
- Covers AE1. Happy path: toggle ON → management-section agents appear under their heading.
- Covers AE4. Edge case: an agent with no section renders under the default group.
- Edge case: sections render in declared order; a section with zero visible agents renders no heading.
- Covers AE3. Integration: with toggle OFF, `GET /connections?agent_id=<management agent>` still returns the connections page (not blocked) — proves cosmetic-only enforcement.
- Edge case: empty roster → existing empty-state message still shows.

**Verification:** the picker shows section headings, management agents appear only when the toggle is on, and direct access to a management agent is unaffected by the toggle.

---

## System-Wide Impact

- **Interaction graph:** touches startup roster resolution (`resolve_agent_options`), the home route, and the settings routes. No change to session creation, chat, or connection resolution.
- **API surface parity:** the roster file format changes — `tests/fixtures/agents.toml` and the packaged `agents.toml` must move together; `init_workspace.py`'s roster-append (if it writes section) is out of scope unless it breaks (it appends agent blocks; new agents land in the default group until given a section).
- **State lifecycle risks:** preference is cookie-only; clearing cookies / logout resets to OFF by design. No persistence migration.
- **Unchanged invariants:** name→id resolution semantics, label-from-SDK behavior, `/connections` and `/chat` access, and the production startup guard remain as-is (guard still checks a non-empty roster).

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Users read the checkbox as a security control | Warning copy frames it as a safety guard; documented as cosmetic (R8). A true boundary is explicitly deferred to a future RBAC effort. |
| `init_workspace.py` appends section-less agent blocks | Acceptable — they land in the default group; note in docs. No code change required for correctness. |
| Prod `agents.toml` must be migrated to the new shape at deploy | It is a packaged file shipped with the app (not DB/SSM), so it deploys with the code — no separate migration step. Verify the prod roster gains sections in the same PR/deploy. |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-27-01-agent-picker-sections-and-management-guardrail-requirements.md](docs/brainstorms/2026-07-27-01-agent-picker-sections-and-management-guardrail-requirements.md)
- Related roster lineage: [docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md](docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md)
- Key code: [settings.py](lik-ui/src/lik_ui/settings.py), [agents.py](lik-ui/src/lik_ui/agents.py), [app_auth.py](lik-ui/src/lik_ui/app_auth.py), [account.py](lik-ui/src/lik_ui/account.py), [templates/agents.html](lik-ui/src/lik_ui/templates/agents.html), [templates/settings.html](lik-ui/src/lik_ui/templates/settings.html)
