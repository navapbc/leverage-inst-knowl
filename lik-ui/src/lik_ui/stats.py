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


def _bars(rows: list[dict], value_key: str) -> list[dict]:
    """Attach a 0–100 bar percentage to each daily bucket, sized against the largest bucket, so
    the template can draw the over-time view without doing math. An all-zero set yields 0% bars."""
    peak = max((row[value_key] for row in rows), default=0) or 0
    out = []
    for row in rows:
        pct = round(100 * row[value_key] / peak) if peak else 0
        out.append({**row, "pct": pct})
    return out


def _stats_view(store, sessions_client, *, live_sessions, user_id, scope_label, per_user, page_path):
    """Assemble the shared stats view model for one scope. ``user_id`` is None for the all-users
    (/all-stats) scope and the viewer's id for /stats. ``page_path`` is where a live-session delete
    should return to."""
    daily = store.session_analytics_daily(user_id)
    return {
        "scope_label": scope_label,
        "page_path": page_path,
        "per_user": store.session_analytics_by_user() if per_user else None,
        "live": build_live_section(sessions_client, live_sessions),
        "deleted": {
            "totals": store.session_analytics_totals(user_id),
            "daily": _bars(daily, "tokens"),
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
        view = _stats_view(
            store,
            sessions_client,
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
        view = _stats_view(
            store,
            sessions_client,
            live_sessions=store.list_all_sessions(),
            user_id=None,
            scope_label="all users",
            per_user=True,
            page_path="/all-stats",
        )
        return templates.TemplateResponse(request, "stats.html", {"user": user, "view": view})
