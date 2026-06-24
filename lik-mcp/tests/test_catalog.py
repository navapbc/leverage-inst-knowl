from lik_mcp.catalog import (
    CatalogEntry,
    SourceRef,
    list_catalog_entries,
    lookup_catalog_entry,
    register_catalog_entry,
)


def _entry(**overrides) -> CatalogEntry:
    base = dict(
        entry_type="project-summary",
        subject="project: Atlas",
        location="https://wiki/atlas",
        store_kind="confluence",
        computed_by="summarizer@navapbc.com",
    )
    base.update(overrides)
    return CatalogEntry(**base)


def test_reregister_upserts(db):
    """AE1 — re-registering the same key updates in place (one row, new values)."""
    first = register_catalog_entry(db, _entry(location="https://old"), updated_by="svc")
    assert first.status == "inserted"

    second = register_catalog_entry(db, _entry(location="https://new"), updated_by="svc")
    assert second.status == "updated"

    found = lookup_catalog_entry(db, "project-summary", "project: Atlas")
    assert found.found is True
    assert found.entry["location"] == "https://new"

    with db.connection() as conn:
        count = conn.execute("SELECT count(*) AS n FROM catalog").fetchone()["n"]
    assert count == 1


def test_lookup_miss_returns_not_found(db):
    """AE5 — a missing Catalog row is a clean not-found, not an exception."""
    result = lookup_catalog_entry(db, "no-such-type", "no-such-subject")
    assert result.found is False
    assert result.entry is None


def test_list_returns_rows_for_one_type_ordered(db):
    """list_catalog_entries returns only the requested entry_type, ordered by subject."""
    register_catalog_entry(db, _entry(entry_type="index", subject="project: Beta"), updated_by="svc")
    register_catalog_entry(db, _entry(entry_type="index", subject="project: Alpha"), updated_by="svc")
    register_catalog_entry(
        db, _entry(entry_type="project-summary", subject="project: Gamma"), updated_by="svc"
    )

    result = list_catalog_entries(db, "index")
    assert result.count == 2
    assert [e["subject"] for e in result.entries] == ["project: Alpha", "project: Beta"]


def test_list_unknown_type_returns_empty(db):
    """A type with no rows is a clean empty list, never an error."""
    result = list_catalog_entries(db, "no-such-type")
    assert result.count == 0
    assert result.entries == []


def test_source_refs_with_fetched_at(db):
    """source_refs round-trips with fetched_at populated (R4)."""
    entry = _entry(source_refs=[SourceRef(id="p1", fetched_at="2026-06-24T00:00:00Z")])
    register_catalog_entry(db, entry, updated_by="svc")

    result = list_catalog_entries(db, "project-summary")
    refs = result.entries[0]["source_refs"]
    assert len(refs) == 1
    assert refs[0]["id"] == "p1"
    assert refs[0]["fetched_at"] == "2026-06-24T00:00:00Z"


def test_source_refs_legacy_shape(db):
    """Legacy source_refs with only id (no version, no fetched_at) deserializes
    with explicit null fields — not absent keys (R3)."""
    entry = _entry(source_refs=[SourceRef(id="p1")])
    register_catalog_entry(db, entry, updated_by="svc")

    result = list_catalog_entries(db, "project-summary")
    ref = result.entries[0]["source_refs"][0]
    assert ref["id"] == "p1"
    assert ref["version"] is None
    assert ref["fetched_at"] is None


def test_source_refs_version_preserved(db):
    """Non-null version round-trips intact — stores that expose versions can use them (R6)."""
    entry = _entry(source_refs=[SourceRef(id="p1", version="v5")])
    register_catalog_entry(db, entry, updated_by="svc")

    result = list_catalog_entries(db, "project-summary")
    ref = result.entries[0]["source_refs"][0]
    assert ref["version"] == "v5"


def test_source_refs_empty_list(db):
    """Empty source_refs is accepted — existing behavior preserved."""
    entry = _entry(source_refs=[])
    first = register_catalog_entry(db, entry, updated_by="svc")
    assert first.status == "inserted"

    result = list_catalog_entries(db, "project-summary")
    assert result.entries[0]["source_refs"] == []
