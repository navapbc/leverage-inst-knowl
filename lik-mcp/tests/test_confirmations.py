import re

from lik_mcp.citations import Citation, ShapeResolver
from lik_mcp.confirmations import confirm_source, read_confirmations

RESOLVER = ShapeResolver()
ALICE = "alice@navapbc.com"
BOB = "bob@navapbc.com"


def _citation(**overrides) -> Citation:
    base = dict(store_kind="confluence", location="page:123", locator="", version="v5")
    base.update(overrides)
    return Citation(**base)


def _citation_no_version(**overrides) -> Citation:
    base = dict(store_kind="confluence", location="page:123", locator="")
    base.update(overrides)
    return Citation(**base)


def test_unresolvable_citation_rejected(db):
    """AE2 — a citation that doesn't resolve is refused and writes no row."""
    bad = Citation(store_kind="unknown-store", location="x", version="v1")
    result = confirm_source(db, bad, ALICE, RESOLVER)
    assert result.status == "rejected"
    assert result.reason == "unresolvable_citation"
    assert read_confirmations(db, bad).count == 0


def test_duplicate_deduped(db):
    """AE3 — the same user confirming the same source-version twice yields one row."""
    citation = _citation()
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "recorded"
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "duplicate"
    assert read_confirmations(db, citation).count == 1


def test_duplicate_deduped_no_version(db):
    """Dedup works for version='' — same user can't confirm same source twice."""
    citation = _citation_no_version()
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "recorded"
    assert confirm_source(db, citation, ALICE, RESOLVER).status == "duplicate"
    assert read_confirmations(db, citation).count == 1


def test_read_is_cross_version(db):
    """AE4 (redefined, R9) — read_confirmations returns confirmations across all versions
    of a source; each row carries its version so the consumer weighs current vs prior.
    confirm_source still records per exact version."""
    confirm_source(db, _citation(version="v5"), ALICE, RESOLVER)

    # Reading with any version of the same source surfaces the v5 confirmation.
    by_v5 = read_confirmations(db, _citation(version="v5"))
    by_v7 = read_confirmations(db, _citation(version="v7"))
    assert by_v5.count == 1
    assert by_v7.count == 1
    assert by_v7.confirmations[0].version == "v5"

    # Each row has created_at in ISO 8601 format (R2).
    assert re.match(r"\d{4}-\d{2}-\d{2}T", by_v5.confirmations[0].created_at)

    # A second confirmation on a later version accumulates; both versions are returned.
    confirm_source(db, _citation(version="v7"), ALICE, RESOLVER)
    both = read_confirmations(db, _citation(version="v7"))
    assert both.count == 2
    assert sorted(c.version for c in both.confirmations) == ["v5", "v7"]


def test_read_cross_version_with_no_version(db):
    """Cross-version read includes version='' rows alongside versioned rows."""
    confirm_source(db, _citation(version="v5"), ALICE, RESOLVER)
    confirm_source(db, _citation_no_version(), BOB, RESOLVER)

    # Reading with version="" returns both.
    result = read_confirmations(db, _citation_no_version())
    assert result.count == 2
    versions = {c.version for c in result.confirmations}
    assert "" in versions
    assert "v5" in versions


def test_confirm_with_version_none_normalizes(db):
    """Citation(version=None) normalizes to '' and records successfully (R1)."""
    citation = Citation(store_kind="confluence", location="page:456", version=None)
    result = confirm_source(db, citation, ALICE, RESOLVER)
    assert result.status == "recorded"
    rows = read_confirmations(db, citation)
    assert rows.count == 1
    assert rows.confirmations[0].version == ""


def test_no_version_row_has_created_at(db):
    """When version='', created_at is present and parseable — usable for recency weighing."""
    citation = _citation_no_version()
    confirm_source(db, citation, ALICE, RESOLVER)
    rows = read_confirmations(db, citation)
    assert rows.count == 1
    row = rows.confirmations[0]
    assert row.version == ""
    assert re.match(r"\d{4}-\d{2}-\d{2}T", row.created_at)
