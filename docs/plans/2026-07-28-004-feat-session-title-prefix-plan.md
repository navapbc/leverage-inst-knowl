---
title: "feat: Add session_title_prefix to agent roster for cleaner session titles"
type: feat
status: active
date: 2026-07-28
---

# feat: Add session_title_prefix to agent roster for cleaner session titles

## Summary

Add an optional `session_title_prefix` field to each agent's roster entry in
[lik-ui/src/lik_ui/agents.toml](../../lik-ui/src/lik_ui/agents.toml) and use it — instead of the
full agent name (`agent_label`) — as the prefix of the default session title (`"<prefix> · <timestamp>"`).
The long platform agent names (e.g. "Cross-Source Referencing Agent") clutter the title; a short curated
prefix keeps titles scannable. When the field is omitted, behavior is unchanged (falls back to `agent_label`).

---

## Problem Frame

The default session title is `"<agent_label> · <local timestamp>"`, where `agent_label` is the agent's
full platform name pulled from the SDK (`describe()["name"]`). These names are descriptive and long
("Cross-Source Referencing Agent", "Catalog Registration Agent"), so every session title leads with a
long clause before the timestamp. The user wants a short, roster-controlled prefix instead.

---

## Requirements

- R1. Each agent's roster entry may declare an optional `session_title_prefix` string.
- R2. The default session title uses `session_title_prefix` as its leading clause instead of `agent_label`,
  in both the client-side prefill and the server-side blank-title fallback.
- R3. When an agent omits `session_title_prefix`, the title default falls back to today's behavior
  (`agent_label`), so no agent is left with a broken/empty prefix.
- R4. Non-title uses of `agent_label` (the connections page `<h1>` and the chat page "Details for …" link)
  are unchanged — those are page headers, not session titles.

---

## Scope Boundaries

- Not changing the timestamp portion of the default title or its format.
- Not changing the scheduled-run title format (`"Scheduled: <agent_name>"` in
  [scheduled_runner.py:132](../../lik-ui/src/lik_ui/scheduled_runner.py#L132)) — it derives from
  `agent_name`, not `agent_label`, and is out of scope.
- Not renaming agents on the platform or changing `describe()`.
- Not adding UI to edit the prefix — it is roster configuration only.

---

## Context & Research

### Relevant Code and Patterns

- **Roster field pattern** — `user_prompt` / `schedulable` / `max_runtime` are the exact template to
  mirror: declared per-agent in [agents.toml](../../lik-ui/src/lik_ui/agents.toml), modeled on
  `AgentRosterEntry` and `AgentOption` in [settings.py:52-103](../../lik-ui/src/lik_ui/settings.py#L52-L103),
  parsed in `Settings.agent_roster` [settings.py:223-257](../../lik-ui/src/lik_ui/settings.py#L223-L257),
  and carried through name→id resolution in `resolve_agent_options`
  [agents.py:161-184](../../lik-ui/src/lik_ui/agents.py#L161-L184).
- **Title default (client)** — JS prefill + input placeholder in
  [connections.html:56-70](../../lik-ui/src/lik_ui/templates/connections.html#L56-L70), fed by `agent_label`
  passed from the `/connections` route [agents.py:229](../../lik-ui/src/lik_ui/agents.py#L229).
- **Title default (server)** — blank-title fallback in `new_chat`
  [chat.py:395-405](../../lik-ui/src/lik_ui/chat.py#L395-L405): `title = title.strip() or f"{label} · …"`.
  Note `label` here is re-fetched via `describe()`; the plan makes the prefix available on the
  `AgentOption` so no extra SDK call is needed for the prefix itself.

### Institutional Learnings

- `docs/solutions/` reviewed — none directly applicable to this roster-field addition.

---

## Key Technical Decisions

- **Fall back to `agent_label` when the prefix is empty** (R3): keeps the change non-breaking and matches
  the existing "always name the session" guarantee. The field is optional in the model (`= ""`), and the
  effective prefix is `session_title_prefix or agent_label`.
- **Carry the prefix on `AgentOption`, not via `describe()`**: the connections route and `new_chat` both
  already hold the `AgentOption`, so the prefix travels with startup-resolved config — no new SDK call,
  and it works even if `describe()` fails (which already degrades `agent_label` to the agent id).
- **Keep the effective-prefix fallback in Python, pass a single ready value to the template**: the route
  computes `session_title_prefix or agent_label` and passes it to `connections.html`, keeping the Jinja
  template free of fallback logic (the template's current `agent_label` var stays for the `<h1>`).

---

## Open Questions

### Resolved During Planning

- *Does this affect scheduled runs?* No — scheduled titles use `agent_name`, not `agent_label` (see Scope).
- *Should the connections `<h1>` and chat "Details for" link use the prefix?* No — R4 keeps the full
  `agent_label` there; only the session title uses the prefix.

### Deferred to Implementation

- **Exact prefix strings per agent** — product-facing wording, the user's to finalize. Proposed short
  values (adjust freely): "Cross-Source" (Cross-Source Referencing Agent), "Catalog" (Catalog Registration
  Agent), "Knowledge Search" (Knowledge Search Agent). The commented-out example `[[agents]]` block does
  not need a value.

---

## Implementation Units

- U1. **Add `session_title_prefix` to the roster model and parsing**

**Goal:** The roster can declare `session_title_prefix` per agent and it flows into the resolved `AgentOption`.

**Requirements:** R1, R3

**Dependencies:** None

**Files:**
- Modify: `lik-ui/src/lik_ui/settings.py` (add field to `AgentRosterEntry` and `AgentOption`; parse it in `agent_roster`)
- Modify: `lik-ui/src/lik_ui/agents.py` (pass it through in `resolve_agent_options`)
- Test: `lik-ui/tests/test_settings.py`

**Approach:**
- Add `session_title_prefix: str = ""` to both `AgentRosterEntry` and `AgentOption`, mirroring `user_prompt`.
- In `Settings.agent_roster`, read `str(entry.get("session_title_prefix", "")).strip()` and pass to the entry.
- In `resolve_agent_options`, add `session_title_prefix=entry.session_title_prefix` to the `AgentOption(...)` call.

**Patterns to follow:**
- `user_prompt` handling across [settings.py:68,96,238,252](../../lik-ui/src/lik_ui/settings.py#L68) and
  [agents.py:178](../../lik-ui/src/lik_ui/agents.py#L178).

**Test scenarios:**
- Happy path: a roster TOML entry with `session_title_prefix = "Cross-Source"` parses to an
  `AgentRosterEntry` whose `session_title_prefix == "Cross-Source"`.
- Edge case: an entry omitting the field parses to `session_title_prefix == ""` (default).
- Edge case: whitespace-only value is stripped to `""`.

**Verification:** `agent_roster` returns entries carrying the declared prefix; omission yields `""`.

---

- U2. **Use the prefix in the session-title default (client + server)**

**Goal:** The default title's leading clause is the effective prefix (`session_title_prefix or agent_label`)
in both the connections-page prefill/placeholder and the `new_chat` server fallback.

**Requirements:** R2, R3, R4

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/agents.py` (`/connections` route: pass an effective `session_title_prefix` to the template)
- Modify: `lik-ui/src/lik_ui/templates/connections.html` (use the prefix var in the JS prefill and input placeholder)
- Modify: `lik-ui/src/lik_ui/chat.py` (`new_chat`: use `agent.session_title_prefix or label` for the blank-title fallback)
- Test: `lik-ui/tests/test_chat.py`

**Approach:**
- In the `/connections` route, compute `session_title_prefix = agent.session_title_prefix or agent_label`
  and add it to the template context; leave `agent_label` in context for the `<h1>` (R4).
- In `connections.html`, change the JS prefill (line ~68) and the input `placeholder` (line ~56) from
  `agent_label` to the new `session_title_prefix` var. Keep the `<h1>` on line 5 as `agent_label`.
- In `new_chat`, change the fallback to `title.strip() or f"{agent.session_title_prefix or label} · {…}"`.
  `label` remains the `describe()`-derived name, preserving the fallback chain when the prefix is empty.

**Patterns to follow:**
- Existing template context construction in the `/connections` route
  [agents.py:223-236](../../lik-ui/src/lik_ui/agents.py#L223-L236).

**Test scenarios:**
- Happy path (server): agent with `session_title_prefix = "Cross-Source"`, blank title → created session
  title starts with `"Cross-Source · "`.
- Fallback (server): agent with empty prefix, blank title → title starts with `agent_label` (current
  behavior; existing `test_new_chat_defaults_title_when_blank` should still pass, adjusted only if the
  test's stub agent gets a prefix).
- Happy path (client): `/connections` for an agent with a prefix → rendered page's placeholder and prefill
  script reference the prefix, not the long agent name.
- R4 guard: the connections `<h1>` still shows the full `agent_label`, not the prefix.

**Verification:** Starting a chat with a blank title yields `"<prefix> · <timestamp>"`; omitting the prefix
still yields `"<agent_label> · <timestamp>"`; the connections `<h1>` is unchanged.

---

- U3. **Populate `session_title_prefix` for each shipped agent**

**Goal:** Each real `[[agents]]` block in the roster declares a short prefix.

**Requirements:** R1

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/agents.toml`

**Approach:**
- Add `session_title_prefix = "…"` to each of the three real agent blocks (Cross-Source Referencing,
  Catalog Registration, Knowledge Search). Use the values finalized from the Deferred question above.
- Leave the commented-out example block as-is.

**Patterns to follow:**
- The one-line-per-field style already used for `user_prompt`/`schedulable` in
  [agents.toml](../../lik-ui/src/lik_ui/agents.toml).

**Test scenarios:**
- Integration: `test_shipped_roster_parses_to_at_least_one_agent` still passes; optionally assert each
  shipped agent now has a non-empty `session_title_prefix`.

**Verification:** App boots; each agent's default session title leads with its short prefix.

---

## System-Wide Impact

- **API surface parity:** `session_title_prefix` is added to both `AgentRosterEntry` and `AgentOption`;
  every `AgentOption(...)` construction site is `resolve_agent_options` (single site).
- **Unchanged invariants:** `agent_label` remains the source for the connections `<h1>` and the chat
  "Details for …" link; the scheduled-run title (`"Scheduled: <agent_name>"`) is untouched; the
  "every session has a non-empty title" guarantee holds via the `or agent_label` fallback.

---

## Sources & References

- Roster + models: [lik-ui/src/lik_ui/settings.py](../../lik-ui/src/lik_ui/settings.py)
- Resolution: [lik-ui/src/lik_ui/agents.py](../../lik-ui/src/lik_ui/agents.py)
- Title default (server): [lik-ui/src/lik_ui/chat.py](../../lik-ui/src/lik_ui/chat.py)
- Title default (client): [lik-ui/src/lik_ui/templates/connections.html](../../lik-ui/src/lik_ui/templates/connections.html)
