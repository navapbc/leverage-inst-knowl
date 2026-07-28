"""Run every due, unattended scheduled agent run to completion.

Invoked on a cadence by ``.github/workflows/scheduled-runs.yml`` (and by manual dispatch). It
mirrors ``prune_sessions.py``: build lik-ui's own ``Store`` and platform clients from ``Settings``
(``LIK_UI_*`` env vars, sourced from SSM in CI), scan for due schedules, and drive each to
completion via the shared run-core (``scheduled_runner.run_scheduled``) — the same function a
future HTTP endpoint would call.

Per row, the outcome is persisted on the schedule: a lapsed credential pauses the schedule (only
interactive re-auth fixes it), everything else advances it to the next cadence. A real failure
(``failed`` / ``timed_out`` / ``auth_lapsed`` / ``deny_loop``) makes the process exit non-zero so
the scheduled job surfaces it; skip-and-record on an otherwise-successful run is not a job failure
(it is surfaced to the owner in-app instead).

Usage:
  uv run python scripts/run_scheduled.py     # connects via Settings() (LIK_UI_* env vars)
"""

import sys

from lik_ui.agents import build_agents_client, resolve_agent_options
from lik_ui.chat import build_sessions_client
from lik_ui.db import Database, Store
from lik_ui.scheduled_runner import AUTH_LAPSED, run_scheduled
from lik_ui.settings import Settings
from lik_ui.vault import build_vault_client

# Outcomes that count as a job-level failure (exit non-zero). A SUCCESS run that merely skipped
# ambiguous items is not here — skips are surfaced to the owner via the Settings health badge.
_FAILURE_STATUSES = frozenset({"failed", "timed_out", "auth_lapsed", "deny_loop"})


def _chat_url(base_url: str, session_id: str) -> str:
    """The owner-facing chat page for a session (same path the browser uses). ``base_url`` is
    lik-ui's public base; falls back to the bare session id if it is unset."""
    base = base_url.rstrip("/")
    return f"{base}/chat/{session_id}" if base else session_id


def run_due_schedules(store, sessions_client, vault_client, agents, base_url="") -> tuple[int, int]:
    """Claim and run every due schedule. Returns ``(ran, failed)``. One row's failure never
    aborts the scan — each is isolated and its outcome recorded on its own row. ``base_url`` is
    lik-ui's public base URL, used to log each run's chat page for this otherwise-invisible job."""
    ran = 0
    failed = 0
    for row in store.claim_due_runs():
        run_id = row["id"]
        # Log the session the moment it is created — flushed so a slow or hanging run is still
        # attributable to a session in the job log, instead of only surfacing once the run ends.
        def _log_session(session_id, run_id=run_id, agent=row["agent_name"]):
            print(f"[scheduled] run {run_id} agent={agent!r} started -> {_chat_url(base_url, session_id)}", flush=True)

        try:
            outcome = run_scheduled(store, sessions_client, vault_client, agents, row, on_session_created=_log_session)
        except Exception as exc:  # noqa: BLE001 - run_scheduled shouldn't raise, but never let one row abort the scan
            store.complete_run(run_id, "failed", str(exc), None)
            failed += 1
            print(f"[scheduled] run {run_id} raised, recorded failed: {exc}", file=sys.stderr)
            continue

        if outcome.status == AUTH_LAPSED:
            # Pause instead of advancing — re-running every cadence would just re-fail until the
            # owner re-authenticates interactively. The Settings badge shows "needs re-auth".
            store.pause_and_flag(run_id, "needs_reauth", error=outcome.error)
        else:
            store.complete_run(run_id, outcome.status, outcome.error, outcome.skipped or None)

        ran += 1
        if outcome.status in _FAILURE_STATUSES:
            failed += 1
        note = f" skipped={len(outcome.skipped)}" if outcome.skipped else ""
        where = f" {_chat_url(base_url, outcome.session_id)}" if outcome.session_id else ""
        print(f"[scheduled] run {run_id} agent={row['agent_name']!r} -> {outcome.status}{note}{where}", flush=True)
    return ran, failed


def main() -> int:
    settings = Settings()
    # Fail closed: a scheduled run needs a real platform client. An empty API key in a non-stub
    # environment would build no client and every run would fail resolving a session.
    if not settings.is_stub and not settings.anthropic_api_key:
        print(
            "[scheduled] refusing to run: LIK_UI_ANTHROPIC_API_KEY is empty in a non-stub environment",
            file=sys.stderr,
        )
        return 1
    store = Store(Database(settings.conninfo))
    agents_client = build_agents_client(settings)
    agents = resolve_agent_options(settings, agents_client)
    sessions_client = build_sessions_client(settings)
    vault_client = build_vault_client(settings)
    try:
        ran, failed = run_due_schedules(store, sessions_client, vault_client, agents, settings.app_base_url)
    finally:
        store.db.close()
    print(f"[scheduled] ran={ran} failed={failed}")
    return 1 if failed else 0  # non-zero surfaces a real failure to the scheduled job


if __name__ == "__main__":
    raise SystemExit(main())
