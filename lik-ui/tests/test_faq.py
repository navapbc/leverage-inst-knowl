"""U4: the /faq page — route, render carrier, degradation, and auth gate.

The live fetch is monkeypatched (mirrors the skill-details tests), so these prove the handler
wiring and template behavior; the real faq.md content is validated offline in test_faq_content.py."""

from fastapi.testclient import TestClient

from tests.test_agents import LIK, FakeAgentsClient, _app, _login
from tests.test_oauth_connector import RecordingVaultClient


def _client(db, monkeypatch, fetch_result):
    async def fake_fetch(path, settings, client_factory=None, **kwargs):
        assert path == "faq.md"
        return fetch_result

    monkeypatch.setattr("lik_ui.faq.fetch_repo_doc", fake_fetch)
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    return client


def test_faq_page_renders_and_embeds_content(db, monkeypatch):
    client = _client(db, monkeypatch, "# FAQ\n\nHello **world**")
    r = client.get("/faq")
    assert r.status_code == 200
    assert 'id="faq-raw"' in r.text  # the render carrier is present
    assert "# FAQ" in r.text  # the fetched body is embedded for client-side render
    assert "view on GitHub" in r.text  # source link shown alongside the rendered content


def test_faq_page_shows_nav_link(db, monkeypatch):
    """The FAQ nav link renders on the page, which also proves `user` reached the template
    context (the whole {% if user %} header depends on it)."""
    client = _client(db, monkeypatch, "# FAQ")
    r = client.get("/faq")
    assert '<a href="/faq">FAQ</a>' in r.text


def test_faq_page_degrades_when_fetch_returns_none(db, monkeypatch):
    client = _client(db, monkeypatch, None)
    r = client.get("/faq")
    assert r.status_code == 200
    assert "view it on GitHub" in r.text  # fallback line, not an error page
    assert 'id="faq-raw"' not in r.text  # no render carrier when there's nothing to render


def test_faq_page_treats_empty_body_like_none(db, monkeypatch):
    client = _client(db, monkeypatch, "   \n  ")
    r = client.get("/faq")
    assert r.status_code == 200
    assert "view it on GitHub" in r.text


def test_faq_page_escapes_adversarial_content(db, monkeypatch):
    """Content is carried in a <template> and HTML-escaped by Jinja, so a literal </script> or
    an injected tag cannot break out or execute before DOMPurify runs."""
    payload = 'quotes "x" and \\ and </script><img src=x onerror=alert(1)> end'
    client = _client(db, monkeypatch, payload)
    r = client.get("/faq")
    assert r.status_code == 200
    assert "</script><img src=x onerror=alert(1)>" not in r.text  # never emitted raw
    assert "&lt;/script&gt;" in r.text  # escaped instead


def test_faq_requires_login(db):
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    r = client.get("/faq")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
