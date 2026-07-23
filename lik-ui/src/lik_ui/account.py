"""Account settings — user-facing management of their own data.

Two actions: deleting a single credential from the vault, or deleting the whole vault.
Deleting the vault removes every source credential the user has connected; a fresh, empty
vault is provisioned the next time an agent needs it.
"""

from .vault import VaultClient, delete_user_vault


def register_account_routes(app) -> None:
    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    from .app import templates
    from .app_auth import require_user

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request, deleted: str = "", sessions_deleted: str = ""):
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
            },
        )

    @app.post("/settings/vault/delete")
    async def delete_vault(request: Request):
        user = require_user(request)
        vault_client: VaultClient | None = request.app.state.vault_client
        try:
            delete_user_vault(request.app.state.store, vault_client, user)
        except Exception as exc:  # noqa: BLE001 - surface vault/SDK errors as a page, not a 500
            return HTMLResponse(f"Could not delete your vault: {exc}", status_code=502)
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
