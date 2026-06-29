import pytest
from pydantic import ValidationError

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
        subject="Atlas",
        location="https://wiki/atlas",
        store_kind="confluence",
        computed_by="summarizer@navapbc.com",
    )
    base.update(overrides)
    return CatalogEntry(**base)


def test_reregister_upserts(db):
    """AE1 — a skill re-registering its own key updates in place (one row, new values)."""
    first = register_catalog_entry(db, _entry(location="https://old"), updated_by="svc")
    assert first.status == "inserted"

    second = register_catalog_entry(db, _entry(location="https://new"), updated_by="svc")
    assert second.status == "updated"
    assert second.id == first.id  # same row, re-derived in place

    found = lookup_catalog_entry(db, "project-summary", "Atlas")
    assert found.count == 1
    assert found.entries[0]["location"] == "https://new"

    with db.connection() as conn:
        count = conn.execute("SELECT count(*) AS n FROM catalog").fetchone()["n"]
    assert count == 1


def test_human_saves_coexist_as_duplicates(db):
    """A key may resolve to several rows: independent human saves are exempt from the
    skill upsert arbiter, so each inserts a new pointer rather than overwriting (v0.4 §3)."""
    first = register_catalog_entry(
        db,
        _entry(location="https://alice", provenance="human-created", row_provenance="human"),
        updated_by="alice",
    )
    second = register_catalog_entry(
        db,
        _entry(location="https://bob", provenance="human-created", row_provenance="human"),
        updated_by="bob",
    )
    assert first.status == "inserted"
    assert second.status == "inserted"
    assert first.id != second.id

    found = lookup_catalog_entry(db, "project-summary", "Atlas")
    assert found.count == 2
    assert {e["location"] for e in found.entries} == {"https://alice", "https://bob"}


def test_lookup_ranks_verified_first(db):
    """Ranking is load-bearing: human-verified outranks unverified so the top row is the
    one a default consumer follows."""
    register_catalog_entry(
        db,
        _entry(location="https://unverified", row_provenance="human"),
        updated_by="alice",
    )
    register_catalog_entry(
        db,
        _entry(
            location="https://verified",
            row_provenance="human",
            verification="human-verified",
        ),
        updated_by="bob",
    )

    found = lookup_catalog_entry(db, "project-summary", "Atlas")
    assert found.count == 2
    assert found.entries[0]["location"] == "https://verified"


def test_lookup_miss_returns_empty(db):
    """AE5 — a missing Catalog row is a clean empty result, not an exception."""
    result = lookup_catalog_entry(db, "no-such-type", "no-such-subject")
    assert result.count == 0
    assert result.entries == []


def test_list_returns_rows_for_one_type_ordered(db):
    """list_catalog_entries returns only the requested entry_type, ordered by subject."""
    register_catalog_entry(db, _entry(entry_type="index", subject="Beta"), updated_by="svc")
    register_catalog_entry(db, _entry(entry_type="index", subject="Alpha"), updated_by="svc")
    register_catalog_entry(
        db, _entry(entry_type="project-summary", subject="Gamma"), updated_by="svc"
    )

    result = list_catalog_entries(db, "index")
    assert result.count == 2
    assert [e["subject"] for e in result.entries] == ["Alpha", "Beta"]


def test_list_unknown_type_returns_empty(db):
    """A type with no rows is a clean empty list, never an error."""
    result = list_catalog_entries(db, "no-such-type")
    assert result.count == 0
    assert result.entries == []


def test_source_refs_source_state_round_trips(db):
    """source_refs round-trips with source_state populated (R4) — the opaque content-state
    marker a consumer compares by equality to detect drift."""
    entry = _entry(source_refs=[SourceRef(id="p1", source_state="abc123")])
    register_catalog_entry(db, entry, updated_by="svc")

    result = list_catalog_entries(db, "project-summary")
    refs = result.entries[0]["source_refs"]
    assert len(refs) == 1
    assert refs[0]["id"] == "p1"
    assert refs[0]["source_state"] == "abc123"


def test_source_refs_no_source_state(db):
    """source_refs with only id (no source_state) deserializes with an explicit null
    field — not an absent key."""
    entry = _entry(source_refs=[SourceRef(id="p1")])
    register_catalog_entry(db, entry, updated_by="svc")

    result = list_catalog_entries(db, "project-summary")
    ref = result.entries[0]["source_refs"][0]
    assert ref["id"] == "p1"
    assert ref["source_state"] is None


def test_source_refs_rejects_removed_fields(db):
    """The removed `version` / `fetched_at` fields fail loudly at the contract boundary
    rather than being silently dropped (System-Wide Impact)."""
    with pytest.raises(ValidationError):
        SourceRef(id="p1", fetched_at="2026-06-24T00:00:00Z")
    with pytest.raises(ValidationError):
        SourceRef(id="p1", version="v5")


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
    _seed_index(db, "Atlas", "Borealis")

    result = search_catalog_entries(db, "index", "Atl")
    subjects = [e["subject"] for e in result.entries]
    assert "Atlas" in subjects
    assert "Borealis" not in subjects


def test_search_fuzzy_typo(db):
    """A typo'd query still finds the row via trigram similarity (R2)."""
    _seed_index(db, "Atlas", "Borealis")

    result = search_catalog_entries(db, "index", "Atals")
    assert "Atlas" in [e["subject"] for e in result.entries]


def test_search_reordered_words(db):
    """Reordered words match via trigram similarity, not substring (R2)."""
    _seed_index(db, "Centers for Medicare", "Department of Labor")

    result = search_catalog_entries(db, "index", "Medicare Centers")
    assert "Centers for Medicare" in [e["subject"] for e in result.entries]


def test_search_ranked_by_similarity(db):
    """Closest match ranks first; every entry carries a similarity score (R3)."""
    _seed_index(db, "Atlas", "Atlas Mapping Service")

    result = search_catalog_entries(db, "index", "Atlas")
    assert result.entries[0]["subject"] == "Atlas"  # exact-est match first
    scores = [e["score"] for e in result.entries]
    assert scores == sorted(scores, reverse=True)


def test_search_limit_caps_results(db):
    """`limit` bounds the number of rows returned (R3)."""
    _seed_index(db, *[f"Atlas {i}" for i in range(5)])

    result = search_catalog_entries(db, "index", "Atlas", limit=2)
    assert result.count == 2
    assert len(result.entries) == 2


def test_search_no_match_is_empty(db):
    """A query matching nothing is a clean empty result, never an error."""
    _seed_index(db, "Atlas")

    result = search_catalog_entries(db, "index", "zzzznomatch")
    assert result.count == 0
    assert result.entries == []


def test_search_category_prefilter(db):
    """An explicit category filters out otherwise-matching rows of other categories (R4)."""
    _seed_index(db, "Atlas North", category="infra")
    _seed_index(db, "Atlas South", category="research")

    result = search_catalog_entries(db, "index", "Atlas", category="infra")
    subjects = [e["subject"] for e in result.entries]
    assert subjects == ["Atlas North"]


def test_search_empty_query_is_empty(db):
    """An empty or whitespace query must not degenerate into match-all."""
    _seed_index(db, "Atlas", "Borealis")

    for q in ("", "   "):
        result = search_catalog_entries(db, "index", q)
        assert result.count == 0
        assert result.entries == []


def test_search_limit_clamped(db):
    """Degenerate limits neither error nor defeat the bound: 0/negative clamp up to >=1,
    oversized clamps down to the cap (50)."""
    _seed_index(db, *[f"Atlas {i}" for i in range(3)])

    # 0 and negative would otherwise return nothing / raise in Postgres.
    assert search_catalog_entries(db, "index", "Atlas", limit=0).count >= 1
    assert search_catalog_entries(db, "index", "Atlas", limit=-5).count >= 1
    # Oversized is accepted (no error) and bounded by available rows.
    assert search_catalog_entries(db, "index", "Atlas", limit=10_000).count == 3


def test_search_like_metacharacters_are_literal(db):
    """`%` in the query is matched literally, not as an ILIKE wildcard (no over-match)."""
    _seed_index(db, "Atlas", "Borealis", "50% target")

    result = search_catalog_entries(db, "index", "%")
    # Only the row containing a literal '%' matches; '%' must not match every row.
    assert [e["subject"] for e in result.entries] == ["50% target"]


def test_search_min_similarity_threshold(db):
    """A high min_similarity excludes a fuzzy (non-substring) match that the default admits."""
    _seed_index(db, "Atlas")

    assert search_catalog_entries(db, "index", "Atals").count == 1  # default 0.3 admits
    assert search_catalog_entries(db, "index", "Atals", min_similarity=0.99).count == 0


def test_search_scoped_to_entry_type(db):
    """Search never returns rows of another entry_type, even on a subject match."""
    _seed_index(db, "Atlas")
    register_catalog_entry(
        db, _entry(entry_type="project-summary", subject="Atlas"), updated_by="svc"
    )

    result = search_catalog_entries(db, "index", "Atlas")
    assert result.count == 1
    assert result.entries[0]["entry_type"] == "index"
