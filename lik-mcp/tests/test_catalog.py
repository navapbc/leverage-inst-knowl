from lik_mcp.catalog import (
    CatalogEntry,
    SourceRef,
    list_catalog_entries,
    lookup_catalog_entry,
    register_catalog_entry,
    search_catalog_entries,
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


def _seed_index(db, *subjects, **overrides):
    for subject in subjects:
        register_catalog_entry(
            db, _entry(entry_type="index", subject=subject, **overrides), updated_by="svc"
        )


def test_search_partial_substring(db):
    """A substring of the subject finds the row even when it's not the exact key (R1)."""
    _seed_index(db, "project: Atlas", "project: Borealis")

    result = search_catalog_entries(db, "index", "Atl")
    subjects = [e["subject"] for e in result.entries]
    assert "project: Atlas" in subjects
    assert "project: Borealis" not in subjects


def test_search_fuzzy_typo(db):
    """A typo'd query still finds the row via trigram similarity (R2)."""
    _seed_index(db, "project: Atlas", "project: Borealis")

    result = search_catalog_entries(db, "index", "Atals")
    assert "project: Atlas" in [e["subject"] for e in result.entries]


def test_search_reordered_words(db):
    """Reordered words match via trigram similarity, not substring (R2)."""
    _seed_index(db, "project: Centers for Medicare", "project: Department of Labor")

    result = search_catalog_entries(db, "index", "Medicare Centers")
    assert "project: Centers for Medicare" in [e["subject"] for e in result.entries]


def test_search_ranked_by_similarity(db):
    """Closest match ranks first; every entry carries a similarity score (R3)."""
    _seed_index(db, "project: Atlas", "project: Atlas Mapping Service")

    result = search_catalog_entries(db, "index", "Atlas")
    assert result.entries[0]["subject"] == "project: Atlas"  # exact-est match first
    scores = [e["score"] for e in result.entries]
    assert scores == sorted(scores, reverse=True)


def test_search_limit_caps_results(db):
    """`limit` bounds the number of rows returned (R3)."""
    _seed_index(db, *[f"project: Atlas {i}" for i in range(5)])

    result = search_catalog_entries(db, "index", "Atlas", limit=2)
    assert result.count == 2
    assert len(result.entries) == 2


def test_search_no_match_is_empty(db):
    """A query matching nothing is a clean empty result, never an error."""
    _seed_index(db, "project: Atlas")

    result = search_catalog_entries(db, "index", "zzzznomatch")
    assert result.count == 0
    assert result.entries == []


def test_search_category_prefilter(db):
    """An explicit category filters out otherwise-matching rows of other categories (R4)."""
    _seed_index(db, "project: Atlas North", category="infra")
    _seed_index(db, "project: Atlas South", category="research")

    result = search_catalog_entries(db, "index", "Atlas", category="infra")
    subjects = [e["subject"] for e in result.entries]
    assert subjects == ["project: Atlas North"]


def test_search_scoped_to_entry_type(db):
    """Search never returns rows of another entry_type, even on a subject match."""
    _seed_index(db, "project: Atlas")
    register_catalog_entry(
        db, _entry(entry_type="project-summary", subject="project: Atlas"), updated_by="svc"
    )

    result = search_catalog_entries(db, "index", "Atlas")
    assert result.count == 1
    assert result.entries[0]["entry_type"] == "index"
