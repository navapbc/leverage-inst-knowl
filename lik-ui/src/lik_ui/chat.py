"""Chat: create or resume a Managed Agents session and stream its events to the browser.

A conversation is backed by one managed session (stored session id); reopening a
conversation resumes that session rather than creating a new one. MCP tool calls are
auto-approved on the agent definition, so no approval UI is rendered here — the stream
just surfaces assistant text, tool activity, and connection errors.

The concrete Managed Agents event shapes are normalized behind ``SessionsClient`` so the
UI depends on a small stable vocabulary ({type: text|tool_use|error|done}); the exact SDK
event mapping is validated at live integration (see the plan's deferred questions).
"""

import json
from collections.abc import Iterator
from typing import Protocol

from .settings import Settings
from .vault import ensure_user_vault


class SessionsClient(Protocol):
    def create_session(self, agent_id: str, environment_id: str, vault_ids: list[str]) -> str:
        """Create a session and return its id."""
        ...

    def send_and_stream(self, session_id: str, message: str) -> Iterator[dict]:
        """Send a user message and yield normalized event dicts, e.g.
        {"type": "text", "text": ...}, {"type": "tool_use", "name": ..., "server": ...},
        {"type": "error", "error_type": ..., "mcp_server_name": ...}, {"type": "done"}."""
        ...


class AnthropicSessionsClient:
    """Real ``SessionsClient`` backed by the Anthropic SDK's Managed Agents sessions API.

    Event names/shapes were pinned from the installed SDK (see scripts/smoke.py surface):
    a turn is sent via ``sessions.events.send`` with a ``user.message`` event, and the
    reply streams via ``sessions.events.stream``. The event ``type`` discriminates the
    union (``agent.message``, ``agent.mcp_tool_use``, ``session.error``, ``session.status_*``).
    Confirmed on a live run: the turn terminates with ``session.status_idle`` (the earlier
    ``session.thread_status_idle`` and ``span.*`` events are ignored); ``session.error`` for
    an unconnected MCP server streams first and the agent still answers."""

    def __init__(self, api_key: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def create_session(self, agent_id: str, environment_id: str, vault_ids: list[str]) -> str:
        session = self._client.beta.sessions.create(
            agent=agent_id, environment_id=environment_id, vault_ids=vault_ids
        )
        return session.id

    def send_and_stream(self, session_id: str, message: str) -> Iterator[dict]:
        events = self._client.beta.sessions.events
        events.send(
            session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": message}]}],
        )
        for event in events.stream(session_id):
            etype = getattr(event, "type", "")
            if etype == "agent.message":
                text = "".join(getattr(b, "text", "") for b in getattr(event, "content", []) or [])
                if text:
                    yield {"type": "text", "text": text}
            elif etype == "event_delta":  # incremental text (only if deltas were requested)
                block = getattr(getattr(event, "delta", None), "content", None)
                if text := getattr(block, "text", None):
                    yield {"type": "text", "text": text}
            elif etype == "agent.mcp_tool_use":
                yield {"type": "tool_use", "name": getattr(event, "name", ""), "server": getattr(event, "mcp_server_name", None)}
            elif etype == "session.error":
                err = getattr(event, "error", None)
                yield {
                    "type": "error",
                    "error_type": getattr(err, "type", "session.error"),
                    "mcp_server_name": getattr(err, "mcp_server_name", None),
                }
            elif etype == "end_turn" or etype.startswith(("session.status_idle", "session.status_terminated")):
                break  # the turn is complete
        yield {"type": "done"}


def build_sessions_client(settings: Settings) -> SessionsClient | None:
    if settings.is_stub:
        return None
    return AnthropicSessionsClient(settings.anthropic_api_key)


def register_chat_routes(app) -> None:
    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

    from .app import templates
    from .app_auth import require_user

    @app.get("/chat")
    async def new_chat(request: Request, agent_id: str):
        user = require_user(request)
        settings: Settings = request.app.state.settings
        agent = next((a for a in settings.agents if a.agent_id == agent_id), None)
        if not agent:
            return HTMLResponse("Unknown agent.", status_code=404)

        try:
            vault_id = ensure_user_vault(request.app.state.store, request.app.state.vault_client, user)
            session_id = request.app.state.sessions_client.create_session(
                agent.agent_id, agent.environment_id, [vault_id]
            )
        except Exception as exc:  # noqa: BLE001 - surface session/vault failures as a page, not a 500
            return HTMLResponse(f"Could not start a session: {exc}", status_code=502)
        conv = request.app.state.store.create_conversation(user["id"], agent.agent_id, session_id)
        return RedirectResponse(f"/chat/{conv['id']}", status_code=303)

    @app.get("/chat/{conversation_id}", response_class=HTMLResponse)
    async def chat_page(request: Request, conversation_id: int):
        user = require_user(request)
        conv = request.app.state.store.get_conversation(conversation_id, user["id"])
        if not conv:
            return HTMLResponse("Conversation not found.", status_code=404)
        conversations = request.app.state.store.list_conversations(user["id"])
        return templates.TemplateResponse(
            request, "chat.html", {"conversation": conv, "conversations": conversations}
        )

    @app.get("/chat/{conversation_id}/stream")
    def chat_stream(request: Request, conversation_id: int, message: str):
        user = require_user(request)
        conv = request.app.state.store.get_conversation(conversation_id, user["id"])
        if not conv:
            return HTMLResponse("Conversation not found.", status_code=404)

        sessions_client: SessionsClient = request.app.state.sessions_client

        def event_stream():
            try:
                for event in sessions_client.send_and_stream(conv["session_id"], message):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as exc:  # noqa: BLE001 - stream a terminal error, don't 500 mid-stream
                yield f"data: {json.dumps({'type': 'error', 'error_type': 'stream_failed', 'detail': str(exc)})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
