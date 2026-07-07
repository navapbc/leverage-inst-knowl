"""Chat: session create/resume and SSE streaming. The Managed Agents session is faked."""

from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.db import Store
from lik_ui.settings import Settings
from tests.test_app_auth import FakeOidc, _start_login_and_get_state
from tests.test_oauth_connector import RecordingVaultClient


class FakeSessionsClient:
    def __init__(self, events=None, raises=False, history=None):
        self.created = []
        self.events = events if events is not None else [{"type": "text", "text": "Hello"}, {"type": "done"}]
        self.raises = raises
        self.history = history or []

    def create_session(self, agent_id, environment_id, vault_ids):
        self.created.append((agent_id, environment_id, tuple(vault_ids)))
        return f"sess_{len(self.created)}"

    def send_and_stream(self, session_id, message):
        if self.raises:
            raise RuntimeError("stream boom")
        for e in self.events:
            yield e

    def list_events(self, session_id):
        yield from self.history


def _app(db, sessions_client, vc=None):
    vc = vc or RecordingVaultClient()
    oidc = FakeOidc({"email": "alice@navapbc.com", "email_verified": True})
    settings = Settings(env="test", default_agent_id="agent_1", default_environment_id="env_1")
    return build_app(settings, store=Store(db), app_oidc=oidc, vault_client=vc, sessions_client=sessions_client)


def _login(client):
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=x&state={state}")


def test_new_chat_creates_session_with_vault_and_redirects(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)

    r = client.get("/chat?agent_id=agent_1")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/chat/")
    assert sc.created == [("agent_1", "env_1", ("vlt_1",))]  # session bound to the user's vault


def test_resume_does_not_create_a_new_session(db):
    sc = FakeSessionsClient()
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    loc = client.get("/chat?agent_id=agent_1").headers["location"]
    assert len(sc.created) == 1

    page = client.get(loc)  # reopen the conversation
    assert page.status_code == 200
    assert len(sc.created) == 1  # reused, no new session


def test_stream_renders_text_then_done(db):
    sc = FakeSessionsClient(events=[{"type": "text", "text": "Hi there"}, {"type": "done"}])
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    conv_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{conv_id}/stream?message=hello")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert '"type": "text"' in r.text
    assert "Hi there" in r.text
    assert '"type": "done"' in r.text


def test_stream_surfaces_mcp_auth_error(db):
    sc = FakeSessionsClient(
        events=[{"type": "error", "error_type": "mcp_authentication_failed_error", "mcp_server_name": "atlassian"}, {"type": "done"}]
    )
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    conv_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{conv_id}/stream?message=go")
    assert "mcp_authentication_failed_error" in r.text
    assert "atlassian" in r.text


def test_stream_emits_terminal_error_when_client_raises(db):
    sc = FakeSessionsClient(raises=True)
    client = TestClient(_app(db, sc), follow_redirects=False)
    _login(client)
    conv_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{conv_id}/stream?message=go")
    assert r.status_code == 200
    assert "stream_failed" in r.text
    assert '"type": "done"' in r.text


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
    conv_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/chat/{conv_id}/history")
    assert r.status_code == 200
    body = r.json()
    assert [e["type"] for e in body] == ["user", "tool_use", "text"]
    assert body[0]["text"] == "hello"


def test_history_empty_in_stub_mode(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    conv_id = client.get("/chat?agent_id=agent_1").headers["location"].rsplit("/", 1)[1]
    # Stub mode: no sessions client -> empty history, transcript just starts blank.
    app = build_app(
        Settings(env="test", default_agent_id="agent_1", default_environment_id="env_1"),
        store=Store(db), app_oidc=FakeOidc({"email": "alice@navapbc.com", "email_verified": True}),
        vault_client=RecordingVaultClient(), sessions_client=None,
    )
    stub_client = TestClient(app, follow_redirects=False)
    _login(stub_client)
    r = stub_client.get(f"/chat/{conv_id}/history")
    assert r.status_code == 200
    assert r.json() == []


def test_new_chat_unknown_agent_404(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    assert client.get("/chat?agent_id=nope").status_code == 404


def test_chat_page_not_found_for_other_users_conversation(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    _login(client)
    assert client.get("/chat/999999").status_code == 404


def test_chat_requires_login(db):
    client = TestClient(_app(db, FakeSessionsClient()), follow_redirects=False)
    r = client.get("/chat?agent_id=agent_1")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
