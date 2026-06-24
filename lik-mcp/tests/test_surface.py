async def test_only_intent_named_tools(server):
    """AE6 — the service advertises only intent-named tools; no raw-SQL escape hatch.
    list_catalog_entries is bounded by the entry_type discovery key, not a generic query."""
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "register_catalog_entry",
        "lookup_catalog_entry",
        "list_catalog_entries",
        "confirm_source",
        "read_confirmations",
    }
