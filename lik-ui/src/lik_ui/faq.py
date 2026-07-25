"""The FAQ page.

Serves ``/faq``, which renders the curated ``faq.md`` bundled inside this package (see
``Settings.faq_path`` / pyproject package-data). The content is read from the local filesystem
— no GitHub fetch — so the repo can be private. The raw Markdown is embedded in a hidden
``<template>`` and rendered client-side with marked + DOMPurify, so a missing file or a missing
CDN degrades to a link/literal text rather than an error. Login-gated like the other pages.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .repo_docs import repo_doc_source_url
from .settings import Settings

# The repo-relative path of the bundled FAQ, used only to build its "view on GitHub" blob link.
_FAQ_REPO_PATH = "lik-ui/src/lik_ui/faq.md"


def load_faq(settings: Settings) -> str | None:
    """Return the bundled FAQ text, or ``None`` if it is missing/unreadable or empty.

    An empty/whitespace-only body is treated like a missing file so the page shows the
    fallback link rather than a blank render."""
    path = Path(settings.faq_path)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return text if text.strip() else None


def register_faq_routes(app: FastAPI) -> None:
    from .app import templates  # local import avoids a circular import at module load
    from .app_auth import require_user

    @app.get("/faq", response_class=HTMLResponse)
    async def faq(request: Request):
        user = require_user(request)
        settings = request.app.state.settings
        content = load_faq(settings)
        source_url = repo_doc_source_url(_FAQ_REPO_PATH, settings)
        return templates.TemplateResponse(
            request,
            "faq.html",
            {"user": user, "content": content, "source_url": source_url},
        )
