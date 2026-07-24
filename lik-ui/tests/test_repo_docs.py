"""U1: the generic public-GitHub repo-doc fetcher.

Drives the fetcher with an httpx.MockTransport-backed client (no network), asserting the
requested raw URL, the blob source URL, timeout passthrough, and the graceful-None behavior
on every failure mode. ``skill_docs`` is a thin wrapper over this module; its own tests
(test_skill_docs.py) prove the skill path is unchanged through the wrapper."""

import httpx

from lik_ui.repo_docs import fetch_repo_doc, raw_doc_url, repo_doc_source_url
from lik_ui.settings import Settings


def _factory(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_happy_path_returns_body_and_hits_expected_raw_url():
    settings = Settings(env="test")  # default repo/ref
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, text="# FAQ\nbody")

    out = await fetch_repo_doc("faq.md", settings, _factory(handler))
    assert out == "# FAQ\nbody"
    assert seen["url"] == "https://raw.githubusercontent.com/navapbc/leverage-inst-knowl/main/faq.md"


async def test_non_default_repo_and_ref_reflected_in_urls():
    settings = Settings(env="test", skills_repo="acme/fork", skills_ref="dev")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, text="body")

    await fetch_repo_doc("docs/x.md", settings, _factory(handler))
    assert seen["url"] == "https://raw.githubusercontent.com/acme/fork/dev/docs/x.md"


def test_raw_and_source_urls_are_pure():
    settings = Settings(env="test")  # default repo/ref
    assert raw_doc_url("faq.md", settings) == (
        "https://raw.githubusercontent.com/navapbc/leverage-inst-knowl/main/faq.md"
    )
    assert repo_doc_source_url("faq.md", settings) == (
        "https://github.com/navapbc/leverage-inst-knowl/blob/main/faq.md"
    )


async def test_custom_timeout_is_passed_to_default_client(monkeypatch):
    """The FAQ page fetch passes a shorter timeout than the default; verify it reaches the
    client the default factory builds."""
    settings = Settings(env="test")
    captured = {}
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    out = await fetch_repo_doc("faq.md", settings, timeout=3)
    assert out == "ok"
    assert captured["timeout"] == 3


async def test_404_returns_none():
    settings = Settings(env="test")
    out = await fetch_repo_doc("missing.md", settings, _factory(lambda r: httpx.Response(404)))
    assert out is None


async def test_500_returns_none():
    settings = Settings(env="test")
    out = await fetch_repo_doc("boom.md", settings, _factory(lambda r: httpx.Response(500)))
    assert out is None


async def test_connect_error_does_not_propagate():
    settings = Settings(env="test")

    def handler(request):
        raise httpx.ConnectError("no route")

    assert await fetch_repo_doc("x.md", settings, _factory(handler)) is None


async def test_timeout_does_not_propagate():
    settings = Settings(env="test")

    def handler(request):
        raise httpx.TimeoutException("slow")

    assert await fetch_repo_doc("x.md", settings, _factory(handler)) is None
