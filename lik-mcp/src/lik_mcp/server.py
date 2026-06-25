import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .auth import Verifier
from .catalog import (
    CatalogEntry,
    ListResult,
    LookupResult,
    RegisterResult,
    SearchResult,
    list_catalog_entries,
    lookup_catalog_entry,
    register_catalog_entry,
    search_catalog_entries,
)
from .citations import Citation, CitationResolver
from .confirmations import (
    ConfirmationsResult,
    ConfirmResult,
    confirm_source,
    read_confirmations,
)
from .db import Database

# One named logger for the service. Tool calls log at INFO; authorization denials and
# tool failures log at WARNING. The auth token is a credential and is NEVER logged —
# only the verified caller email that the token resolves to.
logger = logging.getLogger("lik_mcp.server")


def build_server(
    db: Database,
    verifier: Verifier,
    resolver: CitationResolver,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Construct the MCP service. Dependencies are injected so tests can substitute a
    stub verifier / resolver and a test database. host/port apply only to the
    streamable-http transport. The service exposes ONLY the intent-named tools below —
    there is no generic SQL tool."""

    # The HTTP transport must bind 0.0.0.0 inside a container to be reachable through a
    # published port, so loopback-binding can't be the DNS-rebinding guard. Restrict the
    # accepted Host header to loopback instead (the host side publishes 127.0.0.1 only).
    # Harmless under stdio (no HTTP middleware runs). A real deploy must widen this.
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"],
    )
    mcp = FastMCP("lik-mcp", host=host, port=port, transport_security=transport_security)

    def _authorize(tool: str, token: str | None):
        """Verify the caller and log the outcome. Logs the resolved caller email on
        success and the reason on denial — never the token itself."""
        try:
            identity = verifier.verify(token)
        except Exception as exc:
            logger.warning("tool=%s authorization denied: %s", tool, exc)
            raise
        logger.info("tool=%s authorized caller=%s", tool, identity.email)
        return identity

    @mcp.tool(name="register_catalog_entry")
    def _register_catalog_entry(entry: CatalogEntry, token: str | None = None) -> RegisterResult:
        """Register or update a Catalog row, keyed on (entry_type, subject). Service-only writer."""
        logger.info(
            "tool=register_catalog_entry request entry_type=%r subject=%r store_kind=%r computed_by=%r",
            entry.entry_type, entry.subject, entry.store_kind, entry.computed_by,
        )
        identity = _authorize("register_catalog_entry", token)
        result = register_catalog_entry(db, entry, updated_by=identity.email)
        logger.info(
            "tool=register_catalog_entry result status=%s entry_type=%r subject=%r",
            result.status, result.entry_type, result.subject,
        )
        return result

    @mcp.tool(name="lookup_catalog_entry")
    def _lookup_catalog_entry(entry_type: str, subject: str, token: str | None = None) -> LookupResult:
        """Resolve (entry_type, subject) -> location in one exact-match lookup. Miss = not found."""
        logger.info(
            "tool=lookup_catalog_entry request entry_type=%r subject=%r", entry_type, subject
        )
        _authorize("lookup_catalog_entry", token)
        result = lookup_catalog_entry(db, entry_type, subject)
        logger.info("tool=lookup_catalog_entry result found=%s", result.found)
        return result

    @mcp.tool(name="list_catalog_entries")
    def _list_catalog_entries(entry_type: str, token: str | None = None) -> ListResult:
        """List every Catalog row of one entry_type (e.g. 'index'). Bounded by the
        discovery key — not a generic query. Empty type = empty list, never an error."""
        logger.info("tool=list_catalog_entries request entry_type=%r", entry_type)
        _authorize("list_catalog_entries", token)
        result = list_catalog_entries(db, entry_type)
        logger.info("tool=list_catalog_entries result count=%d", result.count)
        return result

    @mcp.tool(name="search_catalog_entries")
    def _search_catalog_entries(
        entry_type: str,
        query: str,
        category: str | None = None,
        limit: int = 10,
        token: str | None = None,
    ) -> SearchResult:
        """Partial + fuzzy search on `subject` within one entry_type. Returns the top
        `limit` rows ranked by similarity — a bounded candidate set for placing a fuzzy
        question on the right key, not a full read. Optional `category` is an exact-match
        pre-filter. No match = empty result, never an error."""
        logger.info(
            "tool=search_catalog_entries request entry_type=%r query=%r category=%r limit=%d",
            entry_type, query, category, limit,
        )
        _authorize("search_catalog_entries", token)
        result = search_catalog_entries(db, entry_type, query, category=category, limit=limit)
        logger.info("tool=search_catalog_entries result count=%d", result.count)
        return result

    @mcp.tool(name="confirm_source")
    def _confirm_source(
        citation: Citation,
        vote: str = "up",
        reason: str | None = None,
        comment: str | None = None,
        token: str | None = None,
    ) -> ConfirmResult:
        """Record a user's signed vote on a cited source. `vote` is 'up' (the source was
        right) or 'down' (wrong); a down vote names a `reason` ('bad-retrieval' |
        'wrong-content'), an up vote names none. `comment` is an optional free-text note.
        The confirming identity comes from the verified token (never self-asserted)."""
        logger.info(
            "tool=confirm_source request store_kind=%r location=%r locator=%r source_state=%r vote=%r reason=%r",
            citation.store_kind, citation.location, citation.locator, citation.source_state, vote, reason,
        )
        identity = _authorize("confirm_source", token)
        result = confirm_source(db, citation, identity.email, resolver, vote, reason, comment)
        logger.info("tool=confirm_source result %s", result.model_dump())
        return result

    @mcp.tool(name="read_confirmations")
    def _read_confirmations(
        citation: Citation,
        current_source_state: str | None = None,
        token: str | None = None,
    ) -> ConfirmationsResult:
        """Return accumulated confirmations for one cited source. Pass `current_source_state`
        (the source's live content-state marker) to flag each row's `edited_since`; omit it
        and `edited_since` is None (unknown). The citation's own `source_state` is ignored
        for matching."""
        logger.info(
            "tool=read_confirmations request store_kind=%r location=%r locator=%r current_source_state=%r",
            citation.store_kind, citation.location, citation.locator, current_source_state,
        )
        _authorize("read_confirmations", token)
        result = read_confirmations(db, citation, current_source_state)
        logger.info("tool=read_confirmations result count=%d", result.count)
        return result

    return mcp
