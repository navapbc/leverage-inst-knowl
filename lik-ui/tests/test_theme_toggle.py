"""The dark-mode theme toggle lives in the shared base layout, so it renders on every
authenticated page. These tests prove the toggle markup, its position before the email,
and the no-flash bootstrap wiring — the JS behavior itself is exercised in the browser."""

from fastapi.testclient import TestClient

from tests.test_agents import LIK, FakeAgentsClient, _app, _login
from tests.test_oauth_connector import RecordingVaultClient


def _client(db):
    client = TestClient(_app(db, FakeAgentsClient([LIK]), RecordingVaultClient()), follow_redirects=False)
    _login(client)
    return client


def test_toggle_button_renders_in_topbar(db):
    r = _client(db).get("/")
    assert r.status_code == 200
    assert 'id="theme-toggle"' in r.text
    assert 'class="theme-toggle"' in r.text


def test_toggle_button_is_before_email(db):
    """R1: the toggle sits on the right of the navbar, immediately before the email address."""
    html = _client(db).get("/").text
    assert html.index('id="theme-toggle"') < html.index("topbar-email")


def test_toggle_button_has_accessible_name(db):
    html = _client(db).get("/").text
    assert 'aria-label="Toggle dark mode"' in html


def test_no_flash_bootstrap_present(db):
    """R4/R5: an inline head script applies the stored or OS-preferred theme before paint."""
    html = _client(db).get("/").text
    assert "lik-theme" in html  # storage key the bootstrap reads
    assert "prefers-color-scheme: dark" in html  # first-visit OS fallback
    assert "documentElement.dataset.theme" in html  # sets the attribute CSS keys off


def test_theme_script_is_loaded(db):
    html = _client(db).get("/").text
    assert "/static/theme.js" in html
