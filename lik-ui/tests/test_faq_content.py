"""U3: the curated faq.md, validated offline (no live fetch).

This is the highest-value guard for the FAQ: because the app fetches faq.md from `main` at
runtime, the real page is otherwise first seen in production. These checks run in CI on the
branch and enforce R3 (both sections), R6 (every source referenced), and that every intra-repo
link in faq.md resolves to a real file/heading — including the developer-section anchors, the
drift-prone part (also covers U2's link-target verification)."""

import re
from pathlib import Path

from lik_ui.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
FAQ = REPO_ROOT / "faq.md"

_SETTINGS = Settings(env="test")  # default repo/ref — the same values the app fetches with
_BLOB_PREFIX = f"https://github.com/{_SETTINGS.skills_repo}/blob/{_SETTINGS.skills_ref}/"

# R6 sources that must be referenced somewhere on the page.
R6_SOURCES = [
    "claude-managed-agents.md",
    "v0.4/01-overview.md",
    "limitations.md",
    "mcp-availability.md",
    "lik-ui/README.md",
]

_LINK_RE = re.compile(r"\[[^\]]*\]\((?P<url>[^)]+)\)")


def _gh_slug(heading: str) -> str:
    """Approximate GitHub's heading-anchor slug: lowercase, drop punctuation (keeping word
    chars, spaces, hyphens), then spaces -> hyphens."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return s.replace(" ", "-")


def _headings(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^#{1,6}\s+(.*)$", text, flags=re.MULTILINE)]


def test_faq_exists_and_has_no_leading_frontmatter_rule():
    assert FAQ.is_file(), "faq.md must exist at the repo root"
    # A leading `---` would be misread as YAML frontmatter and stripped by the render (U4).
    assert not FAQ.read_text().lstrip().startswith("---")


def test_both_sections_present():
    text = FAQ.read_text()
    assert re.search(r"^##\s+What is this\?", text, flags=re.MULTILINE), "missing end-user section"
    assert re.search(r"^##\s+For developers", text, flags=re.MULTILINE), "missing developer section"


def test_every_r6_source_is_referenced():
    text = FAQ.read_text()
    for src in R6_SOURCES:
        assert src in text, f"R6 source not referenced in faq.md: {src}"


def test_every_intra_repo_link_resolves():
    text = FAQ.read_text()
    checked = 0
    for m in _LINK_RE.finditer(text):
        url = m.group("url")
        if not url.startswith(_BLOB_PREFIX):
            continue  # external link, not our concern here
        rel = url[len(_BLOB_PREFIX):]
        path_part, _, fragment = rel.partition("#")
        target = REPO_ROOT / path_part
        assert target.is_file(), f"faq.md links to a missing file: {path_part}"
        if fragment:
            slugs = {_gh_slug(h) for h in _headings(target.read_text())}
            assert fragment in slugs, f"faq.md links to a missing anchor #{fragment} in {path_part}"
        checked += 1
    assert checked >= len(R6_SOURCES), "expected the R6 sources to be linked, not just mentioned"
