"""Analytics domain-logic tests: the pure event tally, and (below) the capture-before-delete
step and read-model helpers. No platform required for the pure pieces."""

from lik_ui.analytics import tally_events


def test_tally_counts_messages_tools_and_errors_with_breakdowns():
    events = [
        {"type": "user", "text": "q1"},
        {"type": "tool_use", "name": "search", "server": "atlassian"},
        {"type": "tool_use", "name": "search", "server": "atlassian"},
        {"type": "tool_use", "name": "read_file", "server": None},  # built-in -> "builtin"
        {"type": "text", "text": "a1"},
        {"type": "error", "error_type": "mcp_connection_failed"},
        {"type": "user", "text": "q2"},
        {"type": "text", "text": "a2"},
        {"type": "usage", "input": 10},        # ignored by the tally
        {"type": "turn_duration", "seconds": 5},  # ignored by the tally
    ]
    t = tally_events(events)
    assert t["user_message_count"] == 2
    assert t["ai_message_count"] == 2
    assert t["tool_use_count"] == 3
    assert t["error_count"] == 1
    assert t["tool_breakdown"] == {
        "tools": {"search": 2, "read_file": 1},
        "servers": {"atlassian": 2, "builtin": 1},
    }
    assert t["error_types"] == {"mcp_connection_failed": 1}


def test_tally_of_empty_stream_is_all_zero():
    t = tally_events([])
    assert t["user_message_count"] == 0 and t["tool_use_count"] == 0 and t["error_count"] == 0
    assert t["tool_breakdown"] == {"tools": {}, "servers": {}}
    assert t["error_types"] == {}
