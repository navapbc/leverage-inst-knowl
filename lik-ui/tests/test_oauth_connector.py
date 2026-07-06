"""Discovery + client-acquisition tests. The AS/MCP endpoints are simulated with
httpx.MockTransport so the real parsing/DCR logic runs without network."""

import httpx
import pytest

from lik_ui.oauth_connector import ConnectorError, OAuthConnector
from lik_ui.sources import SourceConfig

MCP_URL = "https://mcp.example.com/mcp"
ISSUER = "https://as.example.com"
AS_META_URL = f"{ISSUER}/.well-known/oauth-authorization-server"
REG_ENDPOINT = f"{ISSUER}/register"
PRM_HINT_URL = "https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
PRM_WELLKNOWN_URL = "https://mcp.example.com/.well-known/oauth-protected-resource"

REDIRECT = "https://app.example.com/connections/callback"


def _as_meta(*, registration: bool):
    meta = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "scopes_supported": ["openid", "email", "offline_access"],
    }
    if registration:
        meta["registration_endpoint"] = REG_ENDPOINT
    return meta


def build_handler(*, www_auth_hint=True, registration=True, mcp_status=401, calls=None):
    calls = calls if calls is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        url, method = str(request.url), request.method
        calls[(method, url)] = calls.get((method, url), 0) + 1
        if url == MCP_URL and method == "GET":
            headers = {}
            if www_auth_hint:
                headers["www-authenticate"] = f'Bearer resource_metadata="{PRM_HINT_URL}"'
            return httpx.Response(mcp_status, headers=headers)
        if url in (PRM_HINT_URL, PRM_WELLKNOWN_URL):
            return httpx.Response(200, json={"resource": MCP_URL, "authorization_servers": [ISSUER]})
        if url == AS_META_URL:
            return httpx.Response(200, json=_as_meta(registration=registration))
        if url == REG_ENDPOINT and method == "POST":
            return httpx.Response(200, json={"client_id": "dyn_client", "client_secret": "dyn_secret"})
        if url == f"{ISSUER}/token" and method == "POST":
            return httpx.Response(
                200,
                json={"access_token": "at-xyz", "refresh_token": "rt-xyz", "expires_in": 3600, "scope": "openid email"},
            )
        return httpx.Response(404)

    return handler, calls


def _connector(store, handler, registry=None):
    factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    return OAuthConnector(store, registry or {}, REDIRECT, client_factory=factory)


async def test_discover_via_www_authenticate_hint(store):
    handler, _ = build_handler()
    conn = _connector(store, handler)
    d = await conn.discover(MCP_URL)
    assert d.issuer == ISSUER
    assert d.authorization_endpoint == f"{ISSUER}/authorize"
    assert d.token_endpoint == f"{ISSUER}/token"
    assert d.registration_endpoint == REG_ENDPOINT


async def test_discover_falls_back_to_wellknown_prm(store):
    # No resource_metadata hint on the 401 -> connector tries the well-known PRM paths.
    handler, calls = build_handler(www_auth_hint=False)
    conn = _connector(store, handler)
    d = await conn.discover(MCP_URL)
    assert d.token_endpoint == f"{ISSUER}/token"
    assert calls.get(("GET", PRM_HINT_URL), 0) >= 1  # path-suffixed well-known was tried


async def test_discover_raises_when_metadata_unreachable(store):
    handler, _ = build_handler(www_auth_hint=False, mcp_status=404)

    def only_404(request):  # nothing resolves
        return httpx.Response(404)

    conn = _connector(store, only_404)
    with pytest.raises(ConnectorError):
        await conn.discover(MCP_URL)


async def test_acquire_via_dcr_registers_then_reuses(store):
    handler, calls = build_handler(registration=True)
    conn = _connector(store, handler)
    d = await conn.discover(MCP_URL)

    creds = await conn.acquire_client(MCP_URL, d)
    assert creds.client_id == "dyn_client"
    assert creds.client_secret == "dyn_secret"
    assert creds.offline is True  # offline_access advertised
    assert calls[("POST", REG_ENDPOINT)] == 1
    assert store.get_dcr_registration(ISSUER)["client_id"] == "dyn_client"

    # Second acquisition reuses the stored registration — no second POST.
    creds2 = await conn.acquire_client(MCP_URL, d)
    assert creds2.client_id == "dyn_client"
    assert calls[("POST", REG_ENDPOINT)] == 1


async def test_acquire_configured_when_no_dcr(store):
    handler, calls = build_handler(registration=False)
    registry = {MCP_URL: SourceConfig(client_id="preconf", client_secret="s", scopes=["openid", "email"], offline=True)}
    conn = _connector(store, handler, registry=registry)
    d = await conn.discover(MCP_URL)
    assert d.registration_endpoint is None

    creds = await conn.acquire_client(MCP_URL, d)
    assert creds.client_id == "preconf"
    assert ("POST", REG_ENDPOINT) not in calls  # no DCR attempted


async def test_acquire_raises_when_no_dcr_and_no_config(store):
    handler, _ = build_handler(registration=False)
    conn = _connector(store, handler, registry={})
    d = await conn.discover(MCP_URL)
    with pytest.raises(ConnectorError):
        await conn.acquire_client(MCP_URL, d)


# --- U5: PKCE flow, token exchange, deposit --------------------------------------

from lik_ui.oauth_connector import ClientCredentials, Discovery  # noqa: E402

_DISCOVERY = Discovery(
    issuer=ISSUER,
    authorization_endpoint=f"{ISSUER}/authorize",
    token_endpoint=f"{ISSUER}/token",
    scopes_supported=["openid", "email", "offline_access"],
)
_CREDS = ClientCredentials(client_id="cid", client_secret="csecret", scopes=["openid", "email"], offline=True)


def test_make_pkce_challenge_is_s256_of_verifier():
    import base64
    import hashlib

    conn = OAuthConnector(None, {}, REDIRECT)
    verifier, challenge = conn.make_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected


def test_authorization_url_carries_pkce_resource_and_offline():
    from urllib.parse import parse_qs, urlsplit

    conn = OAuthConnector(None, {}, REDIRECT)
    url = conn.authorization_url(_DISCOVERY, _CREDS, state="st", code_challenge="ch", mcp_url=MCP_URL)
    q = parse_qs(urlsplit(url).query)
    assert q["code_challenge"] == ["ch"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["resource"] == [MCP_URL]
    assert q["state"] == ["st"]
    assert "offline_access" in q["scope"][0]
    assert q["access_type"] == ["offline"]  # Google path for a refresh token


def test_authorization_url_omits_offline_access_when_as_lacks_it():
    # Google-style AS: no offline_access in scopes_supported -> don't request it (Google
    # rejects the scope), but still send access_type=offline for the refresh token.
    from urllib.parse import parse_qs, urlsplit

    google_like = Discovery(
        issuer=ISSUER,
        authorization_endpoint=f"{ISSUER}/authorize",
        token_endpoint=f"{ISSUER}/token",
        scopes_supported=["openid", "email", "profile"],  # no offline_access
    )
    conn = OAuthConnector(None, {}, REDIRECT)
    url = conn.authorization_url(google_like, _CREDS, state="st", code_challenge="ch", mcp_url=MCP_URL)
    q = parse_qs(urlsplit(url).query)
    assert "offline_access" not in q["scope"][0]
    assert q["access_type"] == ["offline"]


async def test_exchange_code_posts_and_returns_tokens(store):
    handler, calls = build_handler()
    conn = _connector(store, handler)
    tokens = await conn.exchange_code(_DISCOVERY, _CREDS, "the-code", "the-verifier", MCP_URL)
    assert tokens["access_token"] == "at-xyz"
    assert calls[("POST", f"{ISSUER}/token")] == 1


def test_refresh_block_omitted_without_refresh_token():
    conn = OAuthConnector(None, {}, REDIRECT)
    assert conn._refresh_block(_DISCOVERY, _CREDS, {"access_token": "at"}) is None
    block = conn._refresh_block(_DISCOVERY, _CREDS, {"access_token": "at", "refresh_token": "rt"})
    assert block["refresh_token"] == "rt"
    assert block["token_endpoint"] == f"{ISSUER}/token"
    assert block["token_endpoint_auth"]["client_secret"] == "csecret"


class RecordingVaultClient:
    def __init__(self):
        self.vault_calls = 0
        self.credentials = []

    def create_vault(self, display_name, metadata):
        self.vault_calls += 1
        return "vlt_1"

    def put_mcp_oauth_credential(self, vault_id, *, mcp_server_url, access_token, expires_at, refresh, display_name):
        self.credentials.append(
            {"vault_id": vault_id, "mcp_server_url": mcp_server_url, "access_token": access_token, "refresh": refresh}
        )
        return "vcrd_1"

    def list_credential_urls(self, vault_id) -> set[str]:
        return {c["mcp_server_url"] for c in self.credentials}


def test_deposit_keys_credential_by_exact_url_with_refresh_block(store):
    conn = OAuthConnector(store, {}, REDIRECT)
    vc = RecordingVaultClient()
    conn.deposit(
        vc, "vlt_9", MCP_URL, _DISCOVERY, _CREDS,
        {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}, "lik-mcp",
    )
    assert len(vc.credentials) == 1
    cred = vc.credentials[0]
    assert cred["mcp_server_url"] == MCP_URL  # exact, not normalized
    assert cred["refresh"]["refresh_token"] == "rt"
