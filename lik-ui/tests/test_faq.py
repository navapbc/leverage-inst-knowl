"""U4: the /faq page — route, render carrier, degradation, and auth gate.

The bundled-file read is monkeypatched, so these prove the handler wiring and template
behavior; the real faq.md content is validated offline in test_faq_content.py."""

from fastapi.testclient import TestClient

from tests.test_agents import LIK, FakeAgentsClient, _app, _login
from tests.test_oauth_connector import RecordingVaultClient


def _client(db, monkeypatch, faq_result):
    def fake_load(settings):
        return faq_result

    monkeypatch.setattr("lik_ui.faq.load_faq", fake_load)
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


# --- load_faq: the local (no-network) read path -------------------------------------------------


def test_load_faq_reads_bundled_file(tmp_path):
    from lik_ui.faq import load_faq
    from lik_ui.settings import Settings

    f = tmp_path / "faq.md"
    f.write_text("# FAQ\n\nbundled body")
    assert load_faq(Settings(env="test", faq_path=f)) == "# FAQ\n\nbundled body"


def test_load_faq_returns_none_when_missing(tmp_path):
    from lik_ui.faq import load_faq
    from lik_ui.settings import Settings

    assert load_faq(Settings(env="test", faq_path=tmp_path / "nope.md")) is None


def test_load_faq_treats_empty_body_as_none(tmp_path):
    from lik_ui.faq import load_faq
    from lik_ui.settings import Settings

    f = tmp_path / "faq.md"
    f.write_text("   \n  ")
    assert load_faq(Settings(env="test", faq_path=f)) is None


def test_default_faq_path_points_at_bundled_file():
    """The packaged default resolves to a real file, so a fresh install serves the FAQ."""
    from lik_ui.settings import Settings

    assert Settings(env="test").faq_path.is_file()
