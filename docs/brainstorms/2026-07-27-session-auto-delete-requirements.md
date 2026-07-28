---
date: 2026-07-27
topic: session-auto-delete
---

# Chat Session Auto-Delete

## Summary

Every chat session gets an auto-delete date, defaulting to 7 days after the session is created. Users can
change the date from the session UI but cannot disable auto-delete entirely. A daily scheduled GitHub Action
finds and deletes sessions whose date has passed — destroying both the local pointer row and the real
transcript on the Anthropic Managed Agents platform — without exposing any internet-facing delete endpoint.

---

## Problem Frame

Chat sessions accumulate indefinitely. Each Postgres `sessions` row is only a pointer; the real chat
transcript and any stored credentials live on the Anthropic Managed Agents platform. Retained sessions are
both a storage/cost liability and a data-minimization concern — old conversations and their credentials stay
alive on the platform with no expiry. Today the only way a session leaves is if a user manually deletes it
(per-session or delete-all); nothing ages out on its own.

Because deletion is irreversible and destroys real transcripts, an automatic timer that silently removes data
is a sharp tool: it has to be predictable to the user (they can see when a session will go and push that date
out) and it must actually delete the platform-side data, not just the local pointer.

---

## Actors

- A1. **Session owner**: an authenticated end user who owns sessions, views their upcoming delete date, and can
  push the date out.
- A2. **Scheduled cleanup job**: the daily GitHub Action that finds expired sessions and deletes them on both
  the platform and the database. Runs unattended with no human in the loop.

---

## Key Flows

- F1. **User adjusts a session's delete date**
  - **Trigger:** Owner opens a session's settings surface.
  - **Actors:** A1
  - **Steps:** Owner sees the current auto-delete date → chooses a new date → the date is saved for that
    session (owner-scoped).
  - **Outcome:** The session's auto-delete date is updated; the new date drives future cleanup.
  - **Covered by:** R2, R3, R5

- F2. **Daily unattended cleanup**
  - **Trigger:** Scheduled daily run of the GitHub Action.
  - **Actors:** A2
  - **Steps:** Job authenticates to AWS via OIDC → obtains DB credentials → finds all sessions whose
    auto-delete date has passed → for each, deletes the platform session first, then the database row →
    reports how many were deleted.
  - **Outcome:** Expired sessions are gone from both the platform and the database. Non-expired sessions are
    untouched.
  - **Covered by:** R6, R7, R8, R9
  - **Escape path:** If a platform deletion fails for one session, the run continues with the others and
    surfaces the failure rather than aborting the whole batch or deleting the row without the transcript.

---

## Requirements

**Auto-delete date (data + behavior)**
- R1. Each session has an auto-delete date. New sessions default to 7 days after creation.
- R2. The owner can change a session's auto-delete date to a later (or earlier) date.
- R3. A session always has an auto-delete date; there is no option to keep a session forever. (Users push the
  date out instead.)
- R4. Existing sessions (created before this feature) receive an auto-delete date derived from their creation
  date plus the default window, so no session is left without a date.

**User-facing surface**
- R5. The auto-delete date is visible and editable on the same per-session surface used for existing
  per-session settings (mirroring the existing share toggle), scoped to the session owner.
- R6. Sessions nearing their auto-delete date are visually flagged in the UI (e.g. "deletes in 2 days"). No
  email or push notification is sent.

**Scheduled cleanup**
- R7. A scheduled job runs once per day and deletes every session whose auto-delete date has passed.
- R8. For each expired session, the job deletes the platform session before deleting the database row, matching
  the existing manual-delete ordering, so a transcript is never orphaned by a deleted pointer.
- R9. The cleanup runs without any internet-facing delete endpoint and without a long-lived shared secret: it
  authenticates to AWS via the existing GitHub OIDC trust, reads database credentials from the existing secret
  store, and connects directly to the database.
- R11. The cleanup deletes platform sessions using the one shared Anthropic API key
  (`/ik-arch/prod/shared/ANTHROPIC_API_KEY`) — the same key the app and the deploy workflows use — fetched
  from SSM at run time via a GitHub OIDC role scoped to reading only that parameter. Using the app's own key
  guarantees permission to delete sessions the app created.
- R10. A single expired session that fails to delete does not abort the run; the job continues with the rest and
  makes the failure visible in its output.

---

## Acceptance Examples

- AE1. **Covers R1.** Given a user starts a new chat, when the session is created, then its auto-delete date is
  set to 7 days from creation.
- AE2. **Covers R2, R3.** Given a session that will auto-delete tomorrow, when the owner changes the date, then
  the new date is saved; there is no control that removes the date entirely.
- AE3. **Covers R7, R8.** Given a session whose auto-delete date passed yesterday, when the daily job runs, then
  the platform session is deleted first and then the database row, and the session no longer appears for the
  user.
- AE4. **Covers R7.** Given a session whose auto-delete date is in the future, when the daily job runs, then the
  session is left untouched.
- AE5. **Covers R6.** Given a session within the warning window, when the owner views their sessions, then that
  session is visually flagged with its upcoming deletion.
- AE6. **Covers R10.** Given two expired sessions where the platform deletion of the first fails, when the job
  runs, then the second is still processed and the first's failure is reported (its row is not deleted without
  its transcript).

---

## Success Criteria

- Sessions age out automatically: a session left alone disappears — platform transcript and database row both —
  on its date, with no manual action.
- Users are never surprised: before a session is deleted they can see its date and push it out.
- No transcript is ever orphaned (row deleted while platform data remains) and no run is aborted by a single
  failure.
- Downstream handoff: `ce-plan` can implement without inventing product behavior — default window, no-opt-out
  rule, warning surface, cleanup trust model, and delete ordering are all fixed here.

---

## Scope Boundaries

- No email, push, or other out-of-app notification before deletion — in-app visual flag only.
- No permanent "keep forever" / opt-out of auto-delete.
- No user-facing or internet-facing HTTP endpoint for triggering deletion.
- No long-lived shared secret between GitHub and the app.
- No soft-delete / trash / undo / recovery window — deletion is immediate and irreversible (consistent with
  today's manual delete).
- No per-user or org-wide configurable default window in v1 — the default is fixed at 7 days.

---

## Key Decisions

- **Cleanup runs itself; the app is not called.** Lightsail container service has no run-one-off-task or
  exec primitive, so there is no way for the job to "invoke cleanup internally" on the app. The DB is
  intentionally publicly reachable (containers can't reach the private endpoint), and CI already holds an OIDC
  path to read DB credentials and the platform API key. So the scheduled job does the work directly against the
  DB and platform. Rationale: satisfies "no public delete endpoint, no shared secret" — the only shape that
  fits current infra without new endpoints.
- **No opt-out, only reschedule.** Guarantees every session eventually ages out (data-minimization goal) while
  still letting users protect a session by pushing its date out. Rationale: a permanent opt-out reopens the
  unbounded-retention problem this feature exists to close.
- **Reuse the existing platform-first-then-row delete ordering.** Manual delete already does this; the cleanup
  must not diverge. Rationale: prevents orphaned transcripts.
- **One shared Anthropic key in SSM; the GitHub secret is retired.** The Anthropic API key is a single value
  used by the lik-ui container, the deploy workflows, and this cleanup job, so it lives once at
  `/ik-arch/prod/shared/ANTHROPIC_API_KEY` and every consumer reads it from there via GitHub OIDC. The old
  `ANTHROPIC_API_KEY` GitHub secret and the per-app `/lik-ui/LIK_UI_ANTHROPIC_API_KEY` param are removed.
  Rationale: the app's own key is the only key guaranteed able to delete app-created sessions (a separate CI
  key risks deleting DB rows while leaving transcripts alive), and a single source of truth means one place to
  rotate. Workflows authenticate with a dedicated OIDC role scoped to `ssm:GetParameter` on only that shared
  parameter — deliberately narrower than the terraform-apply role. (This consolidation is a prerequisite,
  landed separately from the auto-delete feature.)
- **In-app warning, not silent.** Chosen over pure silent deletion at low cost to reduce the surprise of
  irreversible auto-deletion.

---

## Dependencies / Assumptions

- **Production schema change is a separate manual step.** Adding the auto-delete date to the live `lik-prod-db`
  requires a non-destructive `ALTER TABLE ... ADD COLUMN`; re-running `init.sql` will not add it to the existing
  table. The default-window backfill for existing rows (R4) is part of this migration. This must be applied to
  prod by hand, separate from merging the code.
- **The GitHub OIDC role may need a small permission/scoping change** to read the DB credential it needs for
  cleanup (the existing apply role can read SSM params; whether the cleanup job reuses that role or gets a
  narrower one is a planning decision).

---

## Outstanding Questions

### Resolve Before Planning

- *(Resolved 2026-07-27)* The key-mismatch risk is closed by R11/Key Decisions: the cleanup uses the one
  shared `ANTHROPIC_API_KEY` from SSM (same key the app uses), read via a dedicated minimal OIDC role. The
  key consolidation is landing as a separate prerequisite change. No open blocker remains.

### Deferred to Planning

- [Affects R9][Technical] Whether the cleanup job reuses the existing OIDC apply role (broad DB master creds) or
  gets a narrower dedicated role/credential.
- [Affects R6][Technical] The exact warning window (how many days before deletion a session is flagged) and how
  the flag renders in the sessions list / chat page.
- [Affects R7][Technical] How the job reuses lik-ui's existing deletion logic (e.g. importing the app's
  `Store` + platform-client code from a small script vs. reimplementing) so the ordering in R8 stays in one
  place.
- [Affects R2][User decision, minor] Whether editing the date offers freeform date entry or preset windows
  (e.g. +7d / +30d). Product-level form; final control is the planner's to choose.
