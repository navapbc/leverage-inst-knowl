"""The analytics pages: ``/stats`` (the viewer's own sessions, linked in the nav) and
``/all-stats`` (all users' sessions, unlinked — reached only by URL, gated on login).

Each page has a live section (a lightweight per-session platform read at view time) and a
deleted section (from the durable ``session_analytics`` records), with totals and a
server-rendered over-time view. All read-model + platform logic lives in ``analytics.py`` /
``db.py``; this module only assembles the view model and renders. Route handlers import
``templates`` lazily (like the other feature modules) to keep the import graph acyclic.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .analytics import build_live_section


def _series(rows: list[dict]) -> list[dict]:
    """Shape the per-session over-time rows into JSON-safe records (UTC ISO instant + int tokens)
    for the client, which buckets them into local days in the viewer's display zone."""
    return [{"created_at": r["created_at"].isoformat(), "tokens": int(r["tokens"])} for r in rows]


def _agent_label(agents_client, agent_id):
    """Human-readable name for an agent id, falling back to the id itself when the name can't be
    resolved (no client, lookup failure, or an agent with no name). Never raises — a stats page must
    render even if the agents platform is unreachable."""
    if not agent_id:
        return agent_id
    if agents_client is None:
        return agent_id
    try:
        return agents_client.describe(agent_id).get("name") or agent_id
    except Exception:  # noqa: BLE001 - a resolution failure must not fail the stats page
        return agent_id


def _label_agents(agents_client, rows):
    """Attach ``agent_label`` to each live-session row. Resolves each distinct agent id once so a
    page full of same-agent sessions makes a single lookup (the client also memoizes)."""
    labels = {aid: _agent_label(agents_client, aid) for aid in {r.get("agent_id") for r in rows}}
    for r in rows:
        r["agent_label"] = labels.get(r.get("agent_id"))


def _stats_view(store, sessions_client, agents_client, *, live_sessions, user_id, scope_label, per_user, page_path):
    """Assemble the shared stats view model for one scope. ``user_id`` is None for the all-users
    (/all-stats) scope and the viewer's id for /stats. ``page_path`` is where a live-session delete
    should return to."""
    live = build_live_section(sessions_client, live_sessions)
    _label_agents(agents_client, live["rows"])
    return {
        "scope_label": scope_label,
        "page_path": page_path,
        "per_user": store.session_analytics_by_user() if per_user else None,
        "live": live,
        "deleted": {
            "totals": store.session_analytics_totals(user_id),
            "series": _series(store.session_analytics_series(user_id)),
        },
    }


def register_stats_routes(app: FastAPI) -> None:
    from .app import templates  # local import avoids a circular import at module load
    from .app_auth import require_user

    @app.get("/stats", response_class=HTMLResponse)
    async def stats_page(request: Request):
        """Analytics for the logged-in viewer's own sessions only (R1)."""
        user = require_user(request)
        store = request.app.state.store
        sessions_client = request.app.state.sessions_client
        agents_client = request.app.state.agents_client
        view = _stats_view(
            store,
            sessions_client,
            agents_client,
            live_sessions=store.list_sessions(user["id"]),
            user_id=user["id"],
            scope_label="your sessions",
            per_user=False,
            page_path="/stats",
        )
        return templates.TemplateResponse(request, "stats.html", {"user": user, "view": view})

    @app.get("/all-stats", response_class=HTMLResponse)
    async def all_stats_page(request: Request):
        """Analytics across all users' sessions (R3). Not linked in the nav; reached only by URL.
        Requires a logged-in user but applies no further access restriction in this version (R4)."""
        user = require_user(request)
        store = request.app.state.store
        sessions_client = request.app.state.sessions_client
        agents_client = request.app.state.agents_client
        view = _stats_view(
            store,
            sessions_client,
            agents_client,
            live_sessions=store.list_all_sessions(),
            user_id=None,
            scope_label="all users",
            per_user=True,
            page_path="/all-stats",
        )
        return templates.TemplateResponse(request, "stats.html", {"user": user, "view": view})
