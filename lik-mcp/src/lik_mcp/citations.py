from typing import Protocol

from pydantic import BaseModel, field_validator

# The store kinds the Catalog knows how to point at (v0.4/05-architecture.md).
KNOWN_STORE_KINDS = {"gdoc", "gsheet", "confluence", "postgres", "bigquery"}


class Citation(BaseModel):
    """A resolvable reference to a cited source: store_kind + location + locator + version
    (the same shape the Catalog uses). `locator` normalizes to '' so it joins reliably."""

    store_kind: str
    location: str
    locator: str = ""
    version: str

    @field_validator("locator", mode="before")
    @classmethod
    def _normalize_locator(cls, v):
        return v or ""


class CitationResolver(Protocol):
    def resolve(self, citation: Citation) -> bool: ...


class ShapeResolver:
    """First-slice resolver: a citation 'resolves' if it is well-formed and names a
    known store kind. Real per-store reachability checks are deferred and land with the
    source connectors, behind this same interface."""

    def resolve(self, citation: Citation) -> bool:
        return (
            citation.store_kind in KNOWN_STORE_KINDS
            and bool(citation.location.strip())
            and bool(citation.version.strip())
        )
