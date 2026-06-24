async def test_only_four_tools(server):
    """AE6 — the service advertises only the four intent-named tools; no raw-SQL escape hatch."""
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "register_catalog_entry",
        "lookup_catalog_entry",
        "confirm_source",
        "read_confirmations",
    }
