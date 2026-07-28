---
title: "feat: Per-agent user_prompt block above the chat transcript"
type: feat
status: active
date: 2026-07-27
---

# feat: Per-agent user_prompt block above the chat transcript

## Summary

Add a per-agent `user_prompt` — a short, user-facing invitation ("here's what to ask me") authored
in `lik-ui/src/lik_ui/agents.toml` — and render it as a block immediately above the chat transcript.
The value lives in the roster TOML because the Managed Agent spec (the platform's SDK-shaped YAML)
has no field for it. It flows roster → `AgentRosterEntry` → `AgentOption` → `chat_page` → `chat.html`,
mirroring the existing name/section plumbing. Retroactive values are authored for the three shipped
agents from their `description` and `system` prompt.

---

## Problem Frame

When a user opens a chat, the transcript starts empty and the only cue for what to do is the
composer placeholder ("Ask the agent a question or make a request…"). That is generic — it does not
tell the user *what this particular agent is good for* or give example asks. Each agent already
carries a rich `system` prompt and `description`, but those live in the platform spec and are not
surfaced to the user in a concise, actionable form. There is no field in the Managed Agent spec to
hold a short user-facing prompt, so it needs a home in lik-ui's own roster config.

---

## Requirements

- R1. Each agent may declare a `user_prompt` string in its `agents.toml` `[[agents]]` block; it is
  optional (agents without one render no block).
- R2. The `user_prompt` renders as a distinct block positioned immediately before the `#transcript`
  element on the chat page.
- R3. The value is carried by name-based resolution exactly like the rest of the roster — no platform
  ids, no SDK round-trip (it is authored config, not read from the agent definition).
- R4. The three shipped agents each get a retroactively-authored `user_prompt` derived from their
  `description` and `system` prompt.
- R5. The `## Add an agent` section of `lik-ui/README.md` documents the `user_prompt` field so future
  agents populate it.
- R6. Absence of a value, or stub/local mode where `app.state.agents` is empty, degrades gracefully:
  no block, no error.

---

## Scope Boundaries

- Not editing the Managed Agent specs under `claude_platform/agents/` — `user_prompt` is deliberately
  a lik-ui roster concern, not a platform-spec field.
- Not making the block dismissible, per-user, or persisted — it is static config-driven content.
- Not adding example-prompt "click to send" affordances — the block is informational text only.

### Deferred to Follow-Up Work

- Hiding the block once a conversation has messages (empty-state-only rendering): possible later
  enhancement; default is always-visible above the transcript. See Open Questions.

---

## Context & Research

### Relevant Code and Patterns

- `lik-ui/src/lik_ui/agents.toml` — the shipped roster. `[[agents]]` blocks currently carry `agent`
  and `section`; `user_prompt` is a new optional key alongside them.
- `lik-ui/src/lik_ui/settings.py`:
  - `AgentRosterEntry` (line ~37) and `AgentOption` (line ~53) — the two models the value must be
    added to (roster form and resolved form).
  - `Settings.agent_roster` (line ~193) — parses `[[agents]]` blocks; already reads `agent`,
    `environment`, `section` via `str(entry.get(...))`. Add a `user_prompt` read in the same shape.
- `lik-ui/src/lik_ui/agents.py`:
  - `resolve_agent_options` (line ~161) — copies roster fields into `AgentOption` after name→id
    resolution. Must carry `user_prompt` through.
- `lik-ui/src/lik_ui/chat.py`:
  - `chat_page` (line ~441) — already renders `chat.html` with `agent_label`, `servers`, etc. It has
    `request.app.state.agents` (the resolved `AgentOption` list) available to look up the matching
    agent by `session["agent_id"]` and pass its `user_prompt` to the template.
- `lik-ui/src/lik_ui/templates/chat.html` — `#transcript` div at lines 53–56; the block goes just
  before it (after the `<hr/>` on line 51).

### Institutional Learnings

- `docs/plans/2026-07-23-004-refactor-lik-ui-agents-config-file-plan.md` and
  `2026-07-27-001-...-agent-picker-sections-...-plan.md` established the name-based roster and the
  roster→entry→option carry-through pattern this plan extends. Follow that shape exactly.

### External References

- None. This is internal plumbing plus a template block; no external research warranted.

---

## Key Technical Decisions

- **Home the value in `agents.toml`, not the platform spec:** the Managed Agent spec is the SDK's
  shape and has no field for a user-facing invitation; the roster is lik-ui's own config and already
  the right place for display metadata (cf. `section`). (Restates R1/R3.)
- **Carry by name-resolution, not SDK read:** `user_prompt` is authored config, so it rides the same
  `AgentRosterEntry → AgentOption` path as `section`; it is *not* fetched via `describe()`. This keeps
  it out of the `describe` cache and avoids an SDK dependency for static text.
- **Look up in `chat_page` by `agent_id`:** `chat_page` already holds `app.state.agents`; match the
  session's `agent_id` to its `AgentOption` and read `user_prompt`. No new state, no DB column.
- **Render as plain text in a styled block:** keep it simple — a `<div>`/`<aside>` with the text,
  escaped by Jinja's autoescape. Do not run it through the `marked`/DOMPurify markdown pipeline (that
  pipeline exists for untrusted tool output; this is trusted, short, authored config).

---

## Open Questions

### Resolved During Planning

- *Where does "immediately before the transcript" render?* — Directly before the `#transcript` div
  (after the `<hr/>` at `chat.html:51`), as a persistent block above the transcript. Matches the
  literal request.
- *Should it read from the agent's SDK definition?* — No; the request explicitly homes it in
  `agents.toml` because the spec has no field for it.

### Deferred to Implementation

- Exact element/class naming and CSS for the block (a11y role, muted styling to match
  `.muted-note`) — a styling detail, settled when editing `app.css`/`chat.html`.
- Whether to also show it to read-only shared viewers — default yes (it is agent-descriptive, not
  owner-only); confirm during implementation against the `is_owner` gating already in the template.

---

## Implementation Units

- U1. **Add `user_prompt` to the roster models and parser, and author the shipped values**

**Goal:** `user_prompt` is parsed from `agents.toml` and carried through resolution to `AgentOption`;
the three shipped agents get authored values.

**Requirements:** R1, R3, R4

**Dependencies:** None

**Files:**
- Modify: `lik-ui/src/lik_ui/settings.py` (add `user_prompt: str = ""` to `AgentRosterEntry` and
  `AgentOption`; read it in `agent_roster`)
- Modify: `lik-ui/src/lik_ui/agents.py` (`resolve_agent_options` copies `user_prompt` into `AgentOption`)
- Modify: `lik-ui/src/lik_ui/agents.toml` (add `user_prompt` to all three `[[agents]]` blocks)
- Test: `lik-ui/tests/test_settings.py`, `lik-ui/tests/test_agents.py`

**Approach:**
- Add `user_prompt: str = ""` to both models. In `agent_roster`, add
  `user_prompt = str(entry.get("user_prompt", "")).strip()` and pass it into `AgentRosterEntry`,
  mirroring how `section` is read.
- In `resolve_agent_options`, add `user_prompt=entry.user_prompt` to the `AgentOption(...)` construction.
- Authored values (proposed — refine against tone; multi-line TOML string is fine):
  - **Cross-Source Referencing Agent:** "Ask a question and I'll answer it by pulling from several
    sources at once — Nava's project Catalog, Confluence/Jira, Google Drive, Slack, and GitHub — and
    give you one cited answer. Try: *"What's the status of project X across our docs and Slack?"* or
    *"Find the decision behind Y and the code that implemented it."*"
  - **Catalog Registration Agent:** "Tell me what to register into the Discovery Layer Catalog.
    Today I can catalog **Project Indexes** — say *"sync the project indexes"* and I'll crawl the
    project-index pages in Confluence and update one Catalog row per page."
  - **Knowledge Search Agent:** "Ask a Nava delivery-knowledge question and I'll route it to the right
    specialist: project history (*"has anyone done X?"*), org guidance (*"what's Nava's policy on Y?"*,
    *"where's the template for Z?"*), or practice how-to (*"what's the best practice for W?"*)."

**Patterns to follow:**
- The `section`/`is_management` carry-through in `settings.py` and `agents.py` (identical shape).

**Test scenarios:**
- Happy path: a roster TOML with `user_prompt = "…"` parses into an `AgentRosterEntry` with that value.
- Edge case: a `[[agents]]` block with no `user_prompt` yields `user_prompt == ""`.
- Happy path: `resolve_agent_options` (with the fake client) produces an `AgentOption` whose
  `user_prompt` equals the roster entry's.
- Edge case: whitespace-only `user_prompt` normalizes to `""` (via `.strip()`).

**Verification:**
- `LIK_UI_DB_NAME=likuidb_test LIK_UI_DB_PORT=5433 uv run pytest tests/test_settings.py tests/test_agents.py`
  passes; the shipped `agents.toml` loads without error and each block carries a `user_prompt`.

---

- U2. **Plumb `user_prompt` into `chat_page` and render the block in `chat.html`**

**Goal:** The chat page shows the selected agent's `user_prompt` immediately before the transcript.

**Requirements:** R2, R6

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/chat.py` (`chat_page`: resolve the matching `AgentOption`, pass
  `user_prompt` into the template context)
- Modify: `lik-ui/src/lik_ui/templates/chat.html` (render the block before `#transcript`)
- Modify: `lik-ui/src/lik_ui/static/app.css` (muted, bounded styling for the block)
- Modify: `lik-ui/tests/fixtures/agents.toml` (give "Test Agent" a `user_prompt` so rendering is testable)
- Test: `lik-ui/tests/test_chat.py`

**Approach:**
- In `chat_page`, after computing `agent_label`, find the `AgentOption` in `request.app.state.agents`
  whose `agent_id == session["agent_id"]` (same `next(...)` idiom as `new_chat` uses) and read its
  `user_prompt` (default `""` when not found — covers stub mode where `app.state.agents` is empty).
  Add `"user_prompt": user_prompt` to the template context.
- In `chat.html`, immediately before the `<div id="transcript" …>` (i.e. right after the `<hr/>` on
  line 51), add `{% if user_prompt %}<aside class="user-prompt">{{ user_prompt }}</aside>{% endif %}`.
  Rely on Jinja autoescape; do **not** route through `marked`/DOMPurify.
- Style `.user-prompt` in `app.css` to read as a calm hint (similar weight to `.muted-note`), not an
  agent message bubble.

**Patterns to follow:**
- `new_chat`'s `next((a for a in request.app.state.agents if a.agent_id == …), None)` lookup.
- The existing `{% if … %}` gating and `.muted-note` styling in `chat.html`/`app.css`.

**Test scenarios:**
- Happy path: `GET /chat/{session_id}` for a session whose agent has a `user_prompt` includes the
  text, and it appears before the `id="transcript"` element (assert ordering by string index).
- Edge case: an agent with no `user_prompt` renders no `.user-prompt` block (the `{% if %}` is false).
- Edge case: with `app.state.agents` empty (no match for the session's `agent_id`), the page renders
  with no block and no error (200).
- Integration: a read-only shared viewer (`is_owner=false`) still sees the block (it is not gated on
  ownership) — confirms the intended visibility from the deferred Open Question.

**Verification:**
- `LIK_UI_DB_NAME=likuidb_test LIK_UI_DB_PORT=5433 uv run pytest tests/test_chat.py` passes; loading a
  real chat locally shows the agent's invitation above an empty transcript.

---

- U3. **Document `user_prompt` in the README "Add an agent" section**

**Goal:** Future agents populate `user_prompt`; the roster step explains the field and its purpose.

**Requirements:** R5

**Dependencies:** U1 (field must exist to document)

**Files:**
- Modify: `lik-ui/README.md` (step 2, "Add it to the roster", in `## Add an agent`)

**Approach:**
- In step 2, note that a `[[agents]]` block may include `user_prompt` — a short user-facing invitation
  rendered above the chat transcript telling the user what to ask this agent — and that it lives here
  (not in the platform spec) because the Managed Agent spec has no field for it. Advise deriving it
  concisely from the agent's `description`/`system`, and that omitting it simply renders no block.

**Patterns to follow:**
- The existing terse, imperative numbered-step voice of `## Add an agent`.

**Test scenarios:**
- Test expectation: none — documentation-only change, no behavioral surface.

**Verification:**
- The README step reads correctly and matches the field name/behavior shipped in U1/U2.

---

## System-Wide Impact

- **Interaction graph:** Only the chat page render path changes. `new_chat`, session creation, the
  SSE stream, and `describe()` caching are untouched — `user_prompt` never hits the SDK.
- **State lifecycle risks:** None — no DB column, no new state; the value is read from in-memory
  `app.state.agents` (populated once at startup).
- **API surface parity:** `agents.toml` is the only config surface; the field is optional and
  backward-compatible (existing rosters without it keep working).
- **Unchanged invariants:** Name-based resolution (no platform ids in the repo) and the "label/servers
  come from the SDK definition" rule are preserved; `user_prompt` is explicitly authored config, a
  separate concern from SDK-derived display data.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Stub/local mode has empty `app.state.agents`, so the lookup finds nothing | Default `user_prompt` to `""` on no-match; the `{% if %}` simply renders nothing (R6). Covered by a test. |
| Authored values drift from the agents' evolving `system` prompts | Values are short and intent-level, not a mirror of the prompt; README step tells authors to keep them concise and current. |
| Treating the block like untrusted content and over-engineering sanitization | Decision fixed: trusted authored config, Jinja autoescape only — no markdown pipeline. |

---

## Sources & References

- Roster + carry-through pattern: `docs/plans/2026-07-23-004-refactor-lik-ui-agents-config-file-plan.md`,
  `docs/plans/2026-07-27-001-feat-agent-picker-sections-and-management-guardrail-plan.md`
- Agent specs (source for authored values): `claude_platform/agents/{cross-source-reference,catalog-registration,knowledge-search}.yaml`
- Render target: `lik-ui/src/lik_ui/templates/chat.html` (lines 51–56)
