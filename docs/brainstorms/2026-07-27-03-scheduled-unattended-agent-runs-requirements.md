---
date: 2026-07-27
topic: scheduled-unattended-agent-runs
---

# Scheduled, unattended agent runs (self-service, table-driven)

## Summary

Users schedule recurring agent runs from a "Scheduled runs" section of the lik-ui Settings page, each run
executing as its creator using that user's own vault. A `scheduled_runs` table is the cron-like state of
record — it holds, per schedule, when a run last started and completed and when it is next due. A GitHub
Actions workflow runs on a fixed cadence, scans the table for due schedules, runs each to completion as the
owning user, records the run as a session in that user's Sessions page, and updates the timing. First use is
the Confluence catalog sync. Routine writes auto-approve; ambiguous items skip-and-record so the run always
completes; failures and skips are pushed to the owner. Because the disposable CI runner owns the run and the
table owns the state, lik-ui gains no long-running background system.

---

## Problem Frame

Running the catalog sync today requires a human: someone opens lik-ui, picks the Catalog Registration Agent,
and types a message to trigger `sync-catalog-from-project-indexes`. Nothing runs a skill on its own — a skill
only executes inside an agent session, and sessions are created interactively. So keeping the Catalog fresh
depends on someone remembering to do it, and the crawl is documented as expensive enough that it's "run on
demand only."

More broadly, there is no way for a user to say "run this agent for me on a cadence" — every run is a manual,
attended chat. The companion brainstorm
[`2026-07-27-02-catalog-refresh-due-ttl`](2026-07-27-02-catalog-refresh-due-ttl-requirements.md) makes the
routine catalog run *cheap* and leaves open how it — and the periodic full sweep — is *triggered on a
cadence*. This feature supplies that trigger, generalized: a self-service way to schedule any eligible agent
to run unattended.

The hard part is not the schedule. It is running an agent with no human present *safely*: something must
supply credentials, decide what to do where the agent would normally pause for a person, avoid running the
same job twice or leaving a dead job stuck, and make the result — including anything skipped or failed —
reach someone who will act on it.

---

## Actors

- A1. Scheduling user: a logged-in lik-ui user who creates and manages their own scheduled runs in Settings.
  Runs execute as them, using their vault, and land in their Sessions page.
- A2. Scanner/runner (GitHub Actions): fires on a fixed cadence, finds due schedules, and runs each to
  completion. Disposable and long-run-capable.
- A3. `scheduled_runs` table: the cron-like state of record — what to run, as whom, how often, when last run,
  whether in flight, when next due, and the last outcome.
- A4. Agent (first instance: Catalog Registration Agent): runs the session and invokes the target skill.

---

## Key Flows

- F1. Create a schedule
  - **Trigger:** a user opens the "Scheduled runs" section of Settings.
  - **Actors:** A1, A3
  - **Steps:** User picks an eligible target agent and a triggering prompt/run mode, sets a cadence, and saves
    → a `scheduled_runs` row is created, owned by that user, with an initial next-due time.
  - **Outcome:** a recurring run exists, bound to the user's own vault; the user can edit or delete it.
  - **Covered by:** R1, R2, R3, R13

- F2. Scan and run due schedules
  - **Trigger:** the GitHub Actions cadence fires.
  - **Actors:** A2, A3, A4, A1 (as identity)
  - **Steps:** The runner scans `scheduled_runs` for rows that are due and not in flight → atomically claims
    each (marks it in flight) → drives the agent session to completion as the owner, using the owner's vault,
    auto-approving routine writes and skipping-and-recording ambiguous items → records the run as a session
    owned by that user → writes completion, the run outcome, and the next-due time. On failure or any skip,
    the owner is notified.
  - **Outcome:** due schedules ran exactly once each; each has an updated next-due time and a recorded
    outcome; the Catalog is refreshed.
  - **Covered by:** R4, R5, R6, R7, R8, R9, R10, R11, R12, R14, R15, R17, R18

- F3. Review or resolve a run
  - **Trigger:** the owner is notified of a failed run or a run that skipped items (or browses Settings).
  - **Actors:** A1
  - **Steps:** Owner opens the run from their Sessions page or the Scheduled runs list → reviews the
    transcript and recorded skips → acts (re-auth a lapsed connection, send a follow-up to process a
    held-back page, edit or pause the schedule).
  - **Outcome:** skipped/failed work is handled without waiting for the next cadence.
  - **Covered by:** R4, R8, R16, R17

---

## Requirements

**Scheduling UI (Settings)**
- R1. lik-ui's Settings page has a "Scheduled runs" section where a logged-in user can create, view, edit, and
  delete their own scheduled runs. A scheduled run names a target agent, a triggering prompt or run mode, and
  a cadence.
- R2. A scheduled run executes as its creator, using that user's own vault. A user can only see and manage
  their own schedules; there is no scheduling on another user's behalf.
- R13. Only agents explicitly marked unattended-safe are offered as schedulable targets. Eligibility is a
  manual flag on the agent's roster entry (a `schedulable`-style attribute in the lik-ui agent roster), set by
  whoever curates the roster — an author's assertion that the agent's skills carry safe unattended defaults
  (R10–R12), since that is a judgment about skill instructions no automatic marker can verify. R14 is the
  guardrail behind the flag. Adding a schedule for a flagged agent is configuration; marking an agent
  unattended-safe (and authoring it to be so) is separate work.

**Schedule state (`scheduled_runs`)**
- R3. A `scheduled_runs` store records each schedule plus the timing needed to decide when it runs: at least
  when it is next due, whether a run is currently in flight, and when a run last started and completed.
  (Working column names — `next_run_at`, `started_at`, `completed_at` — are illustrative; the concrete schema
  is the planner's to finalize.) It is applied non-destructively as a new table; migrating the production
  database is a separate, required step from merging the code.
- R4. Each run's outcome is recorded on the schedule (at least a last-run status and any error / skip summary)
  so the owner and the UI can tell whether the most recent run succeeded, skipped items, or failed.

**Scan-and-run (GitHub Action)**
- R5. A GitHub Actions workflow runs on a fixed cadence, scans `scheduled_runs` for rows that are due and not
  already in flight, and runs each due schedule. Its cadence bounds scheduling granularity.
- R6. Claiming a due row is atomic: a row picked up by one scan is marked in flight so a later or concurrent
  scan cannot run it a second time.
- R7. For each claimed schedule, the runner drives the agent session to completion using the owner's vault,
  then records completion, the outcome (R4), and the next-due time.
- R8. Every unattended run is recorded as a session owned by the scheduling user, so it appears in that user's
  Sessions page and can be opened, reviewed, and resumed / messaged / confirmed exactly as an
  interactively-created session can.
- R9. The runner owns the run's event-stream loop for its whole duration. Durable state lives in
  `scheduled_runs` (claim / complete / next-due) and the session record — not in a lik-ui background task.
  lik-ui gains no long-running background-execution system.
- R10. Every unattended run has a hard maximum runtime. A row left in flight past that bound (e.g., the runner
  died mid-run) is detected on a later scan, force-failed with that outcome recorded, and made eligible to run
  again — never stuck in flight forever.

**Unattended behavior (no human present)**
- R11. Routine expected writes (e.g., registering Catalog rows) are auto-approved by the runner so the run
  proceeds without a human. The runner implements this approval loop; there is no reusable server-side
  auto-approve to inherit today.
- R12. Ambiguous items that would normally ask a human (e.g., a self-disclaiming "DO NOT USE" page) are
  skipped and recorded so the run always completes; they are not auto-approved and do not hold the run open
  waiting.
- R14. An independent backstop bounds what an unattended run may write (e.g., an allowlist of permitted
  tools/actions, or a dry-run / cap), so write safety does not rest solely on the skill's self-classification
  of "routine" — the human allow/deny gate is removed for these runs.
- R15. Auto-approval treats unexpected instruction-like content in source pages as ambiguous (skip-and-record),
  not routine, to limit writes driven by injected content in third-party-editable pages.

**Identity, credentials, and alerting**
- R16. Because a scheduled run uses the owner's own OAuth connections, and those can lapse (e.g., Confluence
  forces periodic re-authentication), the Scheduled runs UI surfaces each schedule's connection health and
  warns the owner when a schedule cannot authenticate.
- R17. When a run fails, or records any skipped item, the owner is actively notified — a push signal, not only
  a row in a list they must remember to open — and the schedule's recorded outcome reflects it. "Visible in
  the session or Settings if opened" does not by itself satisfy this.
- R18. The GitHub Action's credential to reach `scheduled_runs` and start runs is an explicit, controlled
  secret — rotatable, revocable, and distinct from any user's session. It can start runs as any scheduling
  user, so it is a privileged, bounded capability, not an incidental config value.

---

## Acceptance Examples

- AE1. **Covers R1, R2, R8.** Given a user schedules the Catalog Registration Agent daily in Settings, when
  the schedule fires, then a run executes as that user and afterward appears in that user's Sessions page.
- AE2. **Covers R5, R6.** Given two scans overlap (a scheduled fire and a manual dispatch), when both see the
  same due row, then the schedule runs exactly once, not twice.
- AE3. **Covers R10.** Given the runner dies mid-run leaving a row in flight, when a later scan runs, then that
  row is force-failed (outcome recorded) and becomes eligible again — it is not stuck in flight forever.
- AE4. **Covers R11, R12.** Given the crawl encounters normal pages and one "DO NOT USE" page, when the run
  executes, then normal Catalog rows are written without prompting, the "DO NOT USE" page is skipped with a
  recorded note, and the run reaches completion.
- AE5. **Covers R16, R17.** Given the owner's Confluence connection has lapsed, when the schedule fires, then
  the run fails loudly, the owner is notified, and Settings shows that schedule needs re-authentication —
  rather than the run silently doing nothing.
- AE6. **Covers R13.** Given an agent whose skills lack unattended-safe defaults, when a user opens the
  Scheduled runs picker, then that agent is not offered as a schedulable target.

---

## Success Criteria

- Users can set up recurring agent runs themselves, in Settings, without engineering involvement, and each run
  uses that user's own credentials.
- The Catalog stays fresh on a cadence; when a run fails or skips something, the owner is notified and can act
  from the existing UI.
- lik-ui does not acquire a bespoke background-job system — run durability is the `scheduled_runs` table plus
  the disposable CI runner and the session record.
- ce-plan can proceed without inventing the scheduling UI, the state model, the scan/claim rules, or the
  unattended-safety behavior — those are decided here.

---

## Scope Boundaries

- High-frequency / sub-cadence scheduling — out; granularity is bounded by the GitHub Action's own cron.
- Scheduling on another user's behalf, or shared team schedules — out; a schedule runs as its own creator
  only.
- A dedicated service/bot account for runs — out; each run uses its creator's vault.
- Making arbitrary agents unattended-safe — out of this feature; that is per-agent skill authoring, gated by
  R13.
- The TTL column and the routine-vs-full-sweep skill split — out; owned by
  [`2026-07-27-02-catalog-refresh-due-ttl`](2026-07-27-02-catalog-refresh-due-ttl-requirements.md). This
  feature only supplies the cadence/trigger.
- Retiring / aging-out Catalog rows and other Catalog-maintenance TODOs — out.

---

## Key Decisions

- Self-service, table-driven scheduling: users create schedules in a Settings section; a `scheduled_runs`
  cron-like table is the state of record; a GitHub Action scans and runs due rows. Chosen so scheduling is a
  user capability rather than an engineering task, and so the run set is bounded to rows users authored for
  themselves.
- Each run executes as its creator using that user's own vault — no arbitrary-email impersonation and no
  dedicated service account. This is what lets the trigger be safe: the scanner can only run schedules that a
  logged-in user created for themselves.
- The disposable CI runner owns the run's stream loop; durability lives in the table and the session record,
  so lik-ui grows no background-execution system. The ephemeral GitHub runner is well suited to a minutes-long
  crawl that would exceed a synchronous HTTP timeout.
- Ambiguous items are skipped-and-recorded so a run always completes rather than hanging; failures and skips
  are actively pushed to the owner, not left to be discovered by chance.
- The scan/claim/run/register/complete core is a single shared function in the `lik_ui` package, so the
  choice of how CI reaches the data is a transport decision over one implementation — not two parallel
  writers. "Direct DB" = CI imports and calls that core with DB credentials; "via endpoint" = lik-ui exposes
  the same core over HTTP. This keeps the two options equivalent by construction and avoids schema-drift
  between two codebases, and lets a direct-DB start be wrapped in an endpoint later without a rewrite.
- The production DB is already publicly reachable (verified: Lightsail `lik-prod-db`, `publiclyAccessible:
  true`, port 5432 open), so a CI-direct connection adds no new network exposure — an accepted risk. Residual
  concern is least privilege, mitigated by a dedicated DB role scoped to only `scheduled_runs` and `sessions`
  (not the master credential) plus TLS. Neither option requires a new GitHub-stored secret: both pull their
  credential (DB creds, or an app shared secret) from SSM via CI's existing OIDC-assumed role.

---

## Dependencies / Assumptions

- lik-ui lists sessions from its own database, per user, and can open / resume / message / confirm any session
  that has a row owned by the requesting user — so a recorded run is fully reviewable in the existing UI.
  [Verified against lik-ui/src/lik_ui/chat.py and db.py.]
- Vaults are one-per-user, resolvable from the user's identity. [Verified against lik-ui/src/lik_ui/vault.py.]
- Confluence (Atlassian) forces periodic re-authentication requiring interactive consent, which cannot be done
  mid-run — the durability risk behind R16/R17 for recurring runs. [Verified in docs/oauth.md.]
- The runner can start a platform session bound to a user's vault using an API credential, without that user's
  interactive login (sessions are created against vault ids). [Likely — the planner verifies against the
  platform SDK.]
- Adding the `scheduled_runs` table to production is a separate, non-destructive migration step from merging
  the code (`db/init.sql` uses `CREATE TABLE IF NOT EXISTS`, so re-running it will not migrate an existing DB).

---

## Outstanding Questions

### Deferred to Planning

- [Affects R5, R8, R18][Technical] Whether CI reaches `scheduled_runs` directly (DB credentials from SSM) or
  through a lik-ui endpoint wrapping the same shared core (see Key Decisions). The decisive con of direct-DB —
  new network exposure — does not apply, because the prod DB is already public (verified) and that exposure is
  an accepted risk; the remaining tradeoff is least privilege (mitigated by a dedicated table-scoped DB role)
  vs. the simplicity of not adding an endpoint. Leaning direct-DB; the shared-core design keeps the endpoint
  available later without a rewrite.
  - **CLI consideration:** a future CLI trigger favors the endpoint. If the CLI runs only in a trusted
    environment (CI/ops box with SSM), it can import the shared core like the GH Action and direct-DB is
    fine. But a user-facing CLI on developer/user laptops must not receive prod DB credentials or open
    Postgres from arbitrary machines — it needs an authenticated endpoint (called as the user). So: if a
    user-facing CLI is a near-term goal, build the endpoint now; if the CLI is speculative, direct-DB now and
    wrap the same core in an endpoint when the CLI becomes real.
- [Affects R3, R5][Technical] The concrete `scheduled_runs` schema, how a cadence is expressed (fixed interval
  vs. cron expression), and how the next-due time is computed after each run.
- [Affects R6, R10][Technical] The atomic-claim mechanism (row lock / conditional update) and the max-runtime
  value used to reclaim stuck rows.
- [Affects R17][Technical] The notification channel for failures/skips (email, Slack, in-app) and who is
  accountable for acting on it.
- [Affects R14][Technical] The shape of the independent write backstop (tool allowlist / dry-run / cap).
- [Affects R11][Technical] How the runner's auto-approve loop is built, given today's allow/deny logic lives
  in browser JavaScript and there is no reusable server-side approver.
- [Affects catalog sync][Needs research] The Confluence "recently modified" signal, inherited from the
  companion TTL brainstorm.
