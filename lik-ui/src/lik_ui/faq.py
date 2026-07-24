"""The FAQ page.

Serves ``/faq``, which renders the curated ``faq.md`` fetched from the public repo (the same
public-GitHub, graceful-``None`` fetch used for skill instructions — see :mod:`repo_docs`). The
raw Markdown is embedded in a hidden ``<template>`` and rendered client-side with marked +
DOMPurify, so a fetch failure or a missing CDN degrades to a link/literal text rather than an
error. Login-gated like the other pages.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .repo_docs import fetch_repo_doc, repo_doc_source_url

# Bound below the default 10s so a slow GitHub fetch can't block the page render for long; on
# timeout the fetch returns None and the page shows the "view on GitHub" fallback.
_FAQ_FETCH_TIMEOUT = 5


def register_faq_routes(app: FastAPI) -> None:
    from .app import templates  # local import avoids a circular import at module load
    from .app_auth import require_user

    @app.get("/faq", response_class=HTMLResponse)
    async def faq(request: Request):
        user = require_user(request)
        settings = request.app.state.settings
        content = await fetch_repo_doc("faq.md", settings, timeout=_FAQ_FETCH_TIMEOUT)
        # Treat an empty/whitespace-only body the same as a failed fetch: show the fallback link
        # rather than a blank page.
        if content is not None and not content.strip():
            content = None
        source_url = repo_doc_source_url("faq.md", settings)
        return templates.TemplateResponse(
            request,
            "faq.html",
            {"user": user, "content": content, "source_url": source_url},
        )
