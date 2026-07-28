"""Delete sessions whose ``auto_delete_at`` has passed — the platform transcript first,
then the local DB row — continuing past individual failures.

Run daily by ``.github/workflows/prune-sessions.yml``. It reuses lik-ui's own ``Store`` and
``AnthropicSessionsClient`` so the platform-first-then-row ordering matches the interactive
delete path (``chat.py`` ``/sessions/delete``). Unlike the interactive delete-all, a single
session's failure does not abort the run: its row is left intact (never orphaning a
transcript) and retried on the next run, and the process exits non-zero so the scheduled job
surfaces the failure.

Usage:
  uv run python scripts/prune_sessions.py     # connects via Settings() (LIK_UI_* env vars)
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from lik_ui.chat import AnthropicSessionsClient, SessionsClient
from lik_ui.db import Database, Store
from lik_ui.settings import Settings


@dataclass
class PruneResult:
    deleted: int
    failed: int


def prune_due_sessions(
    store: Store, sessions_client: SessionsClient | None, *, now: datetime | None = None
) -> PruneResult:
    """Delete every session due at ``now`` (defaults to the current instant). For each: delete
    the platform session first (idempotent — a session already gone on the platform is treated
    as success by the client), then the owner-scoped DB row. A failure on one session is
    isolated so the rest still run; the failed session's row is left for the next run."""
    now = now or datetime.now(timezone.utc)
    deleted = 0
    failed = 0
    for s in store.list_sessions_due(now):
        session_id = s["session_id"]
        try:
            if sessions_client is not None:
                sessions_client.delete_session(session_id)  # platform first
            store.delete_session(session_id, s["user_id"])  # then the row
            deleted += 1
        except Exception as exc:  # noqa: BLE001 - isolate one session's failure; keep going
            failed += 1
            print(f"[prune] FAILED {session_id}: {exc}", file=sys.stderr)
    return PruneResult(deleted=deleted, failed=failed)


def _build_sessions_client(settings: Settings) -> SessionsClient | None:
    """The platform client, or None in local/test (stub) mode where there is no platform side."""
    if settings.is_stub or not settings.anthropic_api_key:
        return None
    return AnthropicSessionsClient(settings.anthropic_api_key)


def main() -> int:
    settings = Settings()
    store = Store(Database(settings.conninfo))
    try:
        result = prune_due_sessions(store, _build_sessions_client(settings))
    finally:
        store.db.close()
    print(f"[prune] deleted={result.deleted} failed={result.failed}")
    return 1 if result.failed else 0  # non-zero surfaces a partial failure to the scheduled job


if __name__ == "__main__":
    raise SystemExit(main())
