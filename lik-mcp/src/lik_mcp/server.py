from mcp.server.fastmcp import FastMCP

from .auth import Verifier
from .catalog import (
    CatalogEntry,
    ListResult,
    LookupResult,
    RegisterResult,
    list_catalog_entries,
    lookup_catalog_entry,
    register_catalog_entry,
)
from .citations import Citation, CitationResolver
from .confirmations import (
    ConfirmationsResult,
    ConfirmResult,
    confirm_source,
    read_confirmations,
)
from .db import Database


def build_server(db: Database, verifier: Verifier, resolver: CitationResolver) -> FastMCP:
    """Construct the MCP service. Dependencies are injected so tests can substitute a
    stub verifier / resolver and a test database. The service exposes ONLY the four
    intent-named tools below — there is no generic SQL tool."""

    mcp = FastMCP("lik-mcp")

    @mcp.tool(name="register_catalog_entry")
    def _register_catalog_entry(entry: CatalogEntry, token: str | None = None) -> RegisterResult:
        """Register or update a Catalog row, keyed on (entry_type, subject). Service-only writer."""
        identity = verifier.verify(token)
        return register_catalog_entry(db, entry, updated_by=identity.email)

    @mcp.tool(name="lookup_catalog_entry")
    def _lookup_catalog_entry(entry_type: str, subject: str, token: str | None = None) -> LookupResult:
        """Resolve (entry_type, subject) -> location in one exact-match lookup. Miss = not found."""
        verifier.verify(token)
        return lookup_catalog_entry(db, entry_type, subject)

    @mcp.tool(name="list_catalog_entries")
    def _list_catalog_entries(entry_type: str, token: str | None = None) -> ListResult:
        """List every Catalog row of one entry_type (e.g. 'index'). Bounded by the
        discovery key — not a generic query. Empty type = empty list, never an error."""
        verifier.verify(token)
        return list_catalog_entries(db, entry_type)

    @mcp.tool(name="confirm_source")
    def _confirm_source(citation: Citation, token: str | None = None) -> ConfirmResult:
        """Record a user's confirmation that a cited source was right. The confirming
        identity comes from the verified token (never self-asserted)."""
        identity = verifier.verify(token)
        return confirm_source(db, citation, identity.email, resolver)

    @mcp.tool(name="read_confirmations")
    def _read_confirmations(citation: Citation, token: str | None = None) -> ConfirmationsResult:
        """Return accumulated confirmations for one cited source-version."""
        verifier.verify(token)
        return read_confirmations(db, citation)

    return mcp
