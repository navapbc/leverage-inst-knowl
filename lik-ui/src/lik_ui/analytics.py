"""Session analytics: the capture-before-delete step and the read-model helpers behind the
``/stats`` and ``/all-stats`` pages.

This module holds only pure/domain logic and platform reads through the ``SessionsClient``
seam — it imports NO web/FastAPI/app symbols, so the standalone prune script (which calls
``capture_session_analytics``) never drags in the web stack, and there is no import cycle with
``app.py``. Route handlers live in ``stats.py``.
"""

from collections.abc import Iterable

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
