import logging

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from lik_mcp.auth import FailClosedVerifier
from lik_mcp.server import build_server


async def test_tool_call_logs_request_caller_and_result(server, caplog):
    """A tool call logs the request fields, the verified caller, and the outcome — the
    detail that 'Processing request of type CallToolRequest' alone doesn't give."""
    with caplog.at_level(logging.INFO, logger="lik_mcp.server"):
        await server.call_tool(
            "lookup_catalog_entry",
            {"entry_type": "index", "subject": "Atlas", "token": "alice@navapbc.com"},
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any("tool=lookup_catalog_entry request" in m and "Atlas" in m for m in messages)
    assert any("authorized caller=alice@navapbc.com" in m for m in messages)
    assert any("tool=lookup_catalog_entry result found=" in m for m in messages)


async def test_logs_never_include_the_token(server, caplog):
    """The auth token is a credential: it must appear in no log line, only the email it
    resolves to. A leaked token in the StubVerifier doubles as an email, so use one that
    is clearly not the logged caller."""
    secret = "s3cret-bearer-token"
    with caplog.at_level(logging.INFO, logger="lik_mcp.server"):
        await server.call_tool("list_catalog_entries", {"entry_type": "index", "token": secret})

    # The stub treats the token as the email, so the *caller* line will contain it — that
    # is the resolved identity, not the raw credential. No OTHER line should.
    request_and_result = [
        r.getMessage() for r in caplog.records if "authorized caller=" not in r.getMessage()
    ]
    assert request_and_result, "expected request/result log lines"
    assert all(secret not in m for m in request_and_result)


async def test_authorization_denial_is_logged(db, resolver, caplog):
    """A fail-closed verifier's refusal is logged at WARNING with the reason, so a denied
    call is visible in the logs instead of silently 500-ing."""
    server = build_server(db, FailClosedVerifier(), resolver)
    with caplog.at_level(logging.INFO, logger="lik_mcp.server"):
        # FastMCP re-wraps the refusal as a ToolError; we only care that we logged it first.
        with pytest.raises(ToolError):
            await server.call_tool("list_catalog_entries", {"entry_type": "index", "token": "x"})

    denials = [r for r in caplog.records if "authorization denied" in r.getMessage()]
    assert denials, "expected an authorization-denied log line"
    assert denials[0].levelno == logging.WARNING
