---
title: "feat: Add an Edit button for scheduled runs"
type: feat
status: active
date: 2026-07-31
origin: docs/brainstorms/2026-07-27-03-scheduled-unattended-agent-runs-requirements.md
---

# feat: Add an Edit button for scheduled runs

## Summary

Add per-schedule editing to the Settings "Scheduled runs" section: an **Edit** button on each schedule row
reveals an inline form pre-filled with that schedule's agent, cadence, and message; saving updates the row in
place. This closes the "edit" half of origin R1 ("create, view, edit, and delete"), which shipped with only
create/pause/delete. The change reuses the existing create-form validation and the owner-scoped store pattern —
no new concepts, one new DB method, one new route, and an inline form in the existing template.

---

## Problem Frame

The Scheduled runs section (`lik-ui/src/lik_ui/account.py`, `templates/settings.html`) lets a user create,
pause/resume, and delete a schedule, but not change one. To fix a typo in the message, switch the agent, or
adjust the cadence, the user must delete the schedule and recreate it — losing the row and its run history.
Origin R1 always intended edit; it was the one CRUD verb left unimplemented.

---

## Requirements

- R1. A logged-in user can edit an existing schedule they own: its agent, cadence, and message (origin R1).
- R2. Editing is owner-scoped — a user cannot edit another user's schedule (mirrors delete/pause).
- R3. Edit reuses the same validation as create: agent must be schedulable, cadence must be a whole count of a
  known unit in range, message required; an invalid edit is rejected without mutating the row.
- R4. Switching the agent re-materializes `max_runtime_s` from the new agent's roster value, so the runner
  watchdog and reclaim cutoff stay consistent with create.

**Origin actors:** the logged-in owner of a schedule (self-service).
**Origin flows:** F "manage a schedule" — the held-back/manage path in origin (line 82) explicitly names editing.

---

## Scope Boundaries

- Not adding free-form cron expressions or sub-day cadences — the edit form offers the same
  `weeks`/`days` cadence picker as create (origin deferred free cron to later).
- Not changing run history, `last_status`/`last_error`/`last_skipped`, `started_at`, or `paused` state as a
  side effect of an edit — edit touches only agent, prompt, cadence, and the derived `max_runtime_s`.
- Not adding an edit audit trail or "last edited" timestamp.
- No bulk edit.

---

## Context & Research

### Relevant Code and Patterns

- `lik-ui/src/lik_ui/db.py:369` `create_scheduled_run` and `:413` `set_scheduled_run_paused` — the store
  patterns to mirror: owner-scoped `WHERE id = %s AND user_id = %s`, `RETURNING`, `conn.commit()`,
  `_SCHEDULED_RUN_COLS`.
- `lik-ui/src/lik_ui/account.py:90` `create_scheduled_run` route — the exact validation to reuse
  (`parse_cadence`, the schedulable-agent lookup, `max_runtime` materialization) and the redirect convention
  (`/settings?scheduled=1` on success, `?scheduled_error=1` on rejection).
- `lik-ui/src/lik_ui/account.py:118` `pause_scheduled_run` and `:112` `delete_scheduled_run` — the `{run_id}`
  path-param route shape and owner-scoped no-op-if-not-theirs behavior.
- `lik-ui/src/lik_ui/templates/settings.html:105-139` — the schedule list `<li>`, where the Pause/Delete
  inline forms live and where the Edit button + inline form go.
- `lik-ui/src/lik_ui/account.py:23` `parse_cadence` / `:35` `format_cadence` — cadence parsing/formatting; the
  edit form must pre-select the row's current cadence (see Open Questions: deriving count+unit from the stored
  `run_interval`).

### Institutional Learnings

- CLAUDE.md: **DB schema changes require a non-destructive prod migration.** This plan adds no columns — it only
  writes existing columns — so `db/init.sql` is unchanged and no `ALTER` is needed. Call this out in the PR so a
  reviewer doesn't expect a migration.
- CLAUDE.md: lik-ui tests must target port 5433 and ignore `.env` (`LIK_UI_DB_PORT=5433`).

### External References

- None — this is a convention-following change with strong local patterns (3+ direct examples of the exact
  store/route/template shape). No external research warranted.

---

## Key Technical Decisions

- **Preserve `next_run_at` on edit; do not reset it.** Rationale: editing the message or agent should not change
  *when* the schedule next fires. A cadence change takes full effect after the next completion, since
  `complete_run` (`db.py:498`) already recomputes `next_run_at = now() + run_interval` from the stored interval.
  This keeps the update a plain field write with no scheduling side effects. Alternative (recompute
  `next_run_at = now() + new_interval` on cadence change) is more "immediate" but surprises a user who only fixed
  a typo, and complicates the store method — deferred unless product asks.
- **Edit is allowed regardless of `paused` or in-flight (`started_at`) state**, and does not clear either. An
  in-flight run already read its row; the edit applies to the next cadence. This avoids a special-case guard and
  matches how pause/resume already ignore run state.
- **One combined update method** `update_scheduled_run(run_id, user_id, agent_name, prompt, run_interval,
  max_runtime_s)` rather than field-specific setters — the edit form always submits all three editable fields,
  so a single owner-scoped `UPDATE ... RETURNING` is simplest.
- **Inline expanding form** (per the create form's all-inline convention), toggled client-side. Progressive-
  enhancement note in U3.

---

## Open Questions

### Resolved During Planning

- Edit UX shape: inline expanding form pre-filled per row (user-confirmed), not a dedicated page or a repurposed
  create form.
- Does this need a DB migration? No — no new columns; only existing columns are written.

### Deferred to Implementation

- **Deriving the current cadence's count + unit from the stored `run_interval`** to pre-select the form's
  number + unit dropdown. `format_cadence` produces a display string, not a (count, unit) pair. The implementer
  should add a small helper (e.g. `cadence_parts(interval) -> (count, unit)`) or expose count/unit alongside the
  row for the template — decide the exact shape when wiring the template. Must round-trip with `parse_cadence`
  for the same unit set (weeks when days divide evenly by 7, else days), consistent with `format_cadence`.

---

## Implementation Units

- U1. **Owner-scoped `update_scheduled_run` store method**

**Goal:** Add a store method that updates an existing schedule's agent, prompt, cadence, and derived
`max_runtime_s` in place, scoped to the owner.

**Requirements:** R1, R2, R4

**Dependencies:** None

**Files:**
- Modify: `lik-ui/src/lik_ui/db.py`
- Test: `lik-ui/tests/test_db.py`

**Approach:**
- Add `update_scheduled_run(self, run_id, user_id, agent_name, prompt, run_interval, max_runtime_s) -> bool`
  next to `set_scheduled_run_paused`. Single `UPDATE scheduled_runs SET agent_name=%s, prompt=%s,
  run_interval=%s, max_runtime_s=%s WHERE id=%s AND user_id=%s RETURNING id`, `conn.commit()`, return whether a
  row matched.
- Do **not** touch `next_run_at`, `paused`, `started_at`, or any `last_*` column (see Key Technical Decisions).

**Patterns to follow:**
- `db.py:413` `set_scheduled_run_paused` (owner-scoped `UPDATE ... RETURNING`, bool result).

**Test scenarios:**
- Happy path: create a schedule, call `update_scheduled_run` with new agent/prompt/interval/max_runtime; reload
  via `list_scheduled_runs` and assert all four fields changed.
- Edge case: `next_run_at`, `paused`, and `last_status` are unchanged after an update (assert against the
  pre-edit values).
- Error path (ownership): updating with a different `user_id` returns `False` and mutates nothing (R2).
- Edge case: updating a non-existent `run_id` returns `False`.

**Verification:** `uv run pytest tests/test_db.py` (from `lik-ui`, `LIK_UI_DB_PORT=5433`) passes, including the
ownership and no-side-effect assertions.

---

- U2. **Edit route with create-parity validation**

**Goal:** Add `POST /settings/scheduled-runs/{run_id}/edit` that validates like create and calls
`update_scheduled_run`.

**Requirements:** R1, R2, R3, R4

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/account.py`
- Test: `lik-ui/tests/test_account.py`

**Approach:**
- Mirror `create_scheduled_run` (`account.py:90`): read `agent_name`, `prompt`, `interval_count`,
  `interval_unit` from the form; resolve the schedulable agent option; `parse_cadence`. On any invalid input
  (`option is None or interval is None or not prompt`) redirect to `/settings?scheduled_error=1` **without**
  calling the store. On success call `store.update_scheduled_run(run_id, user["id"], agent_name, prompt,
  interval, option.max_runtime)` and redirect to `/settings?scheduled=1`.
- Owner scoping comes from passing `user["id"]` to the store (no-op if the row isn't theirs), matching
  delete/pause.
- Consider a distinct success flag (e.g. `?scheduled_updated=1`) vs. reusing `?scheduled=1` — reusing keeps the
  template simpler; if a distinct "✓ Schedule updated." message is wanted, thread it through `settings_page`
  like `scheduled_created`. Decide when wiring U3.

**Patterns to follow:**
- `account.py:90` `create_scheduled_run` (validation + redirect), `account.py:118` `pause_scheduled_run`
  (`{run_id}` path param + `require_user`).

**Test scenarios:**
- Happy path: POST an edit changing agent + cadence + prompt; assert 303 → `/settings?scheduled=1` (or the
  chosen success flag) and the stored row reflects all changes.
- Error path: non-schedulable agent → `/settings?scheduled_error=1`, row unchanged.
- Error path: bad cadence (count 0, count > max, unknown unit) → `?scheduled_error=1`, row unchanged.
- Error path: empty prompt → `?scheduled_error=1`, row unchanged.
- Error path (ownership, R2): user B editing user A's schedule leaves A's row unchanged (owner-scoped no-op).
- Auth: unauthenticated POST is rejected (mirror `test_set_agent_visibility_requires_login`).

**Verification:** `uv run pytest tests/test_account.py` passes; new edit tests included in the "scheduled runs"
block.

---

- U3. **Inline Edit button + pre-filled form in the schedule list**

**Goal:** Add an Edit button to each schedule row that toggles an inline form pre-filled with the row's current
agent, cadence, and message, posting to the U2 route.

**Requirements:** R1, R3

**Dependencies:** U2

**Files:**
- Modify: `lik-ui/src/lik_ui/templates/settings.html`
- Modify: `lik-ui/src/lik_ui/account.py` (only if pre-selecting cadence needs a helper / extra template context)
- Modify: `lik-ui/src/lik_ui/static/app.css` (if the toggle needs styling)
- Test: `lik-ui/tests/test_account.py` (render assertions)

**Approach:**
- In the schedule-list `<li>` (`settings.html:107-135`), add an **Edit** button alongside Pause/Delete that
  reveals a hidden inline form for that row. Form action `POST /settings/scheduled-runs/{{ r.id }}/edit`,
  fields identical to the create form (agent `<select>`, cadence number + unit `<select>`, message
  `<textarea>`), each pre-populated from the row: agent option `selected` when it matches `r.agent_name`,
  message value from `r.prompt`, cadence count/unit derived from `r.run_interval` (see Deferred to
  Implementation — add a `cadence_parts` helper or pass count/unit in context).
- Toggle mechanism: prefer a `<details>`/`<summary>` element (no JS) or a tiny click handler consistent with
  the page's existing minimal JS (`settings.html` already uses inline `onchange`/`onsubmit`). A Cancel control
  collapses the form.
- Pre-select the agent `<select>` from the same `schedulable_agents` list used by create; if the row's stored
  `agent_name` is no longer schedulable, still show it as the selected option so the value round-trips (or
  surface it read-only — decide during implementation; keep the row editable for cadence/prompt regardless).

**Execution note:** none.

**Patterns to follow:**
- `settings.html:80-99` create form (field markup, cadence picker, labels) and `:124-133` inline Pause/Delete
  forms (inline form styling, `{{ r.id }}` action).

**Test scenarios:**
- Happy path (render): a user with one schedule sees an Edit control and an edit form whose fields are
  pre-filled — agent option for `r.agent_name` is `selected`, the message `textarea` contains `r.prompt`, and
  the cadence count/unit match the stored interval (assert on the rendered HTML for a week and a multi-day
  schedule).
- Integration: submitting the rendered edit form (posting its fields to the edit route) updates the row —
  extends the U2 happy-path test end-to-end from the pre-filled values.
- Edge case: with no schedules, no edit form renders (existing "You have no scheduled runs." path unaffected).

**Verification:** `uv run pytest tests/test_account.py` passes; manual check that Edit reveals a pre-filled form
and Save updates the row (screenshot for PR per repo demo convention if UI proof is wanted).

---

## System-Wide Impact

- **Interaction graph:** The edit route shares the `create_scheduled_run` validation logic and the
  `list_scheduled_runs` render path; no scheduler/runner code changes. The scanner (`claim_due_runs`) reads the
  edited row on its next scan with no special handling.
- **State lifecycle risks:** Editing must not clear `started_at` (would let the scanner double-run an in-flight
  row) or reset `next_run_at` unexpectedly — U1 explicitly leaves both untouched.
- **API surface parity:** Edit is a new capability with no existing sibling to keep in parity; create/pause/
  delete are unchanged.
- **Unchanged invariants:** `db/init.sql` and the `scheduled_runs` schema are unchanged — no migration. The
  scanner's double-run invariant (reclaim only after `max_runtime_s + margin`) is preserved because
  `max_runtime_s` is only ever re-materialized from the roster, never lowered below the runner's own budget.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Editing an in-flight schedule causes a double-run or lost run | U1 leaves `started_at`/`next_run_at` untouched; edit applies from the next cadence. Covered by the "no side-effect" test in U1. |
| Cadence pre-fill drifts from `format_cadence` (e.g. shows "7 days" where the list shows "every week") | The `cadence_parts` helper must round-trip with `parse_cadence`/`format_cadence` on the same unit rule; U3 render test asserts the pre-selected unit. |
| Stored agent no longer schedulable, so the edit `<select>` can't represent it | U3 shows the stored agent as selected so the value round-trips; cadence/prompt stay editable. |

---

## Documentation / Operational Notes

- No prod DB migration (no schema change). Deploy is the standard `deploy-images.yml` (`service: lik-ui`).
- Per CLAUDE.md, ask the user whether `lik-ui/src/lik_ui/faq.md` should mention that schedules are now editable
  when the PR is opened.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-27-03-scheduled-unattended-agent-runs-requirements.md](docs/brainstorms/2026-07-27-03-scheduled-unattended-agent-runs-requirements.md)
- Related code: `lik-ui/src/lik_ui/account.py`, `lik-ui/src/lik_ui/db.py`, `lik-ui/src/lik_ui/templates/settings.html`
- Related plan: [docs/plans/2026-07-28-002-feat-scheduled-unattended-agent-runs-plan.md](docs/plans/2026-07-28-002-feat-scheduled-unattended-agent-runs-plan.md)
