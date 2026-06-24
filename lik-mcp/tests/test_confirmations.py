from lik_mcp.citations import Citation, ShapeResolver
from lik_mcp.confirmations import confirm_source, read_confirmations

RESOLVER = ShapeResolver()
ALICE = "alice@navapbc.com"


def _citation(**overrides) -> Citation:
    base = dict(store_kind="confluence", location="page:123", locator="", version="v5")
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


def test_version_bound_trust(db):
    """AE4 — a confirmation on v5 is not counted for v7 of the same source."""
    confirm_source(db, _citation(version="v5"), ALICE, RESOLVER)
    assert read_confirmations(db, _citation(version="v5")).count == 1
    assert read_confirmations(db, _citation(version="v7")).count == 0
