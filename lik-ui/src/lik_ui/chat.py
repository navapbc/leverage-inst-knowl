"""Chat: create or resume a Managed Agents session and stream its events to the browser.

A session is the Managed Agents session, persisted by its session id; reopening a
session resumes it rather than creating a new one. MCP tool calls are
auto-approved on the agent definition, so no approval UI is rendered here — the stream
just surfaces assistant text, tool activity, and connection errors.

The concrete Managed Agents event shapes are normalized behind ``SessionsClient`` so the
UI depends on a small stable vocabulary ({type: text|tool_use|error|done}); the exact SDK
event mapping is validated at live integration (see the plan's deferred questions).
"""

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Protocol

from .settings import Settings
from .vault import ensure_user_vault


def _blocks_to_text(blocks) -> str:
    """Flatten a tool-result content block list to display text. Text blocks contribute
    their text; non-text blocks (image/document/search_result) are noted by kind so the
    reader knows something was returned without the UI having to render binary payloads."""
    parts = []
    for b in blocks or []:
        if text := getattr(b, "text", None):
            parts.append(text)
        else:
            parts.append(f"[{getattr(b, 'type', 'content')}]")
    return "\n".join(parts)


class SessionsClient(Protocol):
    def create_session(self, agent_id: str, environment_id: str, vault_ids: list[str]) -> str:
        """Create a session and return its id."""
        ...

    def send_and_stream(self, session_id: str, message: str) -> Iterator[dict]:
        """Send a user message and yield normalized event dicts, e.g.
        {"type": "text", "text": ...}, {"type": "tool_use", "name": ..., "server": ...},
        {"type": "error", "error_type": ..., "mcp_server_name": ...}, {"type": "done"}."""
        ...

    def list_events(self, session_id: str) -> Iterator[dict]:
        """Yield the session's prior events in chronological order, using the same
        normalized vocabulary as ``send_and_stream`` plus {"type": "user", "text": ...}
        for the user's own turns (which the live stream never echoes back)."""
        ...


class AnthropicSessionsClient:
    """Real ``SessionsClient`` backed by the Anthropic SDK's Managed Agents sessions API.

    Event names/shapes were pinned from the installed SDK (see scripts/smoke.py surface):
    a turn is sent via ``sessions.events.send`` with a ``user.message`` event, and the
    reply streams via ``sessions.events.stream``. The event ``type`` discriminates the
    union (``agent.message``, ``agent.mcp_tool_use``, ``session.error``, ``session.status_*``).
    Confirmed on a live run: the turn terminates with ``session.status_idle`` (the earlier
    ``session.thread_status_idle`` and most ``span.*`` events are ignored, except
    ``span.model_request_end`` which carries token usage); ``session.error`` for an
    unconnected MCP server streams first and the agent still answers."""

    def __init__(self, api_key: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def create_session(self, agent_id: str, environment_id: str, vault_ids: list[str]) -> str:
        session = self._client.beta.sessions.create(
            agent=agent_id, environment_id=environment_id, vault_ids=vault_ids
        )
        return session.id

    @staticmethod
    def _normalize(event, *, include_user: bool = False) -> dict | None:
        """Map one SDK event to the UI's normalized vocabulary, or None to drop it.
        ``include_user`` surfaces the user's own turns — wanted when replaying history,
        but not on the live stream (the browser adds the user bubble locally on submit)."""
        etype = getattr(event, "type", "")
        if etype == "user.message":
            if not include_user:
                return None
            text = "".join(getattr(b, "text", "") for b in getattr(event, "content", []) or [])
            return {"type": "user", "text": text} if text else None
        if etype == "agent.message":
            text = "".join(getattr(b, "text", "") for b in getattr(event, "content", []) or [])
            return {"type": "text", "text": text} if text else None
        if etype == "event_delta":  # incremental text (only if deltas were requested)
            block = getattr(getattr(event, "delta", None), "content", None)
            if text := getattr(block, "text", None):
                return {"type": "text", "text": text}
            return None
        if etype == "agent.mcp_tool_use":
            return {
                "type": "tool_use",
                "id": getattr(event, "id", None),
                "name": getattr(event, "name", ""),
                "server": getattr(event, "mcp_server_name", None),
                "input": getattr(event, "input", None) or {},
            }
        if etype == "agent.mcp_tool_result":
            return {
                "type": "tool_result",
                "tool_use_id": getattr(event, "mcp_tool_use_id", None),
                "is_error": bool(getattr(event, "is_error", False)),
                "content": _blocks_to_text(getattr(event, "content", None)),
            }
        if etype == "session.error":
            err = getattr(event, "error", None)
            return {
                "type": "error",
                "error_type": getattr(err, "type", "session.error"),
                "mcp_server_name": getattr(err, "mcp_server_name", None),
            }
        if etype == "agent.thread_context_compacted":
            return {"type": "compacted"}
        if etype == "span.model_request_end":
            usage = getattr(event, "model_usage", None)
            if usage is None:
                return None
            return {
                "type": "usage",
                "input": getattr(usage, "input_tokens", 0),
                "output": getattr(usage, "output_tokens", 0),
                "cache_read": getattr(usage, "cache_read_input_tokens", 0),
                "cache_creation": getattr(usage, "cache_creation_input_tokens", 0),
            }
        return None

    def send_and_stream(self, session_id: str, message: str) -> Iterator[dict]:
        events = self._client.beta.sessions.events
        events.send(
            session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": message}]}],
        )
        for event in events.stream(session_id):
            etype = getattr(event, "type", "")
            if etype == "end_turn" or etype.startswith(("session.status_idle", "session.status_terminated")):
                break  # the turn is complete
            if normalized := self._normalize(event):
                yield normalized
        yield {"type": "done"}

    def list_events(self, session_id: str) -> Iterator[dict]:
        for event in self._client.beta.sessions.events.list(session_id, order="asc"):
            if normalized := self._normalize(event, include_user=True):
                yield normalized


def build_sessions_client(settings: Settings) -> SessionsClient | None:
    if settings.is_stub:
        return None
    return AnthropicSessionsClient(settings.anthropic_api_key)


def register_chat_routes(app) -> None:
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

    from .app import templates
    from .app_auth import require_user

    @app.get("/chat")
    async def new_chat(request: Request, agent_id: str, title: str = ""):
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
        # Fall back to the agent name plus a timestamp when the user leaves the title blank,
        # so every session is named (matches the placeholder shown next to "Start chatting").
        title = title.strip() or f"{agent.label} · {datetime.now():%b %d, %Y %H:%M}"
        request.app.state.store.create_session(user["id"], agent.agent_id, session_id, title)
        return RedirectResponse(f"/chat/{session_id}", status_code=303)

    @app.get("/sessions", response_class=HTMLResponse)
    async def sessions_page(request: Request):
        user = require_user(request)
        sessions = request.app.state.store.list_sessions(user["id"])
        return templates.TemplateResponse(
            request, "sessions.html", {"user": user, "sessions": sessions}
        )

    @app.get("/chat/{session_id}", response_class=HTMLResponse)
    async def chat_page(request: Request, session_id: str):
        user = require_user(request)
        session = request.app.state.store.get_session(session_id, user["id"])
        if not session:
            return HTMLResponse("Session not found.", status_code=404)
        return templates.TemplateResponse(request, "chat.html", {"user": user, "session": session})

    @app.get("/chat/{session_id}/history")
    def chat_history(request: Request, session_id: str):
        """Prior events for the session, replayed when the page opens.
        Empty in stub mode (no sessions client) so the transcript just starts blank."""
        user = require_user(request)
        session = request.app.state.store.get_session(session_id, user["id"])
        if not session:
            return JSONResponse({"detail": "Session not found."}, status_code=404)

        sessions_client: SessionsClient | None = request.app.state.sessions_client
        if sessions_client is None:
            return JSONResponse([])
        try:
            events = list(sessions_client.list_events(session["session_id"]))
        except Exception as exc:  # noqa: BLE001 - a history-fetch failure shouldn't block chatting
            return JSONResponse(
                {"detail": f"Could not load history: {exc}"}, status_code=502
            )
        return JSONResponse(events)

    @app.get("/chat/{session_id}/stream")
    def chat_stream(request: Request, session_id: str, message: str):
        user = require_user(request)
        session = request.app.state.store.get_session(session_id, user["id"])
        if not session:
            return HTMLResponse("Session not found.", status_code=404)

        sessions_client: SessionsClient = request.app.state.sessions_client

        def event_stream():
            try:
                for event in sessions_client.send_and_stream(session["session_id"], message):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as exc:  # noqa: BLE001 - stream a terminal error, don't 500 mid-stream
                yield f"data: {json.dumps({'type': 'error', 'error_type': 'stream_failed', 'detail': str(exc)})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
