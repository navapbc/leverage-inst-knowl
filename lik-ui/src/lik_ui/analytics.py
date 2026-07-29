"""Session analytics: the capture-before-delete step and the read-model helpers behind the
``/stats`` and ``/all-stats`` pages.

This module holds only pure/domain logic and platform reads through the ``SessionsClient``
seam — it imports NO web/FastAPI/app symbols, so the standalone prune script (which calls
``capture_session_analytics``) never drags in the web stack, and there is no import cycle with
``app.py``. Route handlers live in ``stats.py``.
"""

import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# The four code paths that physically delete a session; each stamps its label on the record.
DELETION_PATHS = ("manual", "delete_all", "prune", "self_heal")


def tally_events(events: Iterable[dict]) -> dict:
    """Tally the per-event counts for a deleted session's record from its normalized event
    stream (the ``list_events`` vocabulary). Returns message counts, total tool-use count with a
    per-tool and per-MCP-server breakdown, and an error count with per-error-type counts.

    Token usage and timing do NOT come from here — they are read cumulatively from
    ``usage_snapshot`` — so ``usage``/``turn_duration`` events are ignored."""
    user_messages = ai_messages = tool_uses = errors = 0
    tools: dict[str, int] = {}
    servers: dict[str, int] = {}
    error_types: dict[str, int] = {}
    for event in events:
        etype = event.get("type")
        if etype == "user":
            user_messages += 1
        elif etype == "text":
            ai_messages += 1
        elif etype == "tool_use":
            tool_uses += 1
            name = event.get("name") or "unknown"
            tools[name] = tools.get(name, 0) + 1
            # Built-in agent tools have no MCP server; bucket them under "builtin".
            server = event.get("server") or "builtin"
            servers[server] = servers.get(server, 0) + 1
        elif etype == "error":
            errors += 1
            kind = event.get("error_type") or "error"
            error_types[kind] = error_types.get(kind, 0) + 1
    return {
        "user_message_count": user_messages,
        "ai_message_count": ai_messages,
        "tool_use_count": tool_uses,
        "error_count": errors,
        "tool_breakdown": {"tools": tools, "servers": servers},
        "error_types": error_types,
    }


def build_live_section(sessions_client, sessions: list[dict]) -> dict:
    """Assemble the live-sessions section (R10, R11): one lightweight ``usage_snapshot`` per live
    session for its cumulative tokens, timing, and status — never the heavier per-tool/per-message
    tally, which belongs to deleted sessions only.

    Degrades gracefully: a session whose read fails is still listed with ``available=False`` so the
    page never fails on one bad session; when the client is a stub (None) no reads are attempted and
    every session is marked unavailable. Returns ``{"rows": [...], "totals": {...}}``."""
    rows = []
    totals = {"sessions": 0, "total_tokens": 0}
    for s in sessions:
        row = dict(s)
        totals["sessions"] += 1
        if sessions_client is None:
            row["available"] = False
            rows.append(row)
            continue
        try:
            snap = sessions_client.usage_snapshot(s["session_id"])
        except Exception:  # noqa: BLE001 - one unreadable session must not fail the page
            row["available"] = False
            rows.append(row)
            continue
        tokens = sum(
            v or 0 for v in (snap.get("input"), snap.get("output"),
                             snap.get("cache_read"), snap.get("cache_creation"))
        )
        row.update({
            "available": True,
            "input_tokens": snap.get("input"),
            "output_tokens": snap.get("output"),
            "cache_read_tokens": snap.get("cache_read"),
            "cache_creation_tokens": snap.get("cache_creation"),
            "total_tokens": tokens,
            "active_seconds": snap.get("active_seconds"),
            "wall_clock_seconds": snap.get("wall_clock_seconds"),
            "status": snap.get("status"),
        })
        totals["total_tokens"] += tokens
        rows.append(row)
    return {"rows": rows, "totals": totals}


def _base_record(store, session_row: dict, deletion_path: str) -> dict:
    """The record fields knowable from local state alone, used for every record (a full capture
    layers metrics on top). Reads ``session_row`` defensively with ``.get`` so a thin row (the
    prune path selects only session_id/user_id/agent_id/created_at) can never raise here — a
    raise in the fallback would abort the deletion, the opposite of "capture never blocks delete"."""
    user_id = session_row.get("user_id")
    record = {
        "session_id": session_row.get("session_id"),
        "user_id": user_id,
        "user_email": _lookup_email(store, user_id),
        "agent_id": session_row.get("agent_id"),
        "created_at": session_row.get("created_at"),
        "deletion_path": deletion_path,
    }
    return record


def _lookup_email(store, user_id) -> str | None:
    """Denormalize the owner's email onto the record so /all-stats can attribute usage by whom
    even after the user row is gone. Best-effort — never let a lookup failure block capture."""
    if user_id is None:
        return None
    try:
        user = store.get_user_by_id(user_id)
    except Exception:  # noqa: BLE001 - a lookup failure must not block capture
        return None
    return user["email"] if user else None


def capture_session_analytics(
    store,
    sessions_client,
    session_row: dict,
    deletion_path: str,
    *,
    platform_lost: bool = False,
) -> None:
    """Write exactly one durable analytics record for ``session_row`` just before it is physically
    deleted — the single shared step all four deletion paths route through (R5, R6).

    - When the platform is readable, the record carries full usage: cumulative tokens (with the
      cache-read / cache-creation split), active + wall-clock timing, message counts, the per-tool
      and per-MCP-server tool-use breakdown, error counts with types, agent, lifespan, and path (R7).
    - When ``platform_lost`` is set (self-heal — the platform session is already gone) or the
      client is a stub (None), or the pre-delete read fails for any reason, the record is still
      written from local fields and flagged ``capture_incomplete`` with a reason (R8, R9).

    Never raises: capture must not block deletion. A write failure is logged, not propagated."""
    record = _base_record(store, session_row, deletion_path)
    session_id = record["session_id"]

    if platform_lost:
        record["capture_incomplete"] = True
        record["capture_reason"] = "lost before capture (platform session already gone)"
    elif sessions_client is None:
        record["capture_incomplete"] = True
        record["capture_reason"] = "platform client unavailable"
    else:
        try:
            # All-or-nothing read: any failure flags the whole record rather than storing a
            # partial mix of read and missing metrics.
            snap = sessions_client.usage_snapshot(session_id)
            tally = tally_events(sessions_client.list_events(session_id))
            record.update(
                {
                    "capture_incomplete": False,
                    "input_tokens": snap.get("input"),
                    "output_tokens": snap.get("output"),
                    "cache_read_tokens": snap.get("cache_read"),
                    "cache_creation_tokens": snap.get("cache_creation"),
                    "active_seconds": snap.get("active_seconds"),
                    "wall_clock_seconds": snap.get("wall_clock_seconds"),
                    **tally,
                }
            )
        except Exception as exc:  # noqa: BLE001 - degrade to a flagged local-only record
            record["capture_incomplete"] = True
            record["capture_reason"] = f"usage read failed: {exc}"

    try:
        store.write_session_analytics(record)
    except Exception:  # noqa: BLE001 - never block deletion on an analytics write failure
        logger.exception("failed to write session_analytics for %s", session_id)
