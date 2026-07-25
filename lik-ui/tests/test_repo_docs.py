"""The repo-doc "view on GitHub" blob-URL builder (pure, no network)."""

from lik_ui.repo_docs import repo_doc_source_url
from lik_ui.settings import Settings


def test_source_url_is_pure_blob_url():
    settings = Settings(env="test")  # default repo/ref
    assert repo_doc_source_url("lik-ui/src/lik_ui/faq.md", settings) == (
        "https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/src/lik_ui/faq.md"
    )


def test_source_url_reflects_non_default_repo_and_ref():
    settings = Settings(env="test", skills_repo="acme/fork", skills_ref="dev")
    assert repo_doc_source_url("docs/x.md", settings) == (
        "https://github.com/acme/fork/blob/dev/docs/x.md"
    )
