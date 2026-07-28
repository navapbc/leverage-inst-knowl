"""Account settings — user-facing management of their own data.

Credential/vault management, session cleanup, and self-service scheduled runs: a user schedules
an eligible (unattended-safe) agent to run on a cadence using their own vault, and reviews each
schedule's health. Deleting the vault also cancels the user's schedules (they can't run without
credentials).
"""

from datetime import timedelta

from .vault import VaultClient, delete_user_vault

# Preset cadences offered in the scheduler UI (v1 — free cron expressions are deferred). The label
# is what the user picks; the timedelta is stored as the schedule's run_interval. Ordered
# longest-first so the least-frequent cadence is the default selection in the picker.
CADENCES: dict[str, timedelta] = {
    "weekly": timedelta(weeks=1),
    "daily": timedelta(days=1),
}


def register_account_routes(app) -> None:
    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    from .app import templates
    from .app_auth import require_user, set_show_management_agents, show_management_agents

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(
        request: Request, deleted: str = "", sessions_deleted: str = "",
        scheduled: str = "", scheduled_error: str = "",
    ):
        user = require_user(request)
        store = request.app.state.store
        vault_id = store.get_user_vault(user["id"])
        vault_client: VaultClient | None = request.app.state.vault_client
        credentials = []
        if vault_id and vault_client is not None:
            try:
                credentials = vault_client.list_credentials(vault_id)
            except Exception as exc:  # noqa: BLE001 - a listing failure shouldn't 500 the page
                return HTMLResponse(f"Could not load your credentials: {exc}", status_code=502)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "user": user,
                "vault_id": vault_id,
                "credentials": credentials,
                "deleted": bool(deleted),
                "session_count": len(store.list_sessions(user["id"])),
                "sessions_deleted": bool(sessions_deleted),
                "show_management_agents": show_management_agents(request),
                # Scheduled runs: the user's own schedules, and the agents they may schedule
                # (only those the roster marks unattended-safe). agent_name is the display label.
                "scheduled_runs": store.list_scheduled_runs(user["id"]),
                "schedulable_agents": [a.agent_name for a in request.app.state.agents if a.schedulable],
                "cadences": list(CADENCES),
                "scheduled_created": bool(scheduled),
                "scheduled_error": bool(scheduled_error),
            },
        )

    @app.post("/settings/scheduled-runs")
    async def create_scheduled_run(request: Request):
        """Create a schedule for the current user. The agent must be marked schedulable in the
        roster (a user can't schedule an agent that isn't unattended-safe); the cadence must be a
        known preset; a triggering message is required. max_runtime is materialized from the agent's
        roster value so the runner watchdog and the reclaim cutoff share one source."""
        user = require_user(request)
        form = await request.form()
        agent_name = str(form.get("agent_name", "")).strip()
        cadence = str(form.get("cadence", "")).strip()
        prompt = str(form.get("prompt", "")).strip()
        option = next(
            (a for a in request.app.state.agents if a.agent_name == agent_name and a.schedulable), None
        )
        interval = CADENCES.get(cadence)
        if option is None or interval is None or not prompt:
            return RedirectResponse("/settings?scheduled_error=1", status_code=303)
        request.app.state.store.create_scheduled_run(
            user["id"], agent_name, prompt, interval, option.max_runtime
        )
        return RedirectResponse("/settings?scheduled=1", status_code=303)

    @app.post("/settings/scheduled-runs/{run_id}/delete")
    async def delete_scheduled_run(request: Request, run_id: int):
        user = require_user(request)
        request.app.state.store.delete_scheduled_run(run_id, user["id"])  # owner-scoped no-op if not theirs
        return RedirectResponse("/settings", status_code=303)

    @app.post("/settings/scheduled-runs/{run_id}/pause")
    async def pause_scheduled_run(request: Request, run_id: int):
        """Pause or resume a schedule. Resuming also clears a needs_reauth flag, so re-authenticating
        and resuming brings a lapsed schedule back."""
        user = require_user(request)
        form = await request.form()
        paused = str(form.get("paused", "")) == "true"
        request.app.state.store.set_scheduled_run_paused(run_id, user["id"], paused)
        return RedirectResponse("/settings", status_code=303)

    @app.post("/settings/agent-visibility")
    async def set_agent_visibility(request: Request):
        """Toggle whether management (write-capable) agents show in the picker. A checkbox submits
        its value only when checked, so an absent field means unchecked -> hidden. Persisted in the
        session; guardrail only, so nothing else changes."""
        require_user(request)
        form = await request.form()
        set_show_management_agents(request, form.get("show_management_agents") is not None)
        return RedirectResponse("/settings", status_code=303)

    @app.post("/settings/vault/delete")
    async def delete_vault(request: Request):
        user = require_user(request)
        store = request.app.state.store
        vault_client: VaultClient | None = request.app.state.vault_client
        try:
            delete_user_vault(store, vault_client, user)
        except Exception as exc:  # noqa: BLE001 - surface vault/SDK errors as a page, not a 500
            return HTMLResponse(f"Could not delete your vault: {exc}", status_code=502)
        # R19: a schedule must not keep running with revoked credentials. Cancel the user's
        # schedules when their vault is deleted (they can recreate them after reconnecting).
        store.delete_scheduled_runs_for_user(user["id"])
        return RedirectResponse("/settings?deleted=1", status_code=303)

    @app.post("/settings/sessions/delete-all")
    async def delete_all_sessions(request: Request):
        user = require_user(request)
        store = request.app.state.store
        sessions_client = request.app.state.sessions_client
        # Delete each session's platform data first, then its local row — same ordering as the
        # single-session delete, so a session is never dropped from the list while its data
        # lives on. On a mid-way failure the already-deleted ones stay gone and the rest remain,
        # so a retry safely resumes. Stub/test mode has no platform session; the rows go alone.
        try:
            for s in store.list_sessions(user["id"]):
                if sessions_client is not None:
                    sessions_client.delete_session(s["session_id"])
                store.delete_session(s["session_id"], user["id"])
        except Exception as exc:  # noqa: BLE001 - surface session/SDK errors as a page, not a 500
            return HTMLResponse(f"Could not delete your sessions: {exc}", status_code=502)
        return RedirectResponse("/settings?sessions_deleted=1", status_code=303)

    @app.post("/settings/credential/delete")
    async def delete_credential(request: Request):
        user = require_user(request)
        form = await request.form()
        credential_id = form.get("credential_id", "")
        vault_id = request.app.state.store.get_user_vault(user["id"])
        vault_client: VaultClient | None = request.app.state.vault_client
        if vault_id and vault_client is not None and credential_id:
            try:
                vault_client.delete_credential(vault_id, credential_id)
            except Exception as exc:  # noqa: BLE001 - surface vault/SDK errors as a page, not a 500
                return HTMLResponse(f"Could not delete that credential: {exc}", status_code=502)
        return RedirectResponse("/settings", status_code=303)
