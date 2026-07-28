"""Delete sessions whose ``auto_delete_at`` has passed — the platform transcript first,
then the local DB row.

Run daily by ``.github/workflows/prune-sessions.yml``. It reuses lik-ui's own ``Store`` and
sessions client so the platform-first-then-row ordering matches the interactive delete path
(``chat.py`` ``/sessions/delete``).

Failure handling distinguishes the two legs:
- A **platform** delete failure isolates that session (its row is left for the next run,
  never orphaning a transcript) and the run continues.
- A **DB row** delete failure *after* a successful platform delete aborts the run: the
  transcript is already gone, and continuing against what is likely a dead DB would orphan
  more transcripts. Better to stop and retry next run.

Either kind of failure makes the process exit non-zero so the scheduled job surfaces it.

Usage:
  uv run python scripts/prune_sessions.py     # connects via Settings() (LIK_UI_* env vars)
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from lik_ui.chat import SessionsClient, build_sessions_client
from lik_ui.db import Database, Store
from lik_ui.settings import Settings


@dataclass
class PruneResult:
    deleted: int
    failed: int


def prune_due_sessions(
    store: Store, sessions_client: SessionsClient | None, *, now: datetime | None = None
) -> PruneResult:
    """Delete every session due at ``now`` (defaults to the current instant), platform-first.
    See the module docstring for the two-leg failure policy."""
    now = now or datetime.now(timezone.utc)
    deleted = 0
    failed = 0
    for s in store.list_sessions_due(now):
        session_id = s["session_id"]
        # Platform first (idempotent — a session already gone on the platform is a success).
        # A failure here is isolated: skip the row so it retries next run, and keep going.
        if sessions_client is not None:
            try:
                sessions_client.delete_session(session_id)
            except Exception as exc:  # noqa: BLE001 - isolate one session's platform failure
                failed += 1
                print(f"[prune] platform delete FAILED {session_id}: {exc}", file=sys.stderr)
                continue
        # Row second. If this fails, the transcript is already gone; deleting more platform
        # transcripts against a failing DB would orphan them, so abort the run.
        try:
            store.delete_session(session_id, s["user_id"])
        except Exception as exc:  # noqa: BLE001 - a DB-side failure aborts to avoid mass orphaning
            failed += 1
            print(f"[prune] DB row delete FAILED {session_id} after platform delete; aborting run: {exc}", file=sys.stderr)
            break
        deleted += 1
    return PruneResult(deleted=deleted, failed=failed)


def main() -> int:
    settings = Settings()
    # Fail closed: in a non-stub (prod) environment an empty API key would build no platform
    # client, silently deleting DB rows while orphaning transcripts and reporting success.
    if not settings.is_stub and not settings.anthropic_api_key:
        print(
            "[prune] refusing to run: LIK_UI_ANTHROPIC_API_KEY is empty in a non-stub environment "
            "(would delete DB rows while orphaning platform transcripts)",
            file=sys.stderr,
        )
        return 1
    store = Store(Database(settings.conninfo))
    try:
        result = prune_due_sessions(store, build_sessions_client(settings))
    finally:
        store.db.close()
    print(f"[prune] deleted={result.deleted} failed={result.failed}")
    return 1 if result.failed else 0  # non-zero surfaces a partial failure to the scheduled job


if __name__ == "__main__":
    raise SystemExit(main())
