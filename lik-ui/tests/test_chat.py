"""Chat: session create/resume and SSE streaming. The Managed Agents session is faked."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.chat import AnthropicSessionsClient, SessionNotFound
from lik_ui.db import Store
from lik_ui.settings import Settings
from tests.test_app_auth import FakeOidc, _start_login_and_get_state
from tests.test_oauth_connector import RecordingVaultClient


class FakeSessionsClient:
    def __init__(self, events=None, raises=False, history=None, session_status="idle", resume=None,
                 not_found=False):
        self.created = []
        self.events = events if events is not None else [{"type": "text", "text": "Hello"}, {"type": "done"}]
        self.raises = raises
        self.history = history or []
        self.session_status = session_status
        self.resume = resume if resume is not None else [{"type": "text", "text": "resumed"}, {"type": "done"}]
        self.not_found = not_found  # simulate a platform session gone from the current workspace

    def status(self, session_id):
        if self.not_found:
            raise SessionNotFound(session_id)
        return self.session_status

    def resume_stream(self, session_id):
        yield from self.resume

    def create_session(self, agent_id, environment_id, vault_ids, title):
        self.created.append((agent_id, environment_id, tuple(vault_ids), title))
        return f"sess_{len(self.created)}"

    def delete_session(self, session_id):
        if self.raises:
            raise RuntimeError("delete boom")
        self.deleted = getattr(self, "deleted", [])
        self.deleted.append(session_id)

    def send_and_stream(self, session_id, message):
        if self.raises:
            raise RuntimeError("stream boom")
        yield from self.events

    def confirm_and_stream(self, session_id, tool_use_id, result,
                           session_thread_id=None, deny_message=None):
        self.confirmed = (session_id, tool_use_id, result, session_thread_id, deny_message)
        yield from self.events

    def list_events(self, session_id):
        if self.not_found:
            raise SessionNotFound(session_id)
        yield from self.history


class FakeAgentsClient:
    """Minimal agents client so the untitled-chat default can read the agent's label and the
    chat page can list the agent's declared servers for the auto-approve checklist."""

    def resolve_agent_id(self, name):
        return "agent_1"

    def resolve_environment_id(self, name):
        return "env_1"

    def describe(self, agent_id):
        return {
            "name": "Discovery Layer Agent",
            "servers": [
                {"name": "atlassian", "url": "https://a/", "permission_policy": "ask"},
                {"name": "github", "url": "https://g/", "permission_policy": "always_allow"},
            ],
            "system": None,
            "model": None,
        }


def _app(db, sessions_client, vc=None, email="alice@navapbc.com", roster="agents.toml"):
    vc = vc or RecordingVaultClient()
    oidc = FakeOidc({"email": email, "email_verified": True})
    settings = Settings(env="test", agents_config_path=Path(__file__).parent / "fixtures" / roster)
    return build_app(settings, store=Store(db), app_oidc=oidc, vault_client=vc,
                     agents_client=FakeAgentsClient(), sessions_client=sessions_client)


def _login(client):
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=x&state={state}")


def test_normalize_mcp_tool_use_carries_id_and_input():
    ev = SimpleNamespace(type="agent.mcp_tool_use", id="tu_1", name="search",
                         mcp_server_name="atlassian", input={"q": "hi"},
                         evaluated_permission="allow", session_thread_id=None)
    assert AnthropicSessionsClient._normalize(ev) == {
        "type": "tool_use", "id": "tu_1", "name": "search",
        "server": "atlassian", "input": {"q": "hi"},
        "permission": "allow", "session_thread_id": None,
    }


def test_normalize_mcp_tool_use_carries_ask_permission():
    # A permission-gated call: the "ask" gate is what the UI keys off to prompt for approval.
    ev = SimpleNamespace(type="agent.mcp_tool_use", id="tu_9", name="get_me",
                         mcp_server_name="github", input={},
                         evaluated_permission="ask", session_thread_id="th_1")
    assert AnthropicSessionsClient._normalize(ev) == {
        "type": "tool_use", "id": "tu_9", "name": "get_me",
        "server": "github", "input": {},
        "permission": "ask", "session_thread_id": "th_1",
    }


def test_normalize_builtin_tool_use_has_no_server():
    ev = SimpleNamespace(type="agent.tool_use", id="tu_2", name="think", input={"note": "hm"})
    assert AnthropicSessionsClient._normalize(ev) == {
        "type": "tool_use", "id": "tu_2", "name": "think",
        "server": None, "input": {"note": "hm"},
        "permission": None, "session_thread_id": None,
    }


def test_normalize_builtin_tool_result_pairs_tool_use_id():
    ev = SimpleNamespace(
        type="agent.tool_result", tool_use_id="tu_2", is_error=False,
        content=[SimpleNamespace(type="text", text="done")],
    )
    assert AnthropicSessionsClient._normalize(ev) == {
        "type": "tool_result", "tool_use_id": "tu_2", "is_error": False, "content": "done",
    }


def test_normalize_mcp_tool_result_flattens_content_and_pairs_id():
    ev = SimpleNamespace(
        type="agent.mcp_tool_result", mcp_tool_use_id="tu_1", is_error=False,
        content=[SimpleNamespace(type="text", text="line one"),
                 SimpleNamespace(type="image")],
    )
    assert AnthropicSessionsClient._normalize(ev) == {
        "type": "tool_result", "tool_use_id": "tu_1", "is_error": False,
        "content": "line one\n[image]",
    }


def test_normalize_status_running():
    ev = SimpleNamespace(type="session.status_running", id="s_1")
    assert AnthropicSessionsClient._normalize(ev) == {"type": "status", "state": "running"}


def test_normalize_context_compacted():
    ev = SimpleNamespace(type="agent.thread_context_compacted", id="c_1")
    assert AnthropicSessionsClient._normalize(ev) == {"type": "compacted"}


def test_normalize_model_request_end_carries_token_usage():
    ev = SimpleNamespace(
        type="span.model_request_end",
        model_usage=SimpleNamespace(
            input_tokens=100, output_tokens=20,
            cache_read_input_tokens=5, cache_creation_input_tokens=3,
        ),
    )
    assert AnthropicSessionsClient._normalize(ev) == {
        "type": "usage", "input": 100, "output": 20, "cache_read": 5, "cache_creation": 3,
    }


def test_normalize_session_error_carries_message_and_retry_status():
    # A non-MCP error (e.g. an overloaded model) has no mcp_server_name; the message and
    # retry status must survive so the UI can report it accurately instead of a generic
    # "reconnect your source" nudge.
    ev = SimpleNamespace(
        type="session.error",
        error=SimpleNamespace(
            type="model_overloaded_error",
            message="The API is temporarily overloaded.",
            mcp_server_name=None,
            retry_status=SimpleNamespace(type="exhausted"),
        ),
    )
    assert AnthropicSessionsClient._normalize(ev) == {
        "type": "error",
        "error_type": "model_overloaded_error",
        "mcp_server_name": None,
        "message": "The API is temporarily overloaded.",
        "retry_status": "exhausted",
    }


def _client_with_status(status, events=()):
    client = AnthropicSessionsClient.__new__(AnthropicSessionsClient)
    client._client = SimpleNamespace(
        beta=SimpleNamespace(sessions=SimpleNamespace(
            retrieve=lambda session_id: SimpleNamespace(status=status),
            events=SimpleNamespace(list=lambda session_id, order: iter(events))))
    )
    return client


def test_status_reports_running_session():
    assert _client_with_status("running").status("s") == "running"


def test_status_reports_queued_for_unprocessed_trailing_user_message():
    # The session status reads "idle" while a just-submitted turn waits unprocessed; the
    # trailing user message with a null processed_at is what marks it queued.
    events = [
        SimpleNamespace(type="agent.message", processed_at="t0"),
        SimpleNamespace(type="user.message", processed_at=None),
    ]
    assert _client_with_status("idle", events).status("s") == "queued"


def test_status_stays_idle_when_last_user_message_is_processed():
    events = [SimpleNamespace(type="user.message", processed_at="t0"),
              SimpleNamespace(type="agent.message", processed_at="t1")]
    assert _client_with_status("idle", events).status("s") == "idle"


def test_resume_stream_returns_done_without_attaching_when_idle():
    # Subscribing to an idle session would block forever, so resume short-circuits.
    assert list(_client_with_status("idle").resume_stream("s")) == [{"type": "done"}]


def test_new_chat_creates_session_with_vault_and_redirects(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)

    r = client.get("/chat?agent_id=agent_1")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/chat/")
    assert len(sc.created) == 1
    agent_id, environment_id, vaults, title = sc.created[0]
    assert (agent_id, environment_id, vaults) == ("agent_1", "env_1", ("vlt_1",))  # bound to the user's vault
    assert title  # every session is created with a non-empty title


def test_new_chat_uses_provided_title(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1&title=My+research")
    # The title the user typed is what the sessions list shows.
    assert "My research" in client.get("/sessions").text
    assert sc.created[0][3] == "My research"  # and it's passed to the SDK so the server copy matches


def test_new_chat_defaults_title_when_blank(db):
    # The fixture agent declares no session_title_prefix, so the blank-title default falls back to
    # the agent's full name from describe() (pre-prefix behavior).
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1")  # no title -> agent name + timestamp default
    assert "Discovery Layer Agent" in client.get("/sessions").text


def test_new_chat_uses_session_title_prefix_when_present(db):
    # When the roster gives the agent a short prefix, the blank-title default leads with it instead
    # of the long agent name.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc, roster="agents_prefixed.toml"), follow_redirects=False)
    _login(client)
    client.get("/chat?agent_id=agent_1")  # no title -> prefix + timestamp default
    sessions = client.get("/sessions").text
    assert "TP · " in sessions
    assert "Discovery Layer Agent" not in sessions


def test_connections_page_prefills_title_with_prefix(db):
    # The connections page seeds the title input (placeholder + JS prefill) from the prefix, not the
    # long agent name; the page heading still shows the full name.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc, roster="agents_prefixed.toml"), follow_redirects=False)
    _login(client)
    page = client.get("/connections?agent_id=agent_1").text
    assert 'placeholder="TP"' in page  # input placeholder uses the prefix
    assert '"TP" + " · " + new Date().toLocaleString()' in page  # JS prefill uses the prefix
    assert "Discovery Layer Agent" in page  # heading keeps the full agent label


def _start_session(db, sc, title="agent_1"):
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]
    return client, session_id


def test_sessions_list_flags_session_near_deletion(db):
    from datetime import datetime, timedelta, timezone

    client, session_id = _start_session(db, FakeSessionsClient())
    soon = datetime.now(timezone.utc) + timedelta(days=1, hours=1)  # inside the 3-day window
    Store(db).set_session_auto_delete_at(session_id, _owner_id(db), soon)
    text = client.get("/sessions").text
    assert "delete-warning" in text
    assert "Deletes in 1 day" in text


def test_sessions_list_flags_same_day_deletion_as_today(db):
    from datetime import datetime, timedelta, timezone

    client, session_id = _start_session(db, FakeSessionsClient())
    Store(db).set_session_auto_delete_at(session_id, _owner_id(db), datetime.now(timezone.utc) + timedelta(hours=2))
    text = client.get("/sessions").text
    assert "delete-warning" in text
    assert "Deletes today" in text


def test_sessions_list_flags_session_at_window_boundary(db):
    from datetime import datetime, timedelta, timezone

    client, session_id = _start_session(db, FakeSessionsClient())
    # ~3 days out — the inclusive edge of the 3-day warning window. (A `<` off-by-one that
    # excluded the boundary would drop the flag here.)
    Store(db).set_session_auto_delete_at(session_id, _owner_id(db), datetime.now(timezone.utc) + timedelta(days=3))
    assert "delete-warning" in client.get("/sessions").text


def test_sessions_list_shows_local_date_element_when_not_near(db):
    from datetime import timezone

    client, session_id = _start_session(db, FakeSessionsClient())
    # Default is +7 days, well outside the 3-day window; the list emits the delete instant as a
    # UTC `data-utc` date element (tz.js renders it in the viewer's zone), with no hardcoded ET.
    stored = Store(db).get_session(session_id, _owner_id(db))["auto_delete_at"]
    text = client.get("/sessions").text
    assert "delete-warning" not in text
    assert "Deletes in" not in text
    assert 'data-format="date"' in text
    assert f'data-utc="{stored.astimezone(timezone.utc).isoformat()}"' in text
    assert " ET" not in text  # the hardcoded zone label is gone


def test_chat_page_lists_declared_servers_for_auto_approve(db):
    # The chat page renders a per-server auto-approve checkbox for each MCP server the agent
    # declares, so the user can trust specific sources for the session.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    loc = client.get("/chat?agent_id=agent_1").headers["location"]

    page = client.get(loc).text
    # Checked by default: every declared server is trusted until the user unticks one. An
    # "ask" server stays toggleable; an "always_allow" server is locked (checked + disabled)
    # since its calls never pause for approval.
    assert 'class="auto-server" value="atlassian" checked' in page
    assert 'value="atlassian" checked disabled' not in page
    assert 'class="auto-server" value="github" checked disabled' in page


def test_chat_page_has_activity_indicator_outside_transcript(db):
    # A dedicated, initially-hidden status element must be present (and outside #transcript so a
    # history reload can't remove it) so chat.js can always show when the agent is not idle.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    loc = client.get("/chat?agent_id=agent_1").headers["location"]
    page = client.get(loc).text
    assert 'id="agent-status"' in page
    assert "hidden" in page[page.index('id="agent-status"'):page.index('id="agent-status"') + 120]
    # It sits after the transcript container, not nested inside it.
    assert page.index('id="transcript"') < page.index('id="agent-status"')


def test_chat_page_shows_activity_indicator_to_read_only_viewer(db):
    # A shared-session viewer watches in-flight turns via resume, so they need the indicator too.
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    assert 'id="agent-status"' in viewer.get(f"/chat/{session_id}").text


def test_chat_page_shows_user_prompt_before_transcript(db):
    # The agent's authored user_prompt renders as a block immediately before the transcript.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    loc = client.get("/chat?agent_id=agent_1").headers["location"]
    page = client.get(loc).text
    assert "Ask the Test Agent about test things." in page
    assert 'class="user-prompt"' in page
    # It sits above the transcript, not inside or after it.
    assert page.index('class="user-prompt"') < page.index('id="transcript"')


def test_chat_page_omits_user_prompt_block_when_agent_has_none(db):
    # A session whose agent isn't in the resolved roster (no user_prompt) renders no block, no error.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = "sess-ghost"
    Store(db).create_session(_owner_id(db), "ghost-agent", session_id, "Ghost")
    page = client.get(f"/chat/{session_id}")
    assert page.status_code == 200
    assert 'class="user-prompt"' not in page.text


def test_chat_page_shows_user_prompt_to_read_only_viewer(db):
    # The invitation describes the agent, so a shared-session viewer sees it too (not owner-gated).
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    assert "Ask the Test Agent about test things." in viewer.get(f"/chat/{session_id}").text


def test_delete_session_removes_row_and_deletes_platform_session(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]
    assert session_id in client.get("/sessions").text

    r = client.post("/sessions/delete", data={"session_id": session_id})
    assert r.status_code == 303 and r.headers["location"] == "/sessions"
    assert sc.deleted == [session_id]  # platform data removed, honoring the delete promise
    assert session_id not in client.get("/sessions").text  # and it's gone from the list


def test_delete_session_surfaces_platform_error_and_keeps_row(db):
    # A failed platform delete must not silently drop the local row: a listed session should
    # never outlive its platform data, so we keep it and surface the error.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    sc.raises = True
    r = client.post("/sessions/delete", data={"session_id": session_id})
    assert r.status_code == 502
    assert session_id in client.get("/sessions").text  # row survives the failed delete


def test_delete_session_ignores_a_session_the_user_does_not_own(db):
    # No platform call for a row the user doesn't own (or that doesn't exist); just redirect.
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    r = client.post("/sessions/delete", data={"session_id": "sess_not_mine"})
    assert r.status_code == 303 and r.headers["location"] == "/sessions"
    assert getattr(sc, "deleted", []) == []


def test_resume_does_not_create_a_new_session(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    loc = client.get("/chat?agent_id=agent_1").headers["location"]
    assert len(sc.created) == 1

    page = client.get(loc)  # reopen the session
    assert page.status_code == 200
    assert len(sc.created) == 1  # reused, no new session


def test_stream_renders_text_then_done(db):
    sc = FakeSessionsClient(events=[{"type": "text", "text": "Hi there"}, {"type": "done"}])
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/stream?message=hello")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert '"type": "text"' in r.text
    assert "Hi there" in r.text
    assert '"type": "done"' in r.text


def test_stream_surfaces_running_status(db):
    sc = FakeSessionsClient(events=[{"type": "status", "state": "running"},
                                    {"type": "text", "text": "Hi"}, {"type": "done"}])
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/stream?message=hello")
    assert '"type": "status"' in r.text
    assert '"state": "running"' in r.text


def test_send_and_stream_subscribes_before_sending():
    # Regression: the stream must be opened before the message is dispatched. Sending first
    # left a gap where a fast turn could finish before we subscribed, so its reply never
    # streamed and only showed up on a page refresh.
    calls = []
    stream_events = [
        SimpleNamespace(type="agent.message", content=[SimpleNamespace(text="Hi")]),
        SimpleNamespace(type="session.status_idle"),  # terminates the turn
    ]

    class FakeStream:
        def __enter__(self):
            return iter(stream_events)

        def __exit__(self, *exc):
            calls.append("close")
            return False

    client = AnthropicSessionsClient.__new__(AnthropicSessionsClient)
    client._client = SimpleNamespace(beta=SimpleNamespace(sessions=SimpleNamespace(
        events=SimpleNamespace(
            stream=lambda session_id: (calls.append("stream"), FakeStream())[1],
            send=lambda session_id, events: calls.append("send"),
        ))))

    out = list(client.send_and_stream("sess_1", "hello"))
    assert calls[:2] == ["stream", "send"]  # subscribed before dispatching the turn
    assert "close" in calls  # stream context is closed
    assert out == [{"type": "text", "text": "Hi"}, {"type": "done"}]


def _fake_streaming_client(stream_events):
    """An AnthropicSessionsClient whose stream yields ``stream_events`` and whose send()
    records the dispatched events into the returned ``sent`` list."""
    sent = []

    class FakeStream:
        def __enter__(self):
            return iter(stream_events)

        def __exit__(self, *exc):
            return False

    client = AnthropicSessionsClient.__new__(AnthropicSessionsClient)
    client._client = SimpleNamespace(beta=SimpleNamespace(sessions=SimpleNamespace(
        events=SimpleNamespace(
            stream=lambda session_id: FakeStream(),
            send=lambda session_id, events: sent.append((session_id, events)),
        ))))
    return client, sent


def test_stream_pauses_on_requires_action_instead_of_done():
    # A permission-gated tool call surfaces its "ask" event, then the turn goes idle with a
    # requires_action stop_reason. That's a pause, not completion: emit awaiting_confirmation
    # (carrying the blocked ids) and no "done".
    stream_events = [
        SimpleNamespace(type="agent.mcp_tool_use", id="tu_9", name="get_me",
                        mcp_server_name="github", input={},
                        evaluated_permission="ask", session_thread_id=None),
        SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(
            type="requires_action", event_ids=["tu_9"])),
    ]
    client, _ = _fake_streaming_client(stream_events)
    out = list(client.send_and_stream("sess_1", "hi"))
    assert out == [
        {"type": "tool_use", "id": "tu_9", "name": "get_me", "server": "github",
         "input": {}, "permission": "ask", "session_thread_id": None},
        {"type": "awaiting_confirmation", "event_ids": ["tu_9"]},
    ]


def test_stream_ends_on_plain_idle():
    # An end-of-turn idle (no requires_action) completes the turn with "done".
    stream_events = [
        SimpleNamespace(type="agent.message", content=[SimpleNamespace(text="Hi")]),
        SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(type="end_turn")),
    ]
    client, _ = _fake_streaming_client(stream_events)
    out = list(client.send_and_stream("sess_1", "hi"))
    assert out == [{"type": "text", "text": "Hi"}, {"type": "done"}]


def test_confirm_and_stream_sends_confirmation_event():
    client, sent = _fake_streaming_client([
        SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(type="end_turn")),
    ])
    out = list(client.confirm_and_stream("sess_1", "tu_9", "allow"))
    assert out == [{"type": "done"}]
    assert sent == [("sess_1", [{"type": "user.tool_confirmation",
                                 "result": "allow", "tool_use_id": "tu_9"}])]


def test_confirm_and_stream_deny_carries_message_and_thread():
    client, sent = _fake_streaming_client([
        SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(type="end_turn")),
    ])
    list(client.confirm_and_stream("sess_1", "tu_9", "deny",
                                   session_thread_id="th_1", deny_message="nope"))
    assert sent[0][1] == [{
        "type": "user.tool_confirmation", "result": "deny", "tool_use_id": "tu_9",
        "session_thread_id": "th_1", "deny_message": "nope",
    }]


def test_confirm_route_streams_resumed_turn(db):
    sc = FakeSessionsClient(events=[{"type": "text", "text": "resumed"}, {"type": "done"}])
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/confirm?tool_use_id=tu_9&result=allow")
    assert r.status_code == 200
    assert "resumed" in r.text
    assert sc.confirmed[1:3] == ("tu_9", "allow")


def test_confirm_route_rejects_bad_result(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/confirm?tool_use_id=tu_9&result=maybe")
    assert r.status_code == 400


def _list_events_client(raw):
    client = AnthropicSessionsClient.__new__(AnthropicSessionsClient)
    client._client = SimpleNamespace(
        beta=SimpleNamespace(sessions=SimpleNamespace(events=SimpleNamespace(
            list=lambda session_id, order: iter(raw))))
    )
    return client


def test_list_events_emits_turn_duration_from_processed_at():
    from datetime import datetime, timezone

    def at(sec):
        return datetime(2026, 7, 27, 14, 40, sec, tzinfo=timezone.utc)

    raw = [
        SimpleNamespace(type="user.message", processed_at=at(0), content=[SimpleNamespace(text="hi")]),
        SimpleNamespace(type="agent.mcp_tool_use", processed_at=at(2), id="t1", name="search",
                        mcp_server_name="atlassian", input={}, evaluated_permission="allow",
                        session_thread_id=None),
        SimpleNamespace(type="agent.message", processed_at=at(5), content=[SimpleNamespace(text="reply")]),
    ]
    out = list(_list_events_client(raw).list_events("s"))
    # The duration is the last agent event minus the user message, emitted after the turn's events.
    assert [e["type"] for e in out] == ["user", "tool_use", "text", "turn_duration"]
    assert out[-1] == {"type": "turn_duration", "seconds": 5.0}


def test_list_events_emits_a_duration_per_turn_and_skips_an_unfinished_one():
    from datetime import datetime, timezone

    def at(minute, sec):
        return datetime(2026, 7, 27, 14, minute, sec, tzinfo=timezone.utc)

    raw = [
        SimpleNamespace(type="user.message", processed_at=at(40, 0), content=[SimpleNamespace(text="q1")]),
        SimpleNamespace(type="agent.message", processed_at=at(40, 4), content=[SimpleNamespace(text="a1")]),
        SimpleNamespace(type="user.message", processed_at=at(41, 0), content=[SimpleNamespace(text="q2")]),
        SimpleNamespace(type="agent.message", processed_at=at(41, 30), content=[SimpleNamespace(text="a2")]),
        # A trailing user turn still in flight (no agent event yet) yields no duration.
        SimpleNamespace(type="user.message", processed_at=at(42, 0), content=[SimpleNamespace(text="q3")]),
    ]
    out = list(_list_events_client(raw).list_events("s"))
    durations = [e["seconds"] for e in out if e["type"] == "turn_duration"]
    assert durations == [4.0, 30.0]
    # The first turn's duration lands between its reply and the second user bubble.
    types = [e["type"] for e in out]
    assert types == ["user", "text", "turn_duration", "user", "text", "turn_duration", "user"]


def test_history_drops_transient_status_events():
    # A past turn's "running" is meaningless on replay, so list_events filters it out.
    raw = [SimpleNamespace(type="session.status_running", id="s_1"),
           SimpleNamespace(type="agent.message", content=[SimpleNamespace(text="Hi there")])]
    client = AnthropicSessionsClient.__new__(AnthropicSessionsClient)
    client._client = SimpleNamespace(
        beta=SimpleNamespace(sessions=SimpleNamespace(events=SimpleNamespace(
            list=lambda session_id, order: iter(raw))))
    )
    assert [e["type"] for e in client.list_events("sess_1")] == ["text"]


def test_stream_surfaces_mcp_auth_error(db):
    sc = FakeSessionsClient(
        events=[{"type": "error", "error_type": "mcp_authentication_failed_error", "mcp_server_name": "atlassian"}, {"type": "done"}]
    )
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/stream?message=go")
    assert "mcp_authentication_failed_error" in r.text
    assert "atlassian" in r.text


def test_stream_emits_terminal_error_when_client_raises(db):
    sc = FakeSessionsClient(raises=True)
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/stream?message=go")
    assert r.status_code == 200
    assert "stream_failed" in r.text
    assert '"type": "done"' in r.text


def test_sse_emits_heartbeat_while_the_stream_stalls(db, monkeypatch):
    # A turn that goes silent longer than the heartbeat interval must keep the connection
    # non-idle with SSE comments, so a load balancer doesn't cull it mid-turn and strand the
    # reply. Drive a stall with a generator that blocks between events, and shrink the interval
    # so the test doesn't wait on real seconds.
    import threading

    import lik_ui.chat as chat_mod

    monkeypatch.setattr(chat_mod, "_SSE_HEARTBEAT_SECONDS", 0.05)
    release = threading.Event()

    def stalling_events(session_id, message):
        yield {"type": "text", "text": "first"}
        release.wait(2.0)  # simulate the agent thinking/working with nothing to emit
        yield {"type": "text", "text": "second"}
        yield {"type": "done"}

    sc = FakeSessionsClient()
    sc.send_and_stream = stalling_events
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    chunks = []
    with client.stream("GET", f"/chat/{session_id}/stream?message=go") as r:
        for line in r.iter_lines():
            chunks.append(line)
            if line.startswith(": keepalive"):
                release.set()  # a heartbeat arrived during the stall — let the turn finish
            if '"type": "done"' in line:
                break

    body = "\n".join(chunks)
    assert ": keepalive" in body  # the connection was kept alive during the silent stretch
    assert "first" in body and "second" in body  # and both real events still streamed
    assert '"type": "done"' in body


def test_history_replays_prior_events(db):
    sc = FakeSessionsClient(
        history=[
            {"type": "user", "text": "hello"},
            {"type": "tool_use", "name": "search", "server": "atlassian"},
            {"type": "text", "text": "Hi there"},
        ]
    )
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/history")
    assert r.status_code == 200
    body = r.json()
    assert [e["type"] for e in body["events"]] == ["user", "tool_use", "text"]
    assert body["events"][0]["text"] == "hello"
    assert body["status"] == "idle"


def test_history_reports_in_flight_status(db):
    # A turn still queued when the page (re)loads must be reported so the UI can show it.
    sc = FakeSessionsClient(history=[{"type": "user", "text": "retry"}], session_status="queued")
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    body = client.get(f"/chat/{session_id}/history").json()
    assert body["status"] == "queued"
    assert [e["type"] for e in body["events"]] == ["user"]


def test_resume_route_streams_in_flight_turn(db):
    sc = FakeSessionsClient(resume=[{"type": "text", "text": "picked up"}, {"type": "done"}])
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/resume")
    assert r.status_code == 200
    assert "picked up" in r.text
    assert '"type": "done"' in r.text


def test_history_empty_in_stub_mode(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]
    # Stub mode: no sessions client -> empty history, transcript just starts blank.
    app = build_app(
        Settings(env="test", agents_config_path=Path(__file__).parent / "fixtures" / "agents.toml"),
        store=Store(db), app_oidc=FakeOidc({"email": "alice@navapbc.com", "email_verified": True}),
        vault_client=RecordingVaultClient(), sessions_client=None,
    )
    stub_client = TestClient(app, follow_redirects=False)
    _login(stub_client)
    r = stub_client.get(f"/chat/{session_id}/history")
    assert r.status_code == 200
    assert r.json() == {"status": "idle", "events": []}


def test_new_chat_unknown_agent_404(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    assert client.get("/chat?agent_id=nope").status_code == 404


def test_chat_page_not_found_for_other_users_session(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    assert client.get("/chat/nonexistent").status_code == 404


def test_chat_requires_login(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    r = client.get("/chat?agent_id=agent_1")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def _owner_id(db):
    return Store(db).get_user_by_email("alice@navapbc.com")["id"]


def _owner_and_viewer(db, sc):
    """alice (owner) and bob (a different logged-in user) over the same store, plus alice's
    freshly-created session id."""
    owner = TestClient(_app(db, sc, email="alice@navapbc.com"), follow_redirects=False)
    _login(owner)
    session_id = owner.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]
    viewer = TestClient(_app(db, sc, email="bob@navapbc.com"), follow_redirects=False)
    _login(viewer)
    return owner, viewer, session_id


def test_shared_session_opens_read_only_for_non_owner(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    # Private by default: the viewer can't reach it.
    assert viewer.get(f"/chat/{session_id}").status_code == 404
    # Once the owner shares it, the viewer opens a read-only page: no composer, a notice.
    assert Store(db).set_session_shared(session_id, _owner_id(db), True)
    page = viewer.get(f"/chat/{session_id}")
    assert page.status_code == 200
    assert 'id="composer"' not in page.text
    assert "read-only" in page.text.lower()
    # The owner still gets the send box.
    assert 'id="composer"' in owner.get(f"/chat/{session_id}").text
    # The viewer's transcript is flagged read-only so chat.js suppresses tool Approve/Deny.
    assert 'data-can-write="false"' in page.text
    assert 'data-can-write="true"' in owner.get(f"/chat/{session_id}").text


def test_chat_page_shows_delete_button_only_to_the_owner(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    assert "Delete session" in owner.get(f"/chat/{session_id}").text
    # A shared-session viewer gets the read-only view without a delete control.
    assert "Delete session" not in viewer.get(f"/chat/{session_id}").text


def test_non_owner_can_read_but_not_write_shared_session(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    # Read path is open to the viewer.
    assert viewer.get(f"/chat/{session_id}/history").status_code == 200
    # Write paths stay owner-only — a 404 means the route never reached the sessions client.
    assert viewer.get(f"/chat/{session_id}/stream?message=hi").status_code == 404
    assert viewer.get(f"/chat/{session_id}/confirm?tool_use_id=t&result=allow").status_code == 404


def test_private_and_unknown_ids_are_not_found_for_non_owner(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    assert viewer.get(f"/chat/{session_id}").status_code == 404  # private, not shared
    assert viewer.get("/chat/bogus").status_code == 404          # unknown id


def test_owner_toggles_sharing_on_and_off(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    # Turn sharing on (checkbox checked -> "shared" present).
    r = owner.post(f"/chat/{session_id}/share", data={"shared": "on"})
    assert r.status_code == 303 and r.headers["location"] == f"/chat/{session_id}"
    assert viewer.get(f"/chat/{session_id}").status_code == 200
    # Turn it off (checkbox unchecked -> "shared" absent) revokes the viewer's access.
    r = owner.post(f"/chat/{session_id}/share", data={})
    assert r.status_code == 303
    assert viewer.get(f"/chat/{session_id}").status_code == 404


def test_non_owner_cannot_share_anothers_session(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    viewer.post(f"/chat/{session_id}/share", data={"shared": "on"})
    # The flag never flipped: still private to everyone but the owner.
    assert Store(db).get_session(session_id, _owner_id(db))["shared"] is False
    assert viewer.get(f"/chat/{session_id}").status_code == 404


def test_share_checkbox_shows_only_for_owner(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    assert 'action="/chat/' in owner.get(f"/chat/{session_id}").text  # owner sees the share form
    assert "/share" in owner.get(f"/chat/{session_id}").text
    assert "/share" not in viewer.get(f"/chat/{session_id}").text     # viewer does not


def test_owner_reschedules_auto_delete_by_duration(db):
    from datetime import datetime, timedelta, timezone

    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    before_post = datetime.now(timezone.utc)
    r = owner.post(f"/chat/{session_id}/auto-delete",
                   data={"interval_count": "2", "interval_unit": "weeks"})
    assert r.status_code == 303 and r.headers["location"] == f"/chat/{session_id}"
    stored = Store(db).get_session(session_id, _owner_id(db))["auto_delete_at"]
    # Stored as now() + interval in UTC — no time zone involved. Lands ~14 days out (a small
    # tolerance absorbs the time between capturing before_post and the server's own now()).
    expected = before_post + timedelta(weeks=2)
    assert abs((stored - expected).total_seconds()) < 60


def test_reschedule_min_duration_is_always_in_the_future(db):
    from datetime import datetime, timezone

    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    # The smallest allowed interval (1 day) still pushes the delete time into the future, so a
    # session can be pushed out but never turned off (no separate future check needed).
    r = owner.post(f"/chat/{session_id}/auto-delete",
                   data={"interval_count": "1", "interval_unit": "days"})
    assert r.status_code == 303
    stored = Store(db).get_session(session_id, _owner_id(db))["auto_delete_at"]
    assert stored > datetime.now(timezone.utc)


def test_reschedule_rejects_invalid_duration_and_leaves_row_unchanged(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    before = Store(db).get_session(session_id, _owner_id(db))["auto_delete_at"]
    for bad in ({"interval_count": "0", "interval_unit": "days"},      # below minimum
                {"interval_count": "-1", "interval_unit": "days"},     # negative
                {"interval_count": "not-an-int", "interval_unit": "days"},  # non-integer
                {"interval_count": "2", "interval_unit": "hours"}):    # unknown unit
        r = owner.post(f"/chat/{session_id}/auto-delete", data=bad)
        assert r.status_code == 400
    assert Store(db).get_session(session_id, _owner_id(db))["auto_delete_at"] == before


def test_non_owner_cannot_reschedule_anothers_session(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    before = Store(db).get_session(session_id, _owner_id(db))["auto_delete_at"]
    viewer.post(f"/chat/{session_id}/auto-delete",
                data={"interval_count": "4", "interval_unit": "weeks"})
    # Owner-scoped: the viewer's post changes nothing.
    assert Store(db).get_session(session_id, _owner_id(db))["auto_delete_at"] == before


def test_auto_delete_form_shows_only_for_owner(db):
    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    assert "/auto-delete" in owner.get(f"/chat/{session_id}").text        # owner sees the reschedule form
    assert "/auto-delete" not in viewer.get(f"/chat/{session_id}").text   # shared viewer does not


def test_shared_viewer_sees_deletion_notice_and_warning(db):
    from datetime import datetime, timedelta, timezone

    sc = FakeSessionsClient()
    owner, viewer, session_id = _owner_and_viewer(db, sc)
    Store(db).set_session_shared(session_id, _owner_id(db), True)
    # Near deletion -> the viewer (who has no picker) is still warned it's about to disappear.
    Store(db).set_session_auto_delete_at(session_id, _owner_id(db), datetime.now(timezone.utc) + timedelta(days=1))
    text = viewer.get(f"/chat/{session_id}").text
    assert "auto-deletes on" in text
    assert "delete-warning" in text


def test_chat_history_deletes_stale_session_when_platform_gone(db):
    """After the workspace switch, an old session's platform record is gone. Loading its
    history self-heals: the stale local row is deleted and the client is told it's gone."""
    sc = FakeSessionsClient(not_found=True)
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    session_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{session_id}/history")
    assert r.status_code == 410
    assert r.json()["gone"] is True

    # Row removed: a second history load can't find the session at all.
    assert client.get(f"/chat/{session_id}/history").status_code == 404
    assert Store(db).get_session(session_id, _owner_id(db)) is None


def test_delete_session_is_idempotent_when_platform_session_gone():
    """Deleting a session already gone on the platform (e.g. old workspace) is a no-op, not
    an error — so bulk 'delete all' doesn't abort on the first stale session."""
    import anthropic
    import httpx

    client = AnthropicSessionsClient(api_key="test-key")

    def _gone(session_id):
        raise anthropic.NotFoundError(
            f"Session not found: {session_id}",
            response=httpx.Response(404, request=httpx.Request("DELETE", "https://api.anthropic.com/v1/sessions/x")),
            body=None,
        )

    client._client = SimpleNamespace(beta=SimpleNamespace(sessions=SimpleNamespace(delete=_gone)))
    client.delete_session("sesn_gone")  # must not raise

    # A non-404 error still propagates (we only swallow "already gone").
    def _boom(session_id):
        raise RuntimeError("boom")

    client._client.beta.sessions.delete = _boom
    with pytest.raises(RuntimeError):
        client.delete_session("sesn_x")


def _retrieve_client(session_obj):
    """An AnthropicSessionsClient whose beta.sessions.retrieve returns ``session_obj``."""
    client = AnthropicSessionsClient.__new__(AnthropicSessionsClient)
    client._client = SimpleNamespace(
        beta=SimpleNamespace(sessions=SimpleNamespace(retrieve=lambda session_id: session_obj))
    )
    return client


def test_usage_snapshot_reads_cumulative_usage_timing_and_status():
    from datetime import datetime, timezone

    created = datetime(2026, 7, 27, 14, 0, 0, tzinfo=timezone.utc)
    session = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100, output_tokens=40, cache_read_input_tokens=10,
            cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=3, ephemeral_5m_input_tokens=4),
        ),
        stats=SimpleNamespace(active_seconds=12.5, duration_seconds=30.0),
        status="IDLE", created_at=created, agent="agent_1",
    )
    snap = _retrieve_client(session).usage_snapshot("s")
    assert snap["input"] == 100 and snap["output"] == 40 and snap["cache_read"] == 10
    assert snap["cache_creation"] == 7  # 3 + 4, summed from the nested object
    assert snap["active_seconds"] == 12.5 and snap["wall_clock_seconds"] == 30.0
    assert snap["status"] == "idle" and snap["created_at"] == created and snap["agent"] == "agent_1"


def test_usage_snapshot_tolerates_missing_usage_and_stats():
    session = SimpleNamespace(usage=None, stats=None, status=None, created_at=None, agent=None)
    snap = _retrieve_client(session).usage_snapshot("s")
    assert snap["input"] is None and snap["cache_creation"] is None
    assert snap["active_seconds"] is None and snap["wall_clock_seconds"] is None
    assert snap["status"] == ""


def test_usage_snapshot_raises_session_not_found_when_gone():
    import anthropic
    import httpx

    client = AnthropicSessionsClient.__new__(AnthropicSessionsClient)

    def _gone(session_id):
        raise anthropic.NotFoundError(
            "gone",
            response=httpx.Response(404, request=httpx.Request("GET", "https://api.anthropic.com/x")),
            body=None,
        )

    client._client = SimpleNamespace(beta=SimpleNamespace(sessions=SimpleNamespace(retrieve=_gone)))
    with pytest.raises(SessionNotFound):
        client.usage_snapshot("sesn_gone")
