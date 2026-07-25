"""Build the human-facing GitHub *blob* URL for a repo doc.

lik-ui does not fetch any doc from GitHub at runtime — the FAQ is bundled in the package and
skill instructions are shown as a link. All that remains here is the pure URL builder for the
"view on GitHub" affordance, addressed by a repo-relative ``path`` (e.g.
``lik-ui/src/lik_ui/faq.md`` or ``claude_platform/skills/<name>/SKILL.md``). No network.
"""

from .settings import Settings


def repo_doc_source_url(path: str, settings: Settings) -> str:
    """The human-facing GitHub *blob* URL for a repo doc (pure, no network).

    Rendered in a browser for anyone with access to the repo — including when it is private —
    so it stays useful as the "view on GitHub" affordance."""
    return f"https://github.com/{settings.skills_repo}/blob/{settings.skills_ref}/{path}"
