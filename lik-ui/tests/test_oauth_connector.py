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
