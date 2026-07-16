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

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel

from .sources import SourceConfig, normalize_url

_RESOURCE_METADATA_RE = re.compile(r'resource_metadata="([^"]+)"')


class ConnectorError(Exception):
    """A connection could not be established (discovery failed, or no client could be
    obtained). Surfaced to the user as a failed connect; nothing is persisted."""


def register_connection_routes(app) -> None:
    """Mount the per-source connect + OAuth callback routes."""
    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    from .app_auth import require_user
    from .vault import ensure_user_vault

    @app.get("/connections/connect")
    async def connect(request: Request, mcp_url: str, agent_id: str = "", label: str = ""):
        require_user(request)
        connector: OAuthConnector = request.app.state.connector
        try:
            discovery = await connector.discover(mcp_url)
            creds = await connector.acquire_client(mcp_url, discovery)
        except ConnectorError as exc:
            return HTMLResponse(f"Could not start connection: {exc}", status_code=502)

        state = secrets.token_urlsafe(32)
        verifier, challenge = connector.make_pkce()
        # Stash the discovered endpoints (no secrets) so the callback need not re-discover.
        # ClientCredentials are NOT stashed — they carry a client secret and the session
        # cookie is signed, not encrypted; the callback re-acquires them cheaply (DB/local).
        request.session["oauth_connect"] = {
            "state": state,
            "verifier": verifier,
            "mcp_url": mcp_url,
            "issuer": discovery.issuer,
            "label": label or mcp_url,
            "agent_id": agent_id,
            "discovery": discovery.model_dump(),
        }
        return RedirectResponse(
            connector.authorization_url(discovery, creds, state, challenge, mcp_url), status_code=303
        )

    @app.get("/connections/callback")
    async def connect_callback(request: Request, code: str = "", state: str = "", iss: str = ""):
        user = require_user(request)
        pending = request.session.get("oauth_connect") or {}
        if not state or state != pending.get("state"):
            return HTMLResponse("Connection state mismatch. Please try again.", status_code=400)
        # RFC 9207: if the AS returned an issuer, it must match the one we discovered.
        if iss and iss != pending.get("issuer"):
            return HTMLResponse("Authorization issuer mismatch.", status_code=400)

        mcp_url = pending["mcp_url"]
        connector: OAuthConnector = request.app.state.connector
        # Reuse the endpoints discovered at connect time; re-acquire the client (cheap) and
        # deposit. Guard the whole exchange+deposit so a malformed token response or a
        # misconfigured (e.g. missing) vault client surfaces as a clean failure, not a 500.
        try:
            discovery = Discovery(**pending["discovery"])
            creds = await connector.acquire_client(mcp_url, discovery)
            tokens = await connector.exchange_code(discovery, creds, code, pending["verifier"], mcp_url)
            vault_id = ensure_user_vault(request.app.state.store, request.app.state.vault_client, user)
            connector.deposit(
                request.app.state.vault_client, vault_id, mcp_url, discovery, creds, tokens, pending["label"]
            )
        except (ConnectorError, KeyError, ValueError, TypeError, AttributeError) as exc:
            return HTMLResponse(f"Connection failed: {exc}", status_code=502)

        request.session.pop("oauth_connect", None)
        agent_id = pending.get("agent_id")
        return RedirectResponse(f"/connections?agent_id={agent_id}" if agent_id else "/", status_code=303)


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
    def __init__(self, source_registry: dict[str, SourceConfig], redirect_uri: str, *, client_factory=None):
        self.sources = source_registry
        self.redirect_uri = redirect_uri
        # Injected so tests can supply an httpx.MockTransport-backed client.
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=10))

    # --- discovery -------------------------------------------------------------
    async def discover(self, mcp_url: str) -> Discovery:
        async with self._client_factory() as client:
            issuer = await self._discover_issuer(client, mcp_url)
            if issuer:
                # Standard RFC 9728 path: protected-resource metadata named an AS.
                meta = await self._fetch_as_metadata(client, issuer)
            else:
                # Fallback: no protected-resource metadata (e.g. Atlassian). Many MCP
                # servers co-locate their authorization server, serving AS metadata at
                # their own origin's well-known path.
                meta = await self._fetch_as_metadata(client, self._origin(mcp_url))
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

    async def _discover_issuer(self, client: httpx.AsyncClient, mcp_url: str) -> str | None:
        """Return the first authorization server from RFC 9728 protected-resource metadata,
        or None if the server exposes no PRM (then the caller falls back to the origin)."""
        prm = await self._try_prm(client, mcp_url)
        servers = (prm or {}).get("authorization_servers") or []
        return servers[0] if servers else None

    async def _try_prm(self, client: httpx.AsyncClient, mcp_url: str) -> dict | None:
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
        return None

    @staticmethod
    def _origin(url: str) -> str:
        u = httpx.URL(url)
        return f"{u.scheme}://{u.host}" + (f":{u.port}" if u.port else "")

    @staticmethod
    def _prm_candidates(mcp_url: str) -> list[str]:
        u = httpx.URL(mcp_url)
        origin = f"{u.scheme}://{u.host}" + (f":{u.port}" if u.port else "")
        path = u.path.rstrip("/")
        candidates = [
            f"{origin}/.well-known/oauth-protected-resource{path}",
            f"{origin}/.well-known/oauth-protected-resource",
            f"{normalize_url(mcp_url)}/.well-known/oauth-protected-resource",
        ]
        # De-duplicate (empty/trailing-slash paths make several of these coincide) while
        # preserving order, so fallback discovery doesn't re-fetch the same URL.
        return list(dict.fromkeys(candidates))

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
        # Register a fresh client on every connect rather than caching it. Some
        # authorization servers silently expire or purge dynamically-registered clients
        # (Atlassian does, despite advertising no expiry), and a cached-but-dead client_id
        # is only rejected at the browser authorization step — which the server never sees,
        # so it can't self-heal. Registering per connect sidesteps that trap; the cost is
        # one extra registration call and some orphaned client records on the AS side.
        offline = "offline_access" in discovery.scopes_supported
        scopes = list(discovery.scopes_supported)

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

    # --- PKCE authorization-code flow ------------------------------------------
    @staticmethod
    def make_pkce() -> tuple[str, str]:
        """Return (code_verifier, code_challenge) for the S256 PKCE method."""
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return verifier, challenge

    def _scope_string(self, creds: ClientCredentials, discovery: Discovery) -> str:
        scopes = list(creds.scopes)
        # `offline_access` is the standard OAuth 2.1 scope for a refresh token, but only
        # some authorization servers accept it (Google rejects it and uses access_type
        # instead). Add it only when the AS advertises it in scopes_supported.
        if creds.offline and "offline_access" in (discovery.scopes_supported or []) and "offline_access" not in scopes:
            scopes.append("offline_access")
        return " ".join(scopes)

    def authorization_url(
        self, discovery: Discovery, creds: ClientCredentials, state: str, code_challenge: str, mcp_url: str
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": creds.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": self._scope_string(creds, discovery),
            # RFC 8707: bind the token to this specific MCP server.
            "resource": mcp_url,
        }
        if creds.offline:
            # Google needs these to return a refresh token; providers that use the
            # offline_access scope instead ignore them. Per-provider offline handling is
            # a live-integration detail flagged in the plan's deferred questions.
            params["access_type"] = "offline"
            params["prompt"] = "consent"
        return str(httpx.URL(discovery.authorization_endpoint, params=params))

    async def exchange_code(
        self, discovery: Discovery, creds: ClientCredentials, code: str, code_verifier: str, mcp_url: str
    ) -> dict:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
            "client_id": creds.client_id,
            "resource": mcp_url,
        }
        if creds.client_secret:  # client_secret_post
            data["client_secret"] = creds.client_secret
        # RFC 6749 token responses are JSON, but GitHub's token endpoint defaults to
        # form-encoding and only returns JSON when asked; compliant servers ignore this.
        headers = {"Accept": "application/json"}
        async with self._client_factory() as client:
            resp = await client.post(discovery.token_endpoint, data=data, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ConnectorError(f"Token exchange failed: {exc}") from exc
            try:
                return resp.json()
            except ValueError as exc:
                raise ConnectorError(f"Token endpoint returned a non-JSON response: {exc}") from exc

    def _refresh_block(self, discovery: Discovery, creds: ClientCredentials, token_response: dict) -> dict | None:
        refresh_token = token_response.get("refresh_token")
        if not refresh_token:
            return None  # platform can't refresh; user must reconnect when the token expires
        auth = (
            {"type": "client_secret_post", "client_secret": creds.client_secret}
            if creds.client_secret
            else {"type": "none"}
        )
        block = {
            "token_endpoint": discovery.token_endpoint,
            "client_id": creds.client_id,
            "refresh_token": refresh_token,
            "token_endpoint_auth": auth,
        }
        # scope is optional on refresh; include it only when non-empty (the platform
        # rejects an empty string). Prefer the granted scope from the token response.
        scope = (token_response.get("scope") or "").strip() or self._scope_string(creds, discovery)
        if scope:
            block["scope"] = scope
        return block

    @staticmethod
    def _expires_at(token_response: dict) -> str:
        expires_in = int(token_response.get("expires_in") or 3600)
        return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    def deposit(
        self,
        vault_client,
        vault_id: str,
        mcp_url: str,
        discovery: Discovery,
        creds: ClientCredentials,
        token_response: dict,
        display_name: str,
    ) -> str:
        """Store the obtained tokens as an mcp_oauth credential keyed by the exact MCP URL,
        including a refresh block so the platform can refresh. Returns the credential id."""
        # Key by the exact URL the agent declares — the platform matches credentials to
        # servers by exact URL, so normalizing here would break injection (R8).
        return vault_client.put_mcp_oauth_credential(
            vault_id,
            mcp_server_url=mcp_url,
            access_token=token_response["access_token"],
            expires_at=self._expires_at(token_response),
            refresh=self._refresh_block(discovery, creds, token_response),
            display_name=display_name,
        )
