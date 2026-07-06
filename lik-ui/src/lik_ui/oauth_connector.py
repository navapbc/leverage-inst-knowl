"""Generic, discovery-driven MCP OAuth connector.

From only an MCP server URL, discover its authorization server and endpoints (RFC 9728
protected-resource metadata -> RFC 8414 / OpenID authorization-server metadata), then
obtain an OAuth client for it: via dynamic client registration (RFC 7591) when the AS
advertises a registration endpoint, or via a pre-configured client from ``sources.py``
when it does not. No per-source OAuth endpoints are hardcoded.

This module (U4) covers discovery and client acquisition. The interactive PKCE flow,
callback handling, token exchange, and vault deposit live alongside it (U5).

Nothing here logs client secrets, authorization codes, or tokens.
"""

import re

import httpx
from pydantic import BaseModel

from .db import Store
from .sources import SourceConfig, normalize_url

_RESOURCE_METADATA_RE = re.compile(r'resource_metadata="([^"]+)"')


class ConnectorError(Exception):
    """A connection could not be established (discovery failed, or no client could be
    obtained). Surfaced to the user as a failed connect; nothing is persisted."""


class Discovery(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    scopes_supported: list[str] = []


class ClientCredentials(BaseModel):
    client_id: str
    client_secret: str | None = None
    scopes: list[str] = []
    offline: bool = False


class OAuthConnector:
    def __init__(self, store: Store, source_registry: dict[str, SourceConfig], redirect_uri: str, *, client_factory=None):
        self.store = store
        self.sources = source_registry
        self.redirect_uri = redirect_uri
        # Injected so tests can supply an httpx.MockTransport-backed client.
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=10))

    # --- discovery -------------------------------------------------------------
    async def discover(self, mcp_url: str) -> Discovery:
        async with self._client_factory() as client:
            prm = await self._fetch_protected_resource_metadata(client, mcp_url)
            servers = prm.get("authorization_servers") or []
            if not servers:
                raise ConnectorError(f"No authorization_servers advertised for {mcp_url}")
            issuer = servers[0]
            meta = await self._fetch_as_metadata(client, issuer)
        try:
            return Discovery(
                issuer=meta.get("issuer", issuer),
                authorization_endpoint=meta["authorization_endpoint"],
                token_endpoint=meta["token_endpoint"],
                registration_endpoint=meta.get("registration_endpoint"),
                scopes_supported=meta.get("scopes_supported", []),
            )
        except KeyError as exc:
            raise ConnectorError(f"Authorization-server metadata missing {exc} for {issuer}") from exc

    async def _fetch_protected_resource_metadata(self, client: httpx.AsyncClient, mcp_url: str) -> dict:
        # Preferred: the 401 challenge names the metadata document directly.
        try:
            resp = await client.get(mcp_url)
            hint = _RESOURCE_METADATA_RE.search(resp.headers.get("www-authenticate", ""))
            if hint:
                return await self._get_json(client, hint.group(1))
        except httpx.HTTPError:
            pass
        # Fallback: well-known locations (RFC 9728 origin form and path-suffixed form).
        for url in self._prm_candidates(mcp_url):
            try:
                return await self._get_json(client, url)
            except httpx.HTTPError:
                continue
        raise ConnectorError(f"Could not discover protected-resource metadata for {mcp_url}")

    @staticmethod
    def _prm_candidates(mcp_url: str) -> list[str]:
        u = httpx.URL(mcp_url)
        origin = f"{u.scheme}://{u.host}" + (f":{u.port}" if u.port else "")
        path = u.path.rstrip("/")
        return [
            f"{origin}/.well-known/oauth-protected-resource{path}",
            f"{origin}/.well-known/oauth-protected-resource",
            f"{normalize_url(mcp_url)}/.well-known/oauth-protected-resource",
        ]

    async def _fetch_as_metadata(self, client: httpx.AsyncClient, issuer: str) -> dict:
        base = normalize_url(issuer)
        for url in (
            f"{base}/.well-known/oauth-authorization-server",
            f"{base}/.well-known/openid-configuration",
        ):
            try:
                return await self._get_json(client, url)
            except httpx.HTTPError:
                continue
        raise ConnectorError(f"Could not discover authorization-server metadata for {issuer}")

    @staticmethod
    async def _get_json(client: httpx.AsyncClient, url: str) -> dict:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- client acquisition ----------------------------------------------------
    async def acquire_client(self, mcp_url: str, discovery: Discovery) -> ClientCredentials:
        if discovery.registration_endpoint:
            return await self._acquire_via_dcr(discovery)
        return self._acquire_configured(mcp_url)

    async def _acquire_via_dcr(self, discovery: Discovery) -> ClientCredentials:
        offline = "offline_access" in discovery.scopes_supported
        scopes = list(discovery.scopes_supported)

        stored = self.store.get_dcr_registration(discovery.issuer)
        if stored:
            return ClientCredentials(
                client_id=stored["client_id"],
                client_secret=stored.get("client_secret"),
                scopes=scopes,
                offline=offline,
            )

        body = {
            "client_name": "lik-ui",
            "redirect_uris": [self.redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "application_type": "web",
        }
        async with self._client_factory() as client:
            resp = await client.post(discovery.registration_endpoint, json=body)
            try:
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ConnectorError(f"Dynamic client registration failed: {exc}") from exc
            reg = resp.json()

        client_id = reg.get("client_id")
        if not client_id:
            raise ConnectorError("Dynamic client registration returned no client_id")
        client_secret = reg.get("client_secret")
        self.store.put_dcr_registration(discovery.issuer, client_id, client_secret, reg)
        return ClientCredentials(client_id=client_id, client_secret=client_secret, scopes=scopes, offline=offline)

    def _acquire_configured(self, mcp_url: str) -> ClientCredentials:
        config = self.sources.get(normalize_url(mcp_url))
        if not config:
            raise ConnectorError(
                f"{mcp_url} has no dynamic client registration and no configured client. "
                "Add a source entry for it."
            )
        return ClientCredentials(
            client_id=config.client_id,
            client_secret=config.client_secret,
            scopes=config.scopes,
            offline=config.offline,
        )
