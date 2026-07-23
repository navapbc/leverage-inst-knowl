"""U1: the public-GitHub SKILL.md fetcher.

Drives the fetcher with an httpx.MockTransport-backed client (no network), asserting the
requested raw URL and the graceful-None behavior on every failure mode."""

import httpx

from lik_ui.settings import Settings
from lik_ui.skill_docs import fetch_skill_instructions, skill_source_url


def _factory(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_happy_path_returns_body_and_hits_expected_raw_url():
    settings = Settings(env="test")  # default repo/ref
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, text="# Skill\nfull instructions")

    out = await fetch_skill_instructions("lik-query-project-index", settings, _factory(handler))
    assert out == "# Skill\nfull instructions"
    assert seen["url"] == (
        "https://raw.githubusercontent.com/navapbc/leverage-inst-knowl/main"
        "/.claude/skills/lik-query-project-index/SKILL.md"
    )


async def test_non_default_repo_and_ref_reflected_in_urls():
    settings = Settings(env="test", skills_repo="acme/fork", skills_ref="dev")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, text="body")

    await fetch_skill_instructions("lik-thing", settings, _factory(handler))
    assert seen["url"] == (
        "https://raw.githubusercontent.com/acme/fork/dev/.claude/skills/lik-thing/SKILL.md"
    )
    assert skill_source_url("lik-thing", settings) == (
        "https://github.com/acme/fork/blob/dev/.claude/skills/lik-thing/SKILL.md"
    )


def test_source_url_is_pure_blob_url():
    settings = Settings(env="test")  # default repo/ref
    assert skill_source_url("lik-query-project-index", settings) == (
        "https://github.com/navapbc/leverage-inst-knowl/blob/main"
        "/.claude/skills/lik-query-project-index/SKILL.md"
    )


async def test_404_returns_none():
    settings = Settings(env="test")
    out = await fetch_skill_instructions(
        "missing", settings, _factory(lambda r: httpx.Response(404))
    )
    assert out is None


async def test_500_returns_none():
    settings = Settings(env="test")
    out = await fetch_skill_instructions(
        "boom", settings, _factory(lambda r: httpx.Response(500))
    )
    assert out is None


async def test_connect_error_does_not_propagate():
    settings = Settings(env="test")

    def handler(request):
        raise httpx.ConnectError("no route")

    assert await fetch_skill_instructions("x", settings, _factory(handler)) is None


async def test_timeout_does_not_propagate():
    settings = Settings(env="test")

    def handler(request):
        raise httpx.TimeoutException("slow")

    assert await fetch_skill_instructions("x", settings, _factory(handler)) is None
