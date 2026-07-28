"""Drive a single scheduled, unattended agent run to completion.

This is the shared core (see docs/plans/2026-07-28-002-...): the CI scanner
(``scripts/run_scheduled.py``) calls it, and a future HTTP endpoint could call the same
function, so the run logic is one implementation rather than two writers. Given a claimed
``scheduled_runs`` row it resolves the owner and their vault, creates and registers a session,
drives the turn with an **allowlist-gated** auto-approve loop, and returns a :class:`RunOutcome`
the caller persists (``Store.complete_run`` for terminal outcomes, ``Store.pause_and_flag`` for a
lapsed credential).

There is no human present, so the loop:
  * auto-approves a paused tool call only if its ``(server, tool)`` is on the agent's allowlist;
    everything else is denied and recorded as skipped (the write backstop + injected-content
    defense). A tool call the skill retries after a deny is capped by a deny-loop guard.
  * classifies only ``mcp_authentication_failed_error`` as a lapsed credential; other
    ``session.error`` events are often benign (an unconnected MCP server errors, the agent still
    answers) and the stream keeps draining.
  * enforces a hard max-runtime via a watchdog thread, because the SDK stream is a blocking
    iterator and would otherwise sit through the agent's 60–90s silent windows past the budget.
  * deletes the just-created session if the run produced no transcript, so a recurring failure
    (e.g. lapsed auth) doesn't pile up empty sessions in the owner's Sessions list.
"""

import queue
import threading
import time
from dataclasses import dataclass, field

from .vault import ensure_user_vault

# Terminal outcome statuses (also the values written to scheduled_runs.last_status).
SUCCESS = "success"
AUTH_LAPSED = "auth_lapsed"
TIMED_OUT = "timed_out"
DENY_LOOP = "deny_loop"
FAILED = "failed"

# Fail a run if the agent re-requests the same denied tool this many times — a retry-happy agent
# would otherwise loop until max-runtime; this ends it deterministically without a human.
MAX_DENIES_PER_TOOL = 5


@dataclass
class RunOutcome:
    status: str
    error: str | None = None
    skipped: list = field(default_factory=list)  # [{"server", "tool"}, ...] items denied by the allowlist
    session_id: str | None = None
    has_transcript: bool = False  # whether any content streamed (drives empty-session cleanup)


def _pump(iterator, out: "queue.Queue") -> None:
    """Drain a blocking event iterator on a daemon thread, forwarding events to ``out`` and a
    final sentinel — so the consumer can time out a silent stream instead of blocking in next()."""
    try:
        for event in iterator:
            out.put(("event", event))
    except Exception as exc:  # noqa: BLE001 - forward iterator errors to the consumer, don't die silently
        out.put(("error", exc))
    finally:
        out.put(("end", None))


def _events_until_deadline(iterator, deadline: float):
    """Yield an iterator's events, raising ``TimeoutError`` if the wall-clock ``deadline``
    (a ``time.monotonic()`` value) passes first. Returns normally when the iterator is exhausted."""
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_pump, args=(iterator, q), daemon=True).start()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        try:
            kind, payload = q.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError
        if kind == "end":
            return
        if kind == "error":
            raise payload
        yield payload


def _allowed(tool_use: dict, allowlist) -> bool:
    """A paused tool call is auto-approved only when its (server, name) is on the agent's
    allowlist. Server-qualified so a same-named tool on another server is never auto-approved."""
    server = tool_use.get("server") or ""
    name = tool_use.get("name") or ""
    return any(t.server == server and t.tool == name for t in allowlist)


def run_scheduled(store, sessions_client, vault_client, agents, row) -> RunOutcome:
    """Execute one claimed ``scheduled_runs`` row to completion. ``agents`` is the resolved
    roster (list of ``AgentOption``); ``row`` is a claimed schedule. Never raises for expected
    failures — every path returns a :class:`RunOutcome` for the caller to persist."""
    outcome = RunOutcome(status=FAILED)

    # Resolve owner, vault, and the agent's resolved ids + allowlist. Any gap is a recorded
    # failure, not a crash (e.g. the agent was renamed/removed from the roster since scheduling).
    user = store.get_user_by_id(row["user_id"])
    if user is None:
        return RunOutcome(status=FAILED, error=f"no user for id {row['user_id']}")
    option = next((a for a in agents if a.agent_name == row["agent_name"]), None)
    if option is None:
        return RunOutcome(status=FAILED, error=f"agent {row['agent_name']!r} is not in the schedulable roster")
    try:
        vault_id = ensure_user_vault(store, vault_client, user)
    except Exception as exc:  # noqa: BLE001 - vault provisioning failure is a recorded run failure
        return RunOutcome(status=FAILED, error=f"vault resolution failed: {exc}")

    session_id = sessions_client.create_session(
        option.agent_id, option.environment_id, [vault_id], f"Scheduled: {row['agent_name']}"
    )
    outcome.session_id = session_id
    store.create_session(user["id"], option.agent_id, session_id, f"Scheduled: {row['agent_name']}")

    deadline = time.monotonic() + max(1, int(row["max_runtime_s"]))
    answered: set[str] = set()          # tool_use ids already confirmed
    deny_counts: dict[tuple, int] = {}  # (server, name) -> deny count, for the deny-loop guard
    tool_uses: dict[str, dict] = {}     # id -> tool_use event, buffered so a pause can be correlated

    stream = sessions_client.send_and_stream(session_id, row["prompt"])
    try:
        while True:
            pending = None  # (tool_use_id, session_thread_id, allow)
            for event in _events_until_deadline(stream, deadline):
                etype = event.get("type")
                if etype in ("text", "tool_use", "tool_result"):
                    outcome.has_transcript = True
                if etype == "tool_use":
                    tool_uses[event["id"]] = event
                elif etype == "error" and event.get("error_type") == "mcp_authentication_failed_error":
                    outcome.status = AUTH_LAPSED
                    outcome.error = event.get("message") or "MCP authentication failed"
                    return _finalize(outcome, store, sessions_client, user["id"])
                elif etype == "done":
                    outcome.status = SUCCESS
                    return _finalize(outcome, store, sessions_client, user["id"])
                elif etype == "awaiting_confirmation":
                    # Answer one pending "ask" tool call, then re-stream — the SDK re-pauses on any
                    # remaining ones, so a batch is drained across iterations (mirrors the browser's
                    # one-at-a-time /confirm). event_ids signals the pause; the "ask" tool_use carries
                    # the id/server/name/thread we actually need.
                    pend = next(
                        (tu for tid, tu in tool_uses.items()
                         if tu.get("permission") == "ask" and tid not in answered),
                        None,
                    )
                    if pend is None:
                        outcome.status = FAILED
                        outcome.error = "paused with no actionable tool call"
                        return _finalize(outcome, store, sessions_client, user["id"])
                    allow = _allowed(pend, option.auto_approve)
                    if not allow:
                        key = (pend.get("server") or "", pend.get("name") or "")
                        deny_counts[key] = deny_counts.get(key, 0) + 1
                        if deny_counts[key] > MAX_DENIES_PER_TOOL:
                            outcome.status = DENY_LOOP
                            outcome.error = f"denied {key[1]!r} more than {MAX_DENIES_PER_TOOL} times"
                            return _finalize(outcome, store, sessions_client, user["id"])
                        outcome.skipped.append({"server": key[0], "tool": key[1]})
                    answered.add(pend["id"])
                    pending = (pend["id"], pend.get("session_thread_id"), allow)
                    break
            else:
                # Iterator exhausted without an explicit done (shouldn't happen — idle yields done —
                # but guard against a silent end rather than hang or mislabel).
                outcome.status = SUCCESS if outcome.has_transcript else FAILED
                return _finalize(outcome, store, sessions_client, user["id"])

            tool_use_id, thread_id, allow = pending
            stream = sessions_client.confirm_and_stream(
                session_id, tool_use_id, "allow" if allow else "deny", thread_id
            )
    except TimeoutError:
        outcome.status = TIMED_OUT
        outcome.error = f"exceeded max runtime of {row['max_runtime_s']}s"
        return _finalize(outcome, store, sessions_client, user["id"])
    except Exception as exc:  # noqa: BLE001 - any streaming/platform error is a recorded failure
        outcome.status = FAILED
        outcome.error = str(exc)
        return _finalize(outcome, store, sessions_client, user["id"])


def _finalize(outcome: RunOutcome, store, sessions_client, user_id: int) -> RunOutcome:
    """Clean up an empty session on a failed run so recurring failures don't accumulate empty
    sessions in the owner's list. A successful (or skip-and-record) run keeps its transcript."""
    failed = outcome.status in (AUTH_LAPSED, TIMED_OUT, DENY_LOOP, FAILED)
    if failed and not outcome.has_transcript and outcome.session_id:
        store.delete_session(outcome.session_id, user_id)
        try:
            sessions_client.delete_session(outcome.session_id)
        except Exception:  # noqa: BLE001 - best-effort platform cleanup; the row is already gone
            pass
    return outcome
