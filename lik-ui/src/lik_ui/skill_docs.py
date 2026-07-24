"""Fetch a skill's full ``SKILL.md`` from the public GitHub repo.

A skill is addressed by its *name*, which the deploy pipeline guarantees equals the skill's
directory, so the path is always ``.claude/skills/<name>/SKILL.md``. This module is a thin
wrapper over :mod:`repo_docs` — the single fetch/degradation contract — so there is one code
path (skill fetches are just a repo doc at the skill's path). See ``repo_docs`` for the
public-repo, graceful-``None`` behavior.
"""

from .repo_docs import fetch_repo_doc, raw_doc_url, repo_doc_source_url
from .settings import Settings


def _skill_path(name: str) -> str:
    return f".claude/skills/{name}/SKILL.md"


def _raw_url(name: str, settings: Settings) -> str:
    return raw_doc_url(_skill_path(name), settings)


def skill_source_url(name: str, settings: Settings) -> str:
    """The human-facing GitHub *blob* URL for a skill's ``SKILL.md`` (pure, no network)."""
    return repo_doc_source_url(_skill_path(name), settings)


async def fetch_skill_instructions(name: str, settings: Settings, client_factory=None) -> str | None:
    """Return a skill's ``SKILL.md`` text from the public repo, or ``None`` on any failure."""
    return await fetch_repo_doc(_skill_path(name), settings, client_factory)
