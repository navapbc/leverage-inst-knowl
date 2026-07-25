"""The skill "view on GitHub" link builder.

The connections page links to a skill's SKILL.md rather than fetching it, so this only covers
the pure blob-URL construction (no network)."""

from lik_ui.settings import Settings
from lik_ui.skill_docs import skill_source_url


def test_source_url_is_pure_blob_url():
    settings = Settings(env="test")  # default repo/ref
    assert skill_source_url("lik-query-project-index", settings) == (
        "https://github.com/navapbc/leverage-inst-knowl/blob/main"
        "/claude_platform/skills/lik-query-project-index/SKILL.md"
    )


def test_source_url_reflects_non_default_repo_and_ref():
    settings = Settings(env="test", skills_repo="acme/fork", skills_ref="dev")
    assert skill_source_url("lik-thing", settings) == (
        "https://github.com/acme/fork/blob/dev/claude_platform/skills/lik-thing/SKILL.md"
    )
