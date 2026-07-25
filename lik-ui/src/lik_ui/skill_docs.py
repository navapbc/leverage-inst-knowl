"""Build the human-facing GitHub link for a skill's ``SKILL.md``.

A skill is addressed by its *name*, which the deploy pipeline guarantees equals the skill's
directory, so the path is always ``claude_platform/skills/<name>/SKILL.md``. The connections
page links to this blob URL rather than fetching the file — the instructions are not shown
in-app — so nothing here touches the network.
"""

from .repo_docs import repo_doc_source_url
from .settings import Settings


def _skill_path(name: str) -> str:
    return f"claude_platform/skills/{name}/SKILL.md"


def skill_source_url(name: str, settings: Settings) -> str:
    """The human-facing GitHub *blob* URL for a skill's ``SKILL.md`` (pure, no network)."""
    return repo_doc_source_url(_skill_path(name), settings)
