# Open Questions

*Unresolved decisions for review, collected from across the <u>Architecture</u> and <u>Strategy</u>. Each must be settled before or during the level it affects.*

## Strategy & scope

- **Build vs. buy.** Glean / GoSearch / SearchUnify / Onyx / PipesHub / SWIRL already ingest these DSs, enforce permissions, and provide AI retrieval. Decide DL's delta (likely cross-source aggregations + confirmation signals) and consider scoping DL to just that. Compare the MVP against the realistic *buy* alternative, not only "no DL."
- **MVP is a full production build, not a minimum proof.** Front-load a falsification experiment — index 1–2 DSs, build hints, A/B an agent with vs. without DL — before the full build.
- **DL output-type prioritization.** Partition the DL output types (summaries, indexes, hints, aggregations, freshness) into MVP-required / second-iteration / post-validation.
- **AI-skill scope.** The skill bundles ETL + trust/ranking + ACL propagation + store selection + Catalog registration; consider narrowing the MVP scope.
- **DS selection criteria** are undefined (connector availability, Group support, pilot coverage).
- **Per-DS identity delegation.** For each candidate DS, confirm whether it supports on-behalf-of token exchange, per-user OAuth consent (stored refresh token), or no per-user path at all — the last excludes it from Level 1 (<u>Access Control</u>).
- **Confirmation loop** needs UI, write path, schema, store, consumer — consider deferring post-MVP.

## Content freshness & change detection

- **Staleness / change detection** is underspecified: per-DS CDC / webhooks / delta tokens vs. full re-reads; DSs lacking delta primitives (Slack, Gmail); target refresh interval (which also sets the permission-leak window); and 403-vs-404-vs-5xx error semantics so transient outages don't purge valid DL. Catalog pointers need the same treatment.

## Catalog

- **Catalog scale ceiling.** Format is decided (Confluence page first, schema in <u>Architecture</u> §3, promote to Postgres / indexed DB). Still open: the concrete subject-count / pointer-volume threshold that triggers promotion, and the migration runbook (page → DB), including how in-flight skill writes are handled during cutover.
- **Catalog write integrity: detection & recovery.** With every write going through the skill account (autonomously, or under a verified human assertion for human-created rows), still open: detection cadence/trigger (skill validation pass vs. edit alerting), how the skill handles non-re-derivable human-created rows (validate the pointer, leave the row to revert), and the acceptable bound on the bad-pointer misdirection window.

## Provenance

- **Provenance-marking convention.** The human-edit → durable trigger is defined (the skill's overwrite-safety check: a last revision not authored by its own service account ⇒ treat as human-owned, leave untouched). Still open: the concrete per-DS marker (label / property / naming) readable by both humans and skills, and the explicit human-review → `human-verified` promotion UX.
