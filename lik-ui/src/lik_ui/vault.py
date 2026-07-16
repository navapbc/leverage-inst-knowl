"""Credential-vault provisioning. Each user gets one Anthropic credential vault, created
lazily on first login and remembered via the user->vault mapping in the store.

The vault holds the per-source MCP credentials the user connects (deposited by the OAuth
connector). Here we only create/lookup the vault itself. The concrete Anthropic call is
behind the ``VaultClient`` protocol so tests can substitute a fake without network access.
"""

from typing import Protocol

from .db import Store
from .settings import Settings


class VaultClient(Protocol):
    def create_vault(self, display_name: str, metadata: dict) -> str:
        """Create a vault and return its id (e.g. ``vlt_01ABC...``)."""
        ...

    def put_mcp_oauth_credential(
        self,
        vault_id: str,
        *,
        mcp_server_url: str,
        access_token: str,
        expires_at: str,
        refresh: dict | None,
        display_name: str,
    ) -> str:
        """Create/replace an mcp_oauth credential in the vault, keyed by mcp_server_url.
        Returns the credential id."""
        ...

    def list_credential_urls(self, vault_id: str) -> set[str]:
        """Return the set of mcp_server_urls the vault currently holds credentials for."""
        ...

    def list_credentials(self, vault_id: str) -> list[dict]:
        """Return the vault's credentials as ``{"id", "display_name", "url"}`` dicts (no secrets)."""
        ...

    def delete_credential(self, vault_id: str, credential_id: str) -> None:
        """Delete a single credential from the vault, leaving the vault and its other
        credentials intact."""
        ...

    def delete_vault(self, vault_id: str) -> None:
        """Delete the vault and all credentials it holds."""
        ...


class AnthropicVaultClient:
    """Real ``VaultClient`` backed by the Anthropic SDK's Managed Agents vault API."""

    def __init__(self, api_key: str):
        import anthropic  # imported lazily so test/stub paths need no SDK/network

        self._client = anthropic.Anthropic(api_key=api_key)

    def create_vault(self, display_name: str, metadata: dict) -> str:
        vault = self._client.beta.vaults.create(display_name=display_name, metadata=metadata)
        return vault.id

    def put_mcp_oauth_credential(
        self,
        vault_id: str,
        *,
        mcp_server_url: str,
        access_token: str,
        expires_at: str,
        refresh: dict | None,
        display_name: str,
    ) -> str:
        # The platform allows only one credential per MCP server URL and rejects a duplicate
        # create with 409. On reconnect the user has just obtained a fresh token, so update the
        # existing credential in place (keeping its id, no absence window) rather than replacing
        # it; only mint a new one when none exists yet for this exact URL.
        existing_id = self._find_credential_id(vault_id, mcp_server_url)
        if existing_id:
            # The URL is the credential's immutable key, so it is omitted from the update auth.
            auth: dict = {"type": "mcp_oauth", "access_token": access_token, "expires_at": expires_at}
            if refresh:
                # client_id and token_endpoint are fixed at create time; the update endpoint
                # rejects them, so send only the mutable fields of the refresh block.
                auth["refresh"] = {
                    k: v for k, v in refresh.items() if k not in ("client_id", "token_endpoint")
                }
            credential = self._client.beta.vaults.credentials.update(
                existing_id, vault_id=vault_id, display_name=display_name, auth=auth
            )
        else:
            auth = {
                "type": "mcp_oauth",
                "mcp_server_url": mcp_server_url,
                "access_token": access_token,
                "expires_at": expires_at,
            }
            if refresh:
                auth["refresh"] = refresh
            credential = self._client.beta.vaults.credentials.create(
                vault_id=vault_id, display_name=display_name, auth=auth
            )
        return credential.id

    def _find_credential_id(self, vault_id: str, mcp_server_url: str) -> str | None:
        """Return the id of the credential (if any) already keyed to this MCP server URL.
        Compare on the normalized URL: the platform stores the URL with a trailing slash
        stripped, so a slash-terminated declared URL (e.g. GitHub's ``.../mcp/``) would miss
        its stored form under raw equality — and the ensuing create would 409 on the duplicate."""
        from .sources import normalize_url

        target = normalize_url(mcp_server_url)
        for cred in self._client.beta.vaults.credentials.list(vault_id=vault_id):
            url = getattr(getattr(cred, "auth", None), "mcp_server_url", None)
            if url and normalize_url(url) == target:
                return cred.id
        return None

    def list_credential_urls(self, vault_id: str) -> set[str]:
        urls: set[str] = set()
        for cred in self._client.beta.vaults.credentials.list(vault_id=vault_id):
            url = getattr(getattr(cred, "auth", None), "mcp_server_url", None)
            if url:
                urls.add(url)
        return urls

    def list_credentials(self, vault_id: str) -> list[dict]:
        creds = []
        for cred in self._client.beta.vaults.credentials.list(vault_id=vault_id):
            url = getattr(getattr(cred, "auth", None), "mcp_server_url", None)
            creds.append({"id": cred.id, "display_name": getattr(cred, "display_name", None), "url": url})
        return creds

    def delete_credential(self, vault_id: str, credential_id: str) -> None:
        self._client.beta.vaults.credentials.delete(credential_id, vault_id=vault_id)

    def delete_vault(self, vault_id: str) -> None:
        self._client.beta.vaults.delete(vault_id)


def build_vault_client(settings: Settings) -> VaultClient | None:
    """Real client outside local/test; ``None`` in stub mode (no vault calls made)."""
    if settings.is_stub:
        return None
    return AnthropicVaultClient(settings.anthropic_api_key)


def ensure_user_vault(store: Store, vault_client: VaultClient, user: dict) -> str:
    """Return the user's vault id, creating the vault on first use.

    Idempotent: once the mapping exists, no new vault is created on later logins. The
    vault is tagged with ``external_user_id`` so it can be traced back to the app user.
    """
    existing = store.get_user_vault(user["id"])
    if existing:
        return existing
    vault_id = vault_client.create_vault(
        display_name=f"lik-{user['email']}",
        metadata={"external_user_id": str(user["id"])},
    )
    store.set_user_vault(user["id"], vault_id)
    return vault_id


def delete_user_vault(store: Store, vault_client: VaultClient | None, user: dict) -> bool:
    """Delete the user's vault (and every credential in it) and forget the mapping, so a
    fresh vault is provisioned on next use. Returns False if the user had no vault.

    Idempotent: safe to call when no vault exists. The mapping is cleared only after the
    vault is deleted, so a failed delete leaves the mapping intact to retry.
    """
    vault_id = store.get_user_vault(user["id"])
    if not vault_id:
        return False
    if vault_client is not None:
        vault_client.delete_vault(vault_id)
    store.delete_user_vault(user["id"])
    return True
