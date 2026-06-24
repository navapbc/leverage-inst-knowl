from lik_mcp.catalog import (
    CatalogEntry,
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
