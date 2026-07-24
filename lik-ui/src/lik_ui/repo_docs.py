"""Fetch an arbitrary Markdown doc from the public GitHub repo (see ``Settings.skills_repo``).

The repo is public, so files are read with a plain unauthenticated GET of GitHub's raw
content — no token, no OAuth. A doc is addressed by its repo-relative ``path`` (e.g.
``faq.md`` or ``.claude/skills/<name>/SKILL.md``).

The fetch degrades gracefully: any failure (404, non-200, timeout, network error) returns
``None`` rather than raising, so callers can fall back to a "view on GitHub" link without the
page erroring. ``repo_doc_source_url`` builds that human-facing blob link with no network.

This is the single fetch contract for the app; ``skill_docs`` is a thin wrapper over it.
"""

from collections.abc import Callable

import httpx

from .settings import Settings

_DEFAULT_TIMEOUT = 10


def raw_doc_url(path: str, settings: Settings) -> str:
    return f"https://raw.githubusercontent.com/{settings.skills_repo}/{settings.skills_ref}/{path}"


def repo_doc_source_url(path: str, settings: Settings) -> str:
    """The human-facing GitHub *blob* URL for a repo doc (pure, no network).

    Rendered in a browser for anyone when the repo is public, and for authorized users if it
    later goes private. Used as the "view on GitHub" affordance and the fallback link."""
    return f"https://github.com/{settings.skills_repo}/blob/{settings.skills_ref}/{path}"


async def fetch_repo_doc(
    path: str,
    settings: Settings,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str | None:
    """Return a repo doc's text from the public repo, or ``None`` on any failure.

    Never raises: transport/timeout errors and non-200 responses both yield ``None`` so the
    caller degrades to a fallback. ``client_factory`` is injectable so tests can supply an
    ``httpx.MockTransport``-backed client; ``timeout`` bounds the default client (callers that
    block a page render on this fetch pass a shorter value)."""
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
    try:
        async with factory() as client:
            resp = await client.get(raw_doc_url(path, settings))
    except httpx.HTTPError:
        return None
    return resp.text if resp.status_code == 200 else None
