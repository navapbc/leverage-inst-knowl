"""Integration: the connect + OAuth callback routes drive discovery, token exchange, and
vault deposit end to end. Google (app login) and the source AS are both faked."""

from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.db import Store
from lik_ui.oauth_connector import OAuthConnector
from lik_ui.settings import Settings
from tests.test_app_auth import FakeOidc, _start_login_and_get_state
from tests.test_oauth_connector import ISSUER, MCP_URL, REDIRECT, RecordingVaultClient, build_handler


def _app(db, vc):
    handler, _ = build_handler(registration=True)
    connector = OAuthConnector(
        {}, REDIRECT,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    oidc = FakeOidc({"email": "alice@navapbc.com", "email_verified": True})
    app = build_app(Settings(env="test"), store=Store(db), app_oidc=oidc, vault_client=vc, connector=connector)
    return app


def _login(client):
    state = _start_login_and_get_state(client)
    client.get(f"/auth/callback?code=x&state={state}")


def test_connect_flow_deposits_credential(db):
    vc = RecordingVaultClient()
    client = TestClient(_app(db, vc), follow_redirects=False)
    _login(client)

    r = client.get(f"/connections/connect?mcp_url={MCP_URL}&agent_id=agent_1&label=lik-mcp")
    assert r.status_code == 303
    auth_url = r.headers["location"]
    assert "code_challenge" in auth_url and "resource" in auth_url
    state = parse_qs(urlsplit(auth_url).query)["state"][0]

    r2 = client.get(f"/connections/callback?code=abc&state={state}&iss={ISSUER}")
    assert r2.status_code == 303
    assert r2.headers["location"] == "/connections?agent_id=agent_1"  # agent_id carried through

    assert len(vc.credentials) == 1
    cred = vc.credentials[0]
    assert cred["mcp_server_url"] == MCP_URL
    assert cred["refresh"]["refresh_token"] == "rt-xyz"


def test_callback_rejects_state_mismatch(db):
    vc = RecordingVaultClient()
    client = TestClient(_app(db, vc), follow_redirects=False)
    _login(client)
    client.get(f"/connections/connect?mcp_url={MCP_URL}&label=lik-mcp")

    r = client.get("/connections/callback?code=abc&state=forged")
    assert r.status_code == 400
    assert vc.credentials == []  # nothing deposited


def test_callback_rejects_issuer_mismatch(db):
    vc = RecordingVaultClient()
    client = TestClient(_app(db, vc), follow_redirects=False)
    _login(client)
    r = client.get(f"/connections/connect?mcp_url={MCP_URL}&label=lik-mcp")
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]

    r2 = client.get(f"/connections/callback?code=abc&state={state}&iss=https://evil.example")
    assert r2.status_code == 400
    assert vc.credentials == []


def test_connect_requires_login(db):
    vc = RecordingVaultClient()
    client = TestClient(_app(db, vc), follow_redirects=False)
    r = client.get(f"/connections/connect?mcp_url={MCP_URL}")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
