from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator

# The store kinds the Catalog knows how to point at (v0.4/05-architecture.md).
KNOWN_STORE_KINDS = {"gdoc", "gsheet", "confluence", "postgres", "bigquery"}


class Citation(BaseModel):
    """A resolvable reference to a cited source: store_kind + location + locator + source_state
    (the same shape the Catalog uses). `locator` and `source_state` normalize to '' so they
    join reliably. `source_state` is an opaque content-state marker (a native change signal
    or a content hash, not necessarily a version number); it is compared by equality to
    detect "edited since" and is optional — defaults to '' when the store supplies none.
    Extra fields are forbidden so a caller still sending the removed `version` fails loudly
    at the contract boundary instead of having it silently dropped (which would record an
    empty marker and make "edited since" never fire)."""

    model_config = ConfigDict(extra="forbid")

    store_kind: str
    location: str
    locator: str = ""
    source_state: str = ""

    @field_validator("locator", mode="before")
    @classmethod
    def _normalize_locator(cls, v):
        return v or ""

    @field_validator("source_state", mode="before")
    @classmethod
    def _normalize_source_state(cls, v):
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
        )
