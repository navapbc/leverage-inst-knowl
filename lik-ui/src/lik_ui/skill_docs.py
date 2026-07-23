"""Fetch a skill's full ``SKILL.md`` from the public GitHub repo.

The repo (see ``Settings.skills_repo``) is public, so the file is read with a plain
unauthenticated GET of GitHub's raw content — no token, no OAuth. A skill is addressed by
its *name*, which the deploy pipeline guarantees equals the skill's directory, so the path
is always ``.claude/skills/<name>/SKILL.md``.

The fetch degrades gracefully: any failure (404, non-200, timeout, network error) returns
``None`` rather than raising, so callers can fall back to a "view on GitHub" link without the
page or endpoint erroring. ``skill_source_url`` builds that human-facing link with no network.
"""

import httpx

from .settings import Settings


def _raw_url(name: str, settings: Settings) -> str:
    return (
        f"https://raw.githubusercontent.com/{settings.skills_repo}/{settings.skills_ref}"
        f"/.claude/skills/{name}/SKILL.md"
    )


def skill_source_url(name: str, settings: Settings) -> str:
    """The human-facing GitHub *blob* URL for a skill's ``SKILL.md`` (pure, no network).

    Rendered in a browser for anyone when the repo is public, and for authorized users if
    it later goes private. Used as the "view on GitHub" affordance and the fallback link."""
    return (
        f"https://github.com/{settings.skills_repo}/blob/{settings.skills_ref}"
        f"/.claude/skills/{name}/SKILL.md"
    )


async def fetch_skill_instructions(name: str, settings: Settings, client_factory=None) -> str | None:
    """Return a skill's ``SKILL.md`` text from the public repo, or ``None`` on any failure.

    Never raises: transport/timeout errors and non-200 responses both yield ``None`` so the
    caller degrades to a fallback. ``client_factory`` is injectable so tests can supply an
    ``httpx.MockTransport``-backed client (mirrors ``oauth_connector.py``)."""
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=10))
    try:
        async with factory() as client:
            resp = await client.get(_raw_url(name, settings))
    except httpx.HTTPError:
        return None
    return resp.text if resp.status_code == 200 else None
