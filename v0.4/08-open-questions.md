# Open Questions

*Unresolved decisions for review, collected from across the <u>Architecture</u> and <u>Strategy</u>. Each must be settled before or during the level it affects.*

## Strategy & scope

- **Build vs. buy.** Glean / GoSearch / SearchUnify / Onyx / PipesHub / SWIRL already ingest these DSs, enforce permissions, and provide AI retrieval. Decide DL's delta (likely cross-source aggregations + confirmation signals) and consider scoping DL to just that. Compare the MVP against the realistic *buy* alternative, not only "no DL."
- **MVP is a full production build, not a minimum proof.** Front-load a falsification experiment — index 1–2 DSs, build hints, A/B an agent with vs. without DL — before the full build.
- **DL output-type prioritization.** Partition the DL output types (summaries, indexes, hints, aggregations, freshness) into MVP-required / second-iteration / post-validation.
- **AI-skill scope.** Catalog registration is now pulled out into a **separate Catalog-registration skill** (<u>Architecture</u> §3, §5) — it discovers `discovery-layer`-tagged records and owns the Catalog rows, while the DL-creation skills own producing and re-deriving content. The DL-creation skill still bundles ETL + trust/ranking + ACL propagation + store selection; consider narrowing that scope further for the MVP.
- **DS selection criteria** are undefined (connector availability, Group support, pilot coverage).
- **Per-DS identity delegation.** For each candidate DS, confirm whether it supports on-behalf-of token exchange, per-user OAuth consent (stored refresh token), or no per-user path at all — the last excludes it from Level 1 (<u>Access Control</u>).
- **Confirmation loop** needs UI, write path, schema, store, consumer — consider deferring post-MVP.

## Content freshness & change detection

- **Staleness / change detection** is underspecified: per-DS CDC / webhooks / delta tokens vs. full re-reads; DSs lacking delta primitives (Slack, Gmail); target refresh interval (which also sets the permission-leak window); and 403-vs-404-vs-5xx error semantics so transient outages don't purge valid DL. Catalog pointers need the same treatment.

## Catalog

- **Catalog write integrity: detection & recovery.** With every write going through the skill account (autonomously, or under a verified human assertion for human-created rows), still open: detection cadence/trigger (skill validation pass vs. edit alerting), how the skill handles non-re-derivable human-created rows (validate the pointer, leave the row to revert), and the acceptable bound on the bad-pointer misdirection window.

## Provenance

- **Provenance-marking convention.** *Resolved in principle; realization still open.* The human-edit → ownership-transfer trigger is defined as **change detection** (<u>Architecture</u> §5): a record changed since the DL-creation skill's own last write is treated as human-owned. The skill exposes a **normalized provenance state** — `provenance` (`ai-generated` vs. `human-created`), `verification` (`unverified` vs. `human-verified`), and `freshness` (`current` / `stale` / `obsolete`) — and **only that state is read outside the skill** (by the registrar, to populate the Catalog). *How* the skill maintains it — a content-state marker, a dedicated writer identity, a store label — is the DL-creation team's **private mechanism** and must not leak past this interface; that is what keeps their choice from touching the rest of the architecture. Two things remain open, and they are **independent**: (a) a **human-visible cue** on the record (a label/property telling a person "auto-maintained — editing takes it over") — cosmetic and per-DS, no architectural coupling; and (b) the explicit human-review → `human-verified` promotion UX.
