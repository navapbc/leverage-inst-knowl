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

    The event normalization here is best-effort against the documented event stream and is
    the piece to confirm against the live API (plan deferred question)."""

    def __init__(self, api_key: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def create_session(self, agent_id: str, environment_id: str, vault_ids: list[str]) -> str:
        session = self._client.beta.sessions.create(
            agent=agent_id, environment_id=environment_id, vault_ids=vault_ids
        )
        return session.id

    def send_and_stream(self, session_id: str, message: str) -> Iterator[dict]:
        with self._client.beta.sessions.stream(session_id=session_id, input=message) as stream:
            for event in stream:
                etype = getattr(event, "type", "")
                if "error" in etype:
                    yield {
                        "type": "error",
                        "error_type": getattr(event, "error_type", etype),
                        "mcp_server_name": getattr(event, "mcp_server_name", None),
                    }
                elif "tool" in etype:
                    yield {"type": "tool_use", "name": getattr(event, "name", ""), "server": getattr(event, "mcp_server_name", None)}
                elif text := getattr(event, "text", None):
                    yield {"type": "text", "text": text}
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

        vault_id = ensure_user_vault(request.app.state.store, request.app.state.vault_client, user)
        session_id = request.app.state.sessions_client.create_session(
            agent.agent_id, agent.environment_id, [vault_id]
        )
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
