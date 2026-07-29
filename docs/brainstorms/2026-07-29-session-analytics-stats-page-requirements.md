---
date: 2026-07-29
topic: session-analytics-stats-page
---

# Session Analytics & `/stats` Page

## Summary

Two analytics pages report per-session usage (sessions over time, tokens, tool use, errors), each split into
live and deleted sessions. Because physical deletion destroys the platform transcript, every session deletion
first writes a durable analytics record — with full usage when it can be read, and flagged with a reason when
it can't — so no deletion ever goes uncounted. Live sessions get their numbers from a lightweight on-demand
platform read.

---

## Problem Frame

lik-ui has no usage analytics today. Token usage is observed only transiently mid-stream and then discarded,
and the sessions table stores almost no usage data. Once a session is physically deleted — which happens
routinely, since auto-delete is mandatory (default 7 days) and runs daily via the prune job — everything about
that session is gone from both the local DB and the Managed Agents platform. That means the sessions people
actually used and let expire, which is most of them, are exactly the ones about which nothing can ever be
learned. An operator wanting to know how much the product is used, by whom, with which agents and integrations,
and at what token cost, currently has no way to find out, and the window to capture it closes permanently at
each deletion.

---

## Actors

- A1. Session owner: a logged-in user viewing analytics for their own sessions on `/stats`.
- A2. Operator: a logged-in user viewing cross-user analytics on `/all-stats` (today any authenticated user;
  real access control is deferred).
- A3. Deletion trigger: any of the four code paths that physically delete a session (manual single delete,
  delete-all, the prune retention job, and stale-session self-heal). Each must produce an analytics record.

---

## Key Flows

- F1. Capture-before-delete
  - **Trigger:** any session deletion (A3), regardless of which of the four paths initiates it.
  - **Actors:** A3.
  - **Steps:** (1) Before the platform transcript and local row are removed, attempt to read the session's
    usage and derived counts from the platform. (2) Write a deleted-session analytics record. (3) If the read
    succeeds, the record carries full usage. (4) If the read fails — including the self-heal case where the
    platform session is already gone — the record is still written from the session's known local fields and
    flagged with the reason capture was incomplete. (5) Proceed with the existing deletion.
  - **Outcome:** exactly one analytics record exists per deleted session; deletion is never blocked by
    analytics.
  - **Covered by:** R5, R6, R7, R8, R9.

- F2. View analytics
  - **Trigger:** A1 opens `/stats`, or A2 opens `/all-stats`.
  - **Actors:** A1, A2.
  - **Steps:** (1) The page shows two sections: live sessions and deleted sessions. (2) Live-session numbers
    are read on demand from the platform (lightweight). (3) Deleted-session numbers come from the stored
    analytics records. (4) `/stats` is scoped to the viewer's own sessions; `/all-stats` spans all users.
  - **Outcome:** the viewer sees usage over time and totals across both live and deleted sessions.
  - **Covered by:** R1, R2, R3, R4, R10, R11, R12.

---

## Requirements

**Pages and access**
- R1. Add a `/stats` page showing analytics for the logged-in viewer's own sessions only.
- R2. Add a "Stats" link to the top navigation, positioned immediately after the "Settings" link, pointing to
  `/stats`.
- R3. Add an `/all-stats` page showing analytics across all users' sessions. It is not linked in the
  navigation and is reached only by typing the URL.
- R4. `/all-stats` requires a logged-in user but applies no further access restriction in this version;
  proper access control is explicitly deferred (see Scope Boundaries).

**Analytics capture on deletion**
- R5. Every session deletion writes exactly one durable analytics record before the session is physically
  removed, so the data survives deletion of the platform transcript and local row.
- R6. The capture is a single shared step that all four deletion paths route through: manual single delete,
  delete-all, the prune retention job, and stale-session self-heal.
- R7. Each analytics record captures, when readable: token usage (input, output, and cache-read /
  cache-creation broken out separately), active and wall-clock time, user-message count, AI-message count,
  total tool-use count with a per-tool and per-MCP-server breakdown, error count with error types, the agent
  used, and the session's lifespan (created and deleted timestamps) and how it was deleted (which path).
- R8. If the pre-delete usage read fails, the record is still written using the session's known local fields
  and flagged with the reason capture was incomplete, so missing analytics are counted and visible rather than
  silently absent.
- R9. The self-heal path — where the platform session is already gone and nothing can be read — also writes a
  flagged record, so even platform-lost sessions are counted.

**What the pages show**
- R10. Each page is split into a live-sessions section (not yet deleted) and a deleted-sessions section.
- R11. Live-session numbers are obtained by a lightweight on-demand read per live session at view time,
  yielding cumulative token usage, timing, and status. The heavier per-message / per-tool / per-error tallies
  are not shown for live sessions; they appear only once a session has been deleted and captured.
- R12. Each page presents both totals and a time-based view of sessions and tokens (a "sessions per user /
  tokens over time" view). On `/stats` the per-user dimension collapses to the single viewer.

---

## Acceptance Examples

- AE1. **Covers R5, R7.** Given a session with recorded turns, when it is deleted through any path with the
  platform reachable, then a record exists afterward containing its token usage, timing, message counts,
  tool-use breakdown, error detail, agent, and deletion path — and the record is not flagged.
- AE2. **Covers R8.** Given a session that is deleted while the usage read fails, when deletion completes, then
  a record still exists, populated from local fields and flagged as incomplete — and the deletion itself
  succeeded.
- AE3. **Covers R9.** Given a session dropped by self-heal because the platform already lost it, when the drop
  completes, then a flagged "lost before capture" record exists for it.
- AE4. **Covers R11.** Given a viewer with active (undeleted) sessions, when they open `/stats`, then the live
  section shows each session's cumulative tokens, timing, and status, and does not show per-tool or
  per-message tallies for those live sessions.
- AE5. **Covers R1, R3.** Given two different users each with sessions, when user A opens `/stats`, they see
  only their own sessions; when user A opens `/all-stats`, they see sessions from both users.

---

## Success Criteria

- An operator can answer "how much is the product being used, by whom, with which agents, and at what token
  cost" from `/all-stats`, including for sessions that have already been deleted.
- No session deletion after this ships is absent from analytics: every deletion yields a record, and any record
  that couldn't be fully captured is visibly flagged rather than missing.
- `/stats` loads acceptably for a normal user's own session count without a noticeable per-session read stall.
- A downstream implementer can build from this doc without having to decide the audience/access model, which
  metrics to record, where live numbers come from, or which deletion paths capture — all are settled here.

---

## Scope Boundaries

- Real access control / admin roles on `/all-stats` — deferred; this version only requires a logged-in user.
- Persisting live-session usage into the DB or periodic snapshotting — live numbers stay on-demand.
- Full per-event detail (message / tool / error tallies) for live sessions — deleted sessions only.
- Backfill of sessions deleted before this ships — unrecoverable; only post-ship deletions get records.
- Any change to deletion or retention behavior itself (cadence, the mandatory auto-delete, the prune job).
- Export/CSV, dollar-cost pricing, and cross-workspace analytics.

---

## Key Decisions

- Audience split into two pages: `/stats` (own data, navbar-linked) and `/all-stats` (all users, unlinked).
  Rationale: the operator wants a cross-user view, but exposing everyone's usage to every user by default is
  wrong; keeping the cross-user view unlinked with access control deferred lets the operator use it now without
  committing to an admin model that doesn't exist yet.
- Capture happens at deletion time, not via continuous snapshotting. Rationale: the only moment the data is
  both complete and about to be lost is right before deletion; a single capture step is far simpler than
  keeping a live mirror in sync, and it fits all four existing deletion paths.
- Always write a record, even on capture failure or self-heal. Rationale: a silently missing record looks
  identical to "no session existed," which would quietly bias every aggregate; a flagged record keeps the
  denominator honest.
- Live sessions use a lightweight read (cumulative usage + timing + status), not the full event tally.
  Rationale: the full tally needs a per-event pass per session, which is too costly on every page load; the
  cheap read still delivers the tokens-and-time numbers the pages are about.

---

## Dependencies / Assumptions

- The platform exposes, per session, cumulative token usage (including cache-read / cache-creation) and
  active/wall-clock timing in a single lightweight read, and exposes the per-event stream needed to tally
  message, tool-use (with tool and server identity), and error counts. [Certain — verified against the
  installed SDK during the brainstorm.]
- The four deletion paths named in R6 are the complete set today. [Certain — verified in the current
  codebase.]
- There is a live production database; schema changes must be applied as non-destructive, additive migrations
  (not a drop-and-recreate), and the production DB must be migrated as a separate step from merging the code.
- `/all-stats`' live section may be slow when many sessions exist, since it reads each live session on demand;
  acceptable for this version, with caching left as later work.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R7][Technical] Exact shape and storage of the captured record (fields, types, how the per-tool /
  per-server breakdown and error types are stored), and the migration to add it.
- [Affects R6][Technical] Where the single shared capture step lives so all four deletion paths — including the
  separately-run prune job — invoke it without duplication.
- [Affects R12][Design] The concrete visualization (chart types, table columns, time bucketing) for the
  totals and over-time views.
- [Affects R4][User decision, deferred] What the eventual access-control model for `/all-stats` should be
  (admin allowlist, role, etc.) when it is time to secure it.
