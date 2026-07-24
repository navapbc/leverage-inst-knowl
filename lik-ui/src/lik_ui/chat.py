"""Chat: create or resume a Managed Agents session and stream its events to the browser.

A session is the Managed Agents session, persisted by its session id; reopening a
session resumes it rather than creating a new one. The stream surfaces assistant text,
tool activity, and connection errors. A permission-gated tool call ("ask") pauses the
turn awaiting the user's approval; that pause is surfaced so the UI can prompt, and the
user's allow/deny decision is sent back to resume the turn.

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


class SessionNotFound(Exception):
    """The platform session no longer exists in the current workspace — e.g. the app's API
    key was repointed at a different Claude Workspace (sessions are workspace-scoped), or the
    session was deleted out-of-band. Lets callers drop the stale local row instead of erroring."""


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
    def create_session(
        self, agent_id: str, environment_id: str, vault_ids: list[str], title: str
    ) -> str:
        """Create a session and return its id."""
        ...

    def delete_session(self, session_id: str) -> None:
        """Delete the session on the platform, removing its retained data."""
        ...

    def send_and_stream(self, session_id: str, message: str) -> Iterator[dict]:
        """Send a user message and yield normalized event dicts, e.g.
        {"type": "status", "state": "running"}, {"type": "text", "text": ...},
        {"type": "tool_use", "name": ..., "server": ...},
        {"type": "error", "error_type": ..., "mcp_server_name": ...}, {"type": "done"}.
        A turn that pauses for the user ends with {"type": "awaiting_confirmation",
        "event_ids": [...]} instead of "done"; resume it with ``confirm_and_stream``."""
        ...

    def confirm_and_stream(
        self,
        session_id: str,
        tool_use_id: str,
        result: str,
        session_thread_id: str | None = None,
        deny_message: str | None = None,
    ) -> Iterator[dict]:
        """Answer a paused tool call (``result`` is "allow" or "deny") and yield the resumed
        turn's events, using the same normalized vocabulary as ``send_and_stream``."""
        ...

    def list_events(self, session_id: str) -> Iterator[dict]:
        """Yield the session's prior events in chronological order, using the same
        normalized vocabulary as ``send_and_stream`` plus {"type": "user", "text": ...}
        for the user's own turns (which the live stream never echoes back)."""
        ...

    def status(self, session_id: str) -> str:
        """Return the session's current lifecycle status (e.g. "idle", "queued",
        "running"). Read on page load so an in-flight turn can be reflected in the UI."""
        ...

    def resume_stream(self, session_id: str) -> Iterator[dict]:
        """Attach to an already in-flight turn without sending anything, yielding its
        remaining events in the same normalized vocabulary as ``send_and_stream``. Used
        when a page reload finds a turn still queued/running so it isn't left silent."""
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

    def create_session(
        self, agent_id: str, environment_id: str, vault_ids: list[str], title: str
    ) -> str:
        session = self._client.beta.sessions.create(
            agent=agent_id, environment_id=environment_id, vault_ids=vault_ids, title=title
        )
        return session.id

    def delete_session(self, session_id: str) -> None:
        import anthropic

        try:
            self._client.beta.sessions.delete(session_id)
        except anthropic.NotFoundError:
            pass  # already gone on the platform (workspace switch / prior delete) — idempotent

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
        if etype in ("agent.mcp_tool_use", "agent.tool_use"):
            # MCP tools carry an mcp_server_name; built-in agent tools don't (server -> None).
            # ``permission`` is the gate the agent evaluated for this call: "allow" ran it,
            # "ask" means it's paused for the user's approval (the UI prompts on this), "deny"
            # blocked it. ``session_thread_id`` is set only when the request was cross-posted
            # from a subagent's thread; it's echoed back on the approval to route it home.
            return {
                "type": "tool_use",
                "id": getattr(event, "id", None),
                "name": getattr(event, "name", ""),
                "server": getattr(event, "mcp_server_name", None),
                "input": getattr(event, "input", None) or {},
                "permission": getattr(event, "evaluated_permission", None),
                "session_thread_id": getattr(event, "session_thread_id", None),
            }
        if etype in ("agent.mcp_tool_result", "agent.tool_result"):
            # The call id lives on mcp_tool_use_id for MCP results, tool_use_id for built-ins.
            return {
                "type": "tool_result",
                "tool_use_id": getattr(event, "mcp_tool_use_id", None) or getattr(event, "tool_use_id", None),
                "is_error": bool(getattr(event, "is_error", False)),
                "content": _blocks_to_text(getattr(event, "content", None)),
            }
        if etype == "session.error":
            err = getattr(event, "error", None)
            return {
                "type": "error",
                "error_type": getattr(err, "type", "session.error"),
                "mcp_server_name": getattr(err, "mcp_server_name", None),
                # Carry the platform's human-readable message and whether it's still
                # retrying vs. given up, so the UI can show a non-MCP error (e.g. an
                # overloaded model) accurately instead of a generic "reconnect" nudge.
                "message": getattr(err, "message", None),
                "retry_status": getattr(getattr(err, "retry_status", None), "type", None),
            }
        if etype == "session.status_running":
            # The turn left the work queue and the agent is now working. Lets the UI move a
            # submitted message from "queued" to "running" before any output arrives. Transient
            # by nature, so it's dropped from history replay (see ``list_events``).
            return {"type": "status", "state": "running"}
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

    @staticmethod
    def _requires_action_ids(idle_event) -> list[str]:
        """The event ids a ``session.status_idle`` is blocked on, or ``[]`` if it's just a
        completed turn. A turn pauses (rather than ends) at idle when its ``stop_reason`` is
        ``requires_action`` — e.g. a permission-gated tool call awaiting the user's approval."""
        stop = getattr(idle_event, "stop_reason", None)
        if getattr(stop, "type", None) == "requires_action":
            return list(getattr(stop, "event_ids", None) or [])
        return []

    def _stream(self, session_id: str, send_events: list[dict] | None) -> Iterator[dict]:
        """Dispatch ``send_events`` into the session (or nothing, when ``send_events`` is
        None — used to attach to a turn already in flight) and yield the turn's normalized
        events. Terminates with ``{"type": "done"}`` when the turn completes, or
        ``{"type": "awaiting_confirmation", "event_ids": [...]}`` when it pauses for the user
        (e.g. a tool call needing approval) — the caller resumes via ``confirm_and_stream``."""
        events = self._client.beta.sessions.events
        # Subscribe BEFORE sending. ``stream()`` opens the HTTP connection eagerly (the request
        # is issued when it's called, not on first iteration), so the subscription is already
        # listening before ``send()`` dispatches the turn. Sending first left a gap in which a
        # fast turn could produce and finish its reply before we subscribed — we'd then see only
        # the terminal ``session.status_idle`` and stream nothing, stranding the reply behind a
        # page refresh. The stream carries only events from connection time forward (prior turns
        # aren't replayed), so opening it early doesn't duplicate history.
        with events.stream(session_id) as stream:
            if send_events:
                events.send(session_id, events=send_events)
            for event in stream:
                etype = getattr(event, "type", "")
                if etype == "end_turn" or etype.startswith("session.status_terminated"):
                    break  # the turn is complete
                if etype.startswith("session.status_idle"):
                    if pending := self._requires_action_ids(event):
                        # Paused, not finished: don't emit "done" — the UI keeps the turn open
                        # and prompts. Resolving all pending events resumes the turn.
                        yield {"type": "awaiting_confirmation", "event_ids": pending}
                        return
                    break  # a plain end-of-turn idle
                if normalized := self._normalize(event):
                    yield normalized
        yield {"type": "done"}

    def send_and_stream(self, session_id: str, message: str) -> Iterator[dict]:
        yield from self._stream(
            session_id,
            [{"type": "user.message", "content": [{"type": "text", "text": message}]}],
        )

    def confirm_and_stream(
        self,
        session_id: str,
        tool_use_id: str,
        result: str,
        session_thread_id: str | None = None,
        deny_message: str | None = None,
    ) -> Iterator[dict]:
        event: dict = {
            "type": "user.tool_confirmation",
            "result": result,
            "tool_use_id": tool_use_id,
        }
        # Echo the originating subagent thread (if any) so the approval routes back to it.
        if session_thread_id:
            event["session_thread_id"] = session_thread_id
        # A rationale is only meaningful on a denial.
        if result == "deny" and deny_message:
            event["deny_message"] = deny_message
        yield from self._stream(session_id, [event])

    def list_events(self, session_id: str) -> Iterator[dict]:
        import anthropic

        try:
            events = self._client.beta.sessions.events.list(session_id, order="asc")
            for event in events:
                if normalized := self._normalize(event, include_user=True):
                    if normalized["type"] == "status":
                        continue  # live-only; a past turn's "running" means nothing on replay
                    yield normalized
        except anthropic.NotFoundError as exc:
            raise SessionNotFound(session_id) from exc

    def status(self, session_id: str) -> str:
        import anthropic

        try:
            session = self._client.beta.sessions.retrieve(session_id)
        except anthropic.NotFoundError as exc:
            raise SessionNotFound(session_id) from exc
        status = (getattr(session, "status", "") or "").lower()
        # A turn submitted but not yet started sits with the session status still "idle"
        # while the user message waits unprocessed (``processed_at`` null) — the platform
        # labels that "queued". The session status never reports it, so derive it from the
        # trailing event instead, so a page reload can show the turn is queued.
        if status in ("", "idle"):
            latest = None
            for event in self._client.beta.sessions.events.list(session_id, order="asc"):
                latest = event
            if (
                latest is not None
                and getattr(latest, "type", "") == "user.message"
                and getattr(latest, "processed_at", None) is None
            ):
                return "queued"
        return status

    def resume_stream(self, session_id: str) -> Iterator[dict]:
        # Only attach when a turn is actually in flight: subscribing to an idle session
        # would block waiting for events that never come. This re-checks status (the page
        # decided to resume from a slightly older read); on the rare race where the turn
        # ends in between, the browser falls back to a history reload on ``done``.
        if self.status(session_id).lower() in ("", "idle"):
            yield {"type": "done"}
            return
        yield from self._stream(session_id, None)


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

        # Fall back to the agent name plus a timestamp when the user leaves the title blank,
        # so every session is named (matches the placeholder shown next to "Start chatting").
        # The label comes from the agent's own definition via the SDK; fall back to its id.
        label = agent.agent_id
        agents_client = request.app.state.agents_client
        if agents_client is not None:
            try:
                label = agents_client.describe(agent.agent_id)["name"] or agent.agent_id
            except Exception:  # noqa: BLE001 - a label lookup failure shouldn't block starting a chat
                pass
        title = title.strip() or f"{label} · {datetime.now():%b %d, %Y %H:%M}"
        try:
            vault_id = ensure_user_vault(request.app.state.store, request.app.state.vault_client, user)
            session_id = request.app.state.sessions_client.create_session(
                agent.agent_id, agent.environment_id, [vault_id], title
            )
        except Exception as exc:  # noqa: BLE001 - surface session/vault failures as a page, not a 500
            return HTMLResponse(f"Could not start a session: {exc}", status_code=502)
        request.app.state.store.create_session(user["id"], agent.agent_id, session_id, title)
        return RedirectResponse(f"/chat/{session_id}", status_code=303)

    @app.get("/sessions", response_class=HTMLResponse)
    async def sessions_page(request: Request):
        user = require_user(request)
        sessions = request.app.state.store.list_sessions(user["id"])
        return templates.TemplateResponse(
            request, "sessions.html", {"user": user, "sessions": sessions}
        )

    @app.post("/sessions/delete")
    async def delete_session(request: Request):
        user = require_user(request)
        form = await request.form()
        session_id = form.get("session_id", "")
        # Ownership check: only the owning user can delete, and only an existing row.
        session = request.app.state.store.get_session(session_id, user["id"])
        if not session:
            return RedirectResponse("/sessions", status_code=303)
        # Delete the platform session first so its retained data is actually removed; only
        # then drop the local row, keeping the list honest (a listed session still exists on
        # the platform). Stub/test mode has no platform session, so it deletes the row alone.
        sessions_client: SessionsClient | None = request.app.state.sessions_client
        if sessions_client is not None:
            try:
                sessions_client.delete_session(session_id)
            except Exception as exc:  # noqa: BLE001 - surface session/SDK errors as a page, not a 500
                return HTMLResponse(f"Could not delete that session: {exc}", status_code=502)
        request.app.state.store.delete_session(session_id, user["id"])
        return RedirectResponse("/sessions", status_code=303)

    @app.post("/chat/{session_id}/share")
    async def share_session(request: Request, session_id: str):
        """Owner toggles read-only sharing. The checkbox posts ``shared`` only when checked,
        so its absence means "make private". ``set_session_shared`` is owner-scoped, so a
        non-owner's post changes nothing. Redirect back to the session either way."""
        user = require_user(request)
        form = await request.form()
        shared = form.get("shared") is not None
        request.app.state.store.set_session_shared(session_id, user["id"], shared)
        return RedirectResponse(f"/chat/{session_id}", status_code=303)

    @app.get("/chat/{session_id}", response_class=HTMLResponse)
    async def chat_page(request: Request, session_id: str):
        user = require_user(request)
        # Read access: the owner, or anyone when the owner marked the session shared. A
        # non-owner gets a read-only view (composer/controls hidden below via is_owner).
        session = request.app.state.store.get_accessible_session(session_id, user["id"])
        if not session:
            return HTMLResponse("Session not found.", status_code=404)
        is_owner = session["user_id"] == user["id"]
        # Show the agent's display name and its declared MCP servers; both come from the
        # agent's own definition via the SDK. Each server carries its permission_policy so the
        # auto-approve checklist can lock a server that already always-allows server-side (its
        # calls never pause, so the checkbox can't meaningfully be unchecked). Server names
        # match the mcp_server_name on tool-use events. Fall back to the agent id / no servers
        # when the lookup is unavailable.
        agent_label = session["agent_id"]
        servers: list[dict] = []
        agents_client = request.app.state.agents_client
        if agents_client is not None:
            try:
                described = agents_client.describe(session["agent_id"])
                agent_label = described["name"] or session["agent_id"]
                servers = described["servers"]
            except Exception:  # noqa: BLE001 - a label lookup failure shouldn't block viewing the chat
                pass
        return templates.TemplateResponse(
            request, "chat.html",
            {"user": user, "session": session, "agent_label": agent_label,
             "servers": servers, "is_owner": is_owner},
        )

    @app.get("/chat/{session_id}/history")
    def chat_history(request: Request, session_id: str):
        """Prior events for the session plus its current status, replayed when the page
        opens. The status lets the page reflect a turn still in flight (e.g. a queued
        retry after a reload). Empty/idle in stub mode so the transcript starts blank."""
        user = require_user(request)
        session = request.app.state.store.get_accessible_session(session_id, user["id"])
        if not session:
            return JSONResponse({"detail": "Session not found."}, status_code=404)

        sessions_client: SessionsClient | None = request.app.state.sessions_client
        if sessions_client is None:
            return JSONResponse({"status": "idle", "events": []})
        try:
            events = list(sessions_client.list_events(session["session_id"]))
            status = sessions_client.status(session["session_id"])
        except SessionNotFound:
            # Platform session is gone (workspace switch or out-of-band delete). Drop the
            # stale local row (owner-scoped) so it stops listing and erroring, and tell the
            # client it's gone so it can send the user back to the sessions list.
            request.app.state.store.delete_session(session["session_id"], user["id"])
            return JSONResponse(
                {"detail": "Session is not in the current workspace; session removed.", "gone": True},
                status_code=410,
            )
        except Exception as exc:  # noqa: BLE001 - a history-fetch failure shouldn't block chatting
            return JSONResponse(
                {"detail": f"Could not load history: {exc}"}, status_code=502
            )
        return JSONResponse({"status": status, "events": events})

    @app.get("/chat/{session_id}/resume")
    def chat_resume(request: Request, session_id: str):
        """Attach to a turn already in flight (found via the status on page load) and
        stream its remaining events, so a queued/running turn isn't left silent until a
        manual refresh. No-op (just ``done``) in stub mode or once the turn has ended."""
        user = require_user(request)
        # Read-only attach: a shared-session viewer can watch an in-flight turn, but never sends.
        session = request.app.state.store.get_accessible_session(session_id, user["id"])
        if not session:
            return HTMLResponse("Session not found.", status_code=404)

        sessions_client: SessionsClient | None = request.app.state.sessions_client
        if sessions_client is None:
            return _sse(iter([{"type": "done"}]))
        return _sse(sessions_client.resume_stream(session["session_id"]))

    def _sse(events: Iterator[dict]) -> StreamingResponse:
        """Wrap a normalized-event generator as an SSE response, converting a mid-stream
        failure into a terminal error + done so the browser closes cleanly rather than 500ing."""

        def event_stream():
            try:
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as exc:  # noqa: BLE001 - stream a terminal error, don't 500 mid-stream
                yield f"data: {json.dumps({'type': 'error', 'error_type': 'stream_failed', 'detail': str(exc)})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/chat/{session_id}/stream")
    def chat_stream(request: Request, session_id: str, message: str):
        user = require_user(request)
        session = request.app.state.store.get_session(session_id, user["id"])
        if not session:
            return HTMLResponse("Session not found.", status_code=404)

        sessions_client: SessionsClient = request.app.state.sessions_client
        return _sse(sessions_client.send_and_stream(session["session_id"], message))

    @app.get("/chat/{session_id}/confirm")
    def chat_confirm(
        request: Request,
        session_id: str,
        tool_use_id: str,
        result: str,
        session_thread_id: str = "",
        deny_message: str = "",
    ):
        """Answer a paused tool call and stream the resumed turn. GET (not POST) so the browser
        can consume it with an ``EventSource``, matching the send stream."""
        user = require_user(request)
        session = request.app.state.store.get_session(session_id, user["id"])
        if not session:
            return HTMLResponse("Session not found.", status_code=404)
        if result not in ("allow", "deny"):
            return HTMLResponse("result must be 'allow' or 'deny'.", status_code=400)

        sessions_client: SessionsClient = request.app.state.sessions_client
        return _sse(sessions_client.confirm_and_stream(
            session["session_id"], tool_use_id, result,
            session_thread_id or None, deny_message or None,
        ))
