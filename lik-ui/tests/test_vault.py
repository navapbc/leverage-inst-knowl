"""Vault provisioning: created lazily on first login, reused thereafter, and deletable."""

from types import SimpleNamespace

from lik_ui.vault import AnthropicVaultClient, delete_user_vault, ensure_user_vault


class FakeVaultClient:
    def __init__(self):
        self.calls = 0
        self.last_metadata = None
        self.deleted = []
        self.credentials: list[dict] = []

    def create_vault(self, display_name: str, metadata: dict) -> str:
        self.calls += 1
        self.last_metadata = metadata
        return f"vlt_{self.calls}"

    def list_credentials(self, vault_id: str) -> list[dict]:
        return self.credentials

    def delete_vault(self, vault_id: str) -> None:
        self.deleted.append(vault_id)


def test_ensure_user_vault_creates_then_reuses(store):
    vc = FakeVaultClient()
    user = store.upsert_user("v@navapbc.com")

    first = ensure_user_vault(store, vc, user)
    assert first == "vlt_1"
    assert vc.calls == 1

    again = ensure_user_vault(store, vc, user)
    assert again == "vlt_1"  # reused
    assert vc.calls == 1  # no new vault created
    assert store.get_user_vault(user["id"]) == "vlt_1"


def test_vault_tagged_with_external_user_id(store):
    vc = FakeVaultClient()
    user = store.upsert_user("m@navapbc.com")
    ensure_user_vault(store, vc, user)
    assert vc.last_metadata["external_user_id"] == str(user["id"])


def test_delete_user_vault_removes_vault_and_mapping(store):
    vc = FakeVaultClient()
    user = store.upsert_user("d@navapbc.com")
    vault_id = ensure_user_vault(store, vc, user)

    assert delete_user_vault(store, vc, user) is True
    assert vc.deleted == [vault_id]
    assert store.get_user_vault(user["id"]) is None

    # A subsequent ensure provisions a brand-new vault.
    fresh = ensure_user_vault(store, vc, user)
    assert fresh != vault_id


def test_delete_user_vault_noop_when_absent(store):
    vc = FakeVaultClient()
    user = store.upsert_user("n@navapbc.com")
    assert delete_user_vault(store, vc, user) is False
    assert vc.deleted == []


class _FakeCredentialsAPI:
    """Records SDK credential calls; rejects a duplicate create per URL like the platform."""

    def __init__(self):
        self.creds = []  # each: SimpleNamespace(id, auth=SimpleNamespace(mcp_server_url))
        self._n = 0

    def list(self, *, vault_id):
        return list(self.creds)

    def delete(self, credential_id, *, vault_id):
        self.creds = [c for c in self.creds if c.id != credential_id]

    def create(self, *, vault_id, display_name, auth):
        url = auth["mcp_server_url"]
        if any(c.auth.mcp_server_url == url for c in self.creds):
            raise AssertionError(f"409: credential already exists for {url}")
        self._n += 1
        cred = SimpleNamespace(id=f"vcrd_{self._n}", auth=SimpleNamespace(mcp_server_url=url))
        self.creds.append(cred)
        return cred

    def update(self, credential_id, *, vault_id, display_name, auth):
        # The update auth carries no mcp_server_url (the URL is the immutable key), so the
        # existing credential's URL is preserved and its id is unchanged.
        cred = next(c for c in self.creds if c.id == credential_id)
        assert "mcp_server_url" not in auth
        return cred


def _vault_client_with_fake_sdk():
    client = AnthropicVaultClient(api_key="test-key")  # no network on construction
    fake_creds = _FakeCredentialsAPI()
    client._client = SimpleNamespace(beta=SimpleNamespace(vaults=SimpleNamespace(credentials=fake_creds)))
    return client, fake_creds


def _put(client, url):
    return client.put_mcp_oauth_credential(
        "vlt_1", mcp_server_url=url, access_token="at", expires_at="2099-01-01T00:00:00+00:00",
        refresh=None, display_name="lik-mcp",
    )


def test_reconnect_updates_existing_credential_for_same_url():
    """Reconnect (a second deposit for the same URL) must not 409 — it updates the credential
    in place, preserving its id."""
    client, creds = _vault_client_with_fake_sdk()
    url = "https://mcp.example.com/sse"

    first_id = _put(client, url)
    second_id = _put(client, url)  # would raise the fake's 409 if it created a duplicate

    assert first_id == second_id  # same credential, updated in place
    urls = [c.auth.mcp_server_url for c in creds.creds]
    assert urls == [url]  # exactly one credential remains for the URL


def test_reconnect_refresh_block_omits_immutable_fields():
    """On update, client_id/token_endpoint are fixed at create time and rejected by the API,
    so the reconnect refresh block must send only the mutable fields."""
    client, creds = _vault_client_with_fake_sdk()
    url = "https://mcp.example.com/sse"
    full_refresh = {
        "token_endpoint": "https://auth.example.com/token",
        "client_id": "cid-123",
        "refresh_token": "rt-1",
        "token_endpoint_auth": {"type": "none"},
        "scope": "read",
    }

    seen = {}
    orig_update = creds.update

    def spy_update(credential_id, *, vault_id, display_name, auth):
        seen["auth"] = auth
        return orig_update(credential_id, vault_id=vault_id, display_name=display_name, auth=auth)

    creds.update = spy_update

    client.put_mcp_oauth_credential(
        "vlt_1", mcp_server_url=url, access_token="at", expires_at="2099-01-01T00:00:00+00:00",
        refresh=None, display_name="lik-mcp",
    )
    client.put_mcp_oauth_credential(
        "vlt_1", mcp_server_url=url, access_token="at2", expires_at="2099-01-01T00:00:00+00:00",
        refresh=full_refresh, display_name="lik-mcp",
    )

    assert set(seen["auth"]["refresh"]) == {"refresh_token", "token_endpoint_auth", "scope"}


def test_deposit_leaves_other_urls_untouched():
    """Replacing one URL's credential must not disturb credentials for other URLs."""
    client, creds = _vault_client_with_fake_sdk()
    _put(client, "https://a.example.com/sse")
    _put(client, "https://b.example.com/sse")
    _put(client, "https://a.example.com/sse")  # reconnect A

    urls = sorted(c.auth.mcp_server_url for c in creds.creds)
    assert urls == ["https://a.example.com/sse", "https://b.example.com/sse"]
