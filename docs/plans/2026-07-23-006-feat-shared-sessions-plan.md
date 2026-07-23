---
title: "feat: Shared sessions (open by id + Shared toggle, read-only)"
type: feat
status: completed
date: 2026-07-23
---

# feat: Shared sessions (open by id + Shared toggle, read-only)

## Summary

Let a session owner mark a session as **shared** via a checkbox on the Chat page, and let any
authenticated user open a shared session by entering its id in the "Open a session by id" field on
the Sessions page. Non-owners get **read-only** access: they can view the full transcript and attach
to an in-flight turn, but cannot send messages, answer tool prompts, toggle sharing, or delete. Only
the owner ever drives the session, so it always runs on the owner's own vault.

---

## Problem Frame

The "Open a session by id" field (already added to `sessions.html`) 404s for any id the current
user doesn't own, because every session route gates on owner-scoped `store.get_session`. Since
`sessions.session_id` is the PRIMARY KEY (one row, one owner), the field is only useful if opening
can reach sessions the current user does *not* own — but unrestricted cross-user access would leak
every session. A `shared` opt-in flag, set by the owner, is the gate that makes the field useful
without opening all sessions to everyone. Read-only access keeps every write on the owner's own
credentials, so a viewer never acts on the owner's connected data sources.

---

## Requirements

- R1. An owner can toggle a session between private and shared from the Chat page.
- R2. A non-owner who enters a shared session's id opens it exactly like clicking a session link,
  landing on a read-only view of the transcript.
- R3. A non-owner who enters a private (or unknown) session's id still gets "Session not found."
- R4. A non-owner viewing a shared session can read full history and attach to an in-flight turn,
  but **cannot** send messages or answer tool prompts — those paths remain owner-only.
- R5. Write and management actions (send, confirm, delete, toggle `shared`) remain restricted to the
  owner. A non-owner attempting them gets denied without changing state.

---

## Scope Boundaries

- No real-time push of the owner's turn to a viewer's open browser. New messages appear on page load /
  history fetch. A viewer who loads while a turn is in flight still attaches via the existing resume path.
- No per-user copy of a shared session — it is not added to the non-owner's Sessions list. They reopen
  it via the id field each time (matches "as if they clicked a link", which adds nothing to the list).
- No write access for non-owners of any kind — no shared drafting, no multi-user turns. This removes
  the concurrency question entirely.
- No sharing granularity (per-grantee ACLs, share links/tokens, read-vs-write per user).

### Deferred to Follow-Up Work

- Visual "shared by <owner>, read-only" indicator on the Chat page for non-owners: follow-up if wanted.

- **"Copy to my own session"** (from a shared session's Chat page): create a *new* session owned by
  the current user with *their* vault, seeded with a digest of the shared transcript so all new turns
  run on the copier's credentials. Feasibility is confirmed against the SDK, with a known limitation.
  - Mechanism: `create_session(agent_id, environment_id, [copier_vault_id], title)` for the current
    user (mirrors `new_chat` in `lik-ui/src/lik_ui/chat.py`), then seed history from
    `list_events(shared_session_id)` as a single `system_message` (or initial `user_message`), then
    `store.create_session(copier_user_id, ...)` and redirect to the new `/chat/{id}`.
  - **Limitation (honest framing):** this is a *re-prime, not a clone*. `sessions.create` has no
    source/fork parameter, and the event API only accepts user/system-authored events — prior *agent*
    turns, tool results, and thinking cannot be replayed as history. The new session gets a text
    digest of the conversation, not the agent's accumulated internal state.
  - No new data exposure: the copier can already read the shared transcript, so seeding it into their
    own session leaks nothing further. Achieves the goal — the copier's vault backs all new activity.

- **"Transfer session to new owner"** (owner action): reassign a session to a different user, moving
  it onto the recipient's vault. This is a true handoff of the single existing session (option 1 from
  the vault-ownership discussion), not a copy.
  - Mechanism: `sessions.update(session_id, vault_ids=[recipient_vault_id])` to repoint the live
    session's credentials [confirmed: `update` accepts `vault_ids`], plus a store update reassigning
    the row's `user_id` to the recipient. After transfer the original owner keeps access only if the
    session is `shared`.
  - **Consequences to design before building:** it mutates the one shared session (no copy), so the
    original owner loses ownership; ensure the recipient has a provisioned vault first
    (`ensure_user_vault`); decide whether an in-flight turn must be idle before transfer; and confirm
    the recipient consents (a transfer silently moves someone else's conversation and its future
    credential use onto them). Ownership reassignment should be a deliberate, confirmed action.

---

## Context & Research

### Relevant Code and Patterns

- `lik-ui/src/lik_ui/db.py` — `Store`; `get_session(session_id, user_id)` (owner-scoped, already returns
  `user_id`), `create_session`, `list_sessions`, `delete_session`. Add sharing queries here.
- `lik-ui/src/lik_ui/chat.py` — session routes gate on `store.get_session`:
  - View paths (widen to shared): `chat_page` (L365), `chat_history` (L392), `chat_resume` (L414).
  - Write paths (stay owner-only): `chat_stream` (L443), `chat_confirm` (L453), `delete_session` (L344).
- `lik-ui/src/lik_ui/templates/chat.html` — `#chat-controls`, the `#auto-approve` block, and `#composer` are
  owner-only controls to hide for a non-owner; the Shared checkbox is added here for the owner. Both
  driven by a new `is_owner` flag passed from `chat_page`.
- `lik-ui/src/lik_ui/templates/sessions.html` — "Open a session by id" form already navigates to
  `/chat/<id>` with `encodeURIComponent`; no change needed once server access widens.
- `lik-ui/db/init.sql` — `sessions` table DDL. Drop-and-recreate for the schema change (drafting mode).
- Delete form in `sessions.html` (POST `/sessions/delete` + hidden `session_id` + `confirm()`) is the
  pattern to mirror for the Shared toggle form.

### Institutional Learnings

- CLAUDE.md: schema changes prefer drop/recreate (`docker compose down -v && up -d`), no migrations.
- CLAUDE.md: keep designs store-agnostic — nothing here is Confluence/Jira-specific.

---

## Key Technical Decisions

- **Grant read access, don't copy rows.** `session_id` is the PK, so a non-owner cannot get their own
  row. Sharing widens *read access* to the single existing row; it does not duplicate it. Rationale:
  simplest model that satisfies "open as if clicked" without a composite-key/junction-table change.
- **Two access levels, one new accessor.** Keep `get_session` (owner-only) for all writes + delete +
  toggle. Add `get_accessible_session(session_id, user_id)` = the row if the user owns it **or** it is
  `shared`. Only the three view routes use the accessor.
- **Read-only removes the concurrency problem.** Because non-owners never send or confirm, there is no
  second driver and no need for a turn-serialization gate. The owner's session always runs on the
  owner's vault; a viewer never acts on the owner's credentials.
- **Hide write controls for non-owners, not just block routes.** The composer, auto-approve, and Shared
  checkbox render only when `is_owner`, so a viewer sees a clean read-only page. Server routes still
  re-check ownership — never trust the hidden UI.

---

## Open Questions

### Resolved During Planning

- Read-only vs full interaction for non-owners → **read-only** (user decision), so viewers never act on
  the owner's credentials and there is no concurrency to manage.
- How to make the id field work → widen server-side read access for shared sessions; form is unchanged.

### Deferred to Implementation

- Whether `chat_resume` for a non-owner should stream or no-op: default to allowing it (read-only
  observation of an in-flight turn); revisit only if it proves confusing.

---

## High-Level Technical Design

> *Illustrates the intended approach and is directional guidance for review, not implementation
> specification. Treat as context, not code to reproduce.*

```
Open by id (Sessions page form)  ──GET──▶ /chat/{id}
    chat_page → get_accessible_session(id, uid)
        owner OR shared?  ── no ─▶ 404 "Session not found."
                          ── yes ─▶ render chat.html
                                     is_owner → show composer + auto-approve + Shared checkbox
                                     viewer   → transcript only (read-only)

View  (history / resume)  → get_accessible_session   (owner OR shared)
Write (stream / confirm)  → get_session               (owner-only → 404 for viewers)
Toggle  ──POST──▶ /chat/{id}/share  → get_session (owner-only) → set_session_shared
Delete  ──POST──▶ /sessions/delete  → get_session (owner-only, unchanged)
```

---

## Implementation Units

- U1. **Add `shared` column to the sessions schema**

**Goal:** Persist the per-session sharing flag.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `lik-ui/db/init.sql`

**Approach:**
- Add `shared boolean NOT NULL DEFAULT false` to the `sessions` table DDL.
- Drop-and-recreate the DB per project convention (`docker compose down -v && docker compose up -d`);
  no migration script.

**Test scenarios:**
- Test expectation: none — DDL only; behavior is exercised through the store tests in U2.

**Verification:**
- Fresh DB has `sessions.shared` defaulting to `false`.

---

- U2. **Store: sharing queries**

**Goal:** Give the app owner-scoped and shared-scoped read access, plus an owner-only toggle.

**Requirements:** R2, R3, R5

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/db.py`
- Test: `lik-ui/tests/test_db.py`

**Approach:**
- Add `shared` to the `SELECT` column lists in `get_session` and `list_sessions` (and any row the
  routes/templates read).
- Add `get_accessible_session(session_id, user_id)`: returns the row when
  `session_id = %s AND (user_id = %s OR shared = true)`.
- Add `set_session_shared(session_id, user_id, shared)`: owner-scoped
  `UPDATE ... SET shared = %s WHERE session_id = %s AND user_id = %s`; returns whether a row changed.

**Patterns to follow:** existing owner-scoped queries in `Store` (`get_session`, `delete_session`).

**Test scenarios:**
- Happy path: owner marks shared → `get_accessible_session` returns the row for a *different* user.
- Edge case: private session → `get_accessible_session` returns None for a non-owner, row for the owner.
- Edge case: unknown session_id → `get_accessible_session` returns None.
- Happy path: `set_session_shared` by owner flips the flag; re-read shows new value.
- Error path (R5): `set_session_shared` by a non-owner changes nothing and reports no row changed.
- Happy path: newly created session has `shared = false`.

**Verification:**
- New store methods behave as above against the real (dropped/recreated) DB used in tests.

---

- U3. **Read-only view for non-owners**

**Goal:** Let a non-owner open and read a shared session while write paths and controls stay owner-only.

**Requirements:** R2, R3, R4, R5

**Dependencies:** U2

**Files:**
- Modify: `lik-ui/src/lik_ui/chat.py` (`chat_page`, `chat_history`, `chat_resume`)
- Modify: `lik-ui/src/lik_ui/templates/chat.html`
- Test: `lik-ui/tests/test_chat.py`

**Approach:**
- Swap `get_session` → `get_accessible_session` in `chat_page`, `chat_history`, `chat_resume` only.
  Leave `chat_stream`, `chat_confirm`, and `delete_session` on `get_session` (owner-only → 404/redirect
  for a non-owner). This is the R4/R5 boundary — review each route explicitly.
- In `chat_page`, compute `is_owner = session["user_id"] == user["id"]` and pass it to the template.
- In `chat.html`, gate `#composer`, `#auto-approve`, and `#chat-controls`-write affordances behind
  `is_owner`, so a viewer sees a read-only transcript. (`chat.js`'s send/confirm wiring is a no-op with
  no composer present; confirm the script tolerates a missing `#composer`.)
- No change to the `sessions.html` form — this unit is what makes the already-present "Open by id"
  field resolve for shared ids.

**Patterns to follow:** existing route bodies; template context dict in `chat_page`.

**Test scenarios:**
- Covers R2. Owner shares a session; a second logged-in user GETs `/chat/{id}` → 200, transcript renders.
- Covers R3. Second user GETs `/chat/{id}` for a *private* session → 404 "Session not found."
- Covers R3. Any user GETs `/chat/{unknown}` → 404.
- Happy path (R4): non-owner GETs `/chat/{id}/history` on a shared session → 200 with events.
- Covers R5. Non-owner GETs `/chat/{id}/stream?message=…` on a shared session → 404, and
  `send_and_stream` is NOT called (assert on the fake).
- Covers R5. Non-owner GETs `/chat/{id}/confirm...` on a shared session → 404; `confirm_and_stream`
  not called.
- Rendering: non-owner's page has no `#composer`; owner's page does.
- Happy path: owner still opens their own private session with the composer present (no regression).

**Verification:**
- Entering a shared id in the Sessions "Open by id" field lands on a read-only chat page for a
  non-owner; the send box is absent and send/confirm requests 404.

---

- U4. **Shared toggle: route + Chat page checkbox (owner-only)**

**Goal:** Owner can turn sharing on/off from the Chat page.

**Requirements:** R1, R5

**Dependencies:** U2, U3

**Files:**
- Modify: `lik-ui/src/lik_ui/chat.py` (new POST `/chat/{session_id}/share`)
- Modify: `lik-ui/src/lik_ui/templates/chat.html`
- Test: `lik-ui/tests/test_chat.py`

**Approach:**
- New route reads the form, resolves the owner row via `get_session` (owner-only), calls
  `set_session_shared`, and redirects back to `/chat/{session_id}` (303). Non-owner/unknown → redirect
  or 404 without changing state.
- In `chat.html`, render the Shared control only when `is_owner`, reflecting current `session.shared`.
  Product-level UI form (submit-on-change vs checkbox + Save button, exact label/copy) is the
  planner's/implementer's to finalize; mirror the existing delete-form POST pattern.

**Patterns to follow:** `delete_session` route + `sessions.html` delete form (POST + hidden field).

**Test scenarios:**
- Covers R1. Owner POSTs share=on → redirect; `get_accessible_session` now returns the row for another user.
- Happy path: owner POSTs share=off → a previously-allowed non-owner now gets 404 on `/chat/{id}`.
- Error path (R5): non-owner POSTs to `/chat/{id}/share` → flag unchanged.
- Rendering: owner's chat page shows the Shared control; a non-owner's view of the same session does not.

**Verification:**
- Toggling the checkbox flips shared read-visibility for other users end-to-end.

---

## System-Wide Impact

- **Interaction graph:** Six session routes read access via the store. Only the three view routes move
  to `get_accessible_session`; the three write/manage routes keep `get_session`. Getting this split
  wrong is the main correctness risk — enumerate each route in review.
- **API surface parity:** `chat_stream` and `chat_confirm` are the two write paths and must both stay
  owner-only; hiding the composer is UX, the 404 on those routes is the real guard.
- **Unchanged invariants:** `list_sessions` stays per-owner (shared sessions don't appear in a
  non-owner's list); `delete_session` stays owner-scoped; sessions always run on the owner's vault.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Access-split mistake widens a write route to non-owners. | View routes use the accessor; write/manage routes keep `get_session`. U3/U4 tests assert non-owners get 404 on stream/confirm and cannot delete or toggle. |
| Shared transcript exposes the owner's conversation content to viewers. | Intended — that is what sharing is. It is an owner opt-in per session; consider a follow-up "shared, read-only" notice so the owner sees the exposure. Read-only means no *new* actions on the owner's data sources. |
| `chat.js` errors when the composer is absent for viewers. | Guard the send/confirm wiring against a missing `#composer`; covered by U3 rendering tests. |
| Users expect live updates of the owner's turns. | Out of scope and stated; new messages surface on reload/history, and resume attaches to an in-flight turn on load. |

---

## Sources & References

- Related code: `lik-ui/src/lik_ui/chat.py`, `lik-ui/src/lik_ui/db.py`, `lik-ui/db/init.sql`,
  `lik-ui/src/lik_ui/templates/chat.html`, `lik-ui/src/lik_ui/templates/sessions.html`
- Tests: `lik-ui/tests/test_chat.py`, `lik-ui/tests/test_db.py`, `lik-ui/tests/conftest.py` (`FakeSessionsClient`)
