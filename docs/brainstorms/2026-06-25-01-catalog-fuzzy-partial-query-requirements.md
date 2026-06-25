# Catalog Fuzzy & Partial Query — Requirements

**Date:** 2026-06-25
**Status:** Requirements (ready for planning)
**Scope:** Standard

## Problem

The Catalog supports only exact-match lookup on its `(entry_type, subject)` key
(`lik-mcp/src/lik_mcp/catalog.py:105-114`). When a caller doesn't know the exact
subject string, the only fallback is `list_catalog_entries` — pull every row for an
`entry_type` and scan terms in-memory (Level 2 in the `query-project-index` skill).

That in-memory scan is the part that won't scale. The Catalog is expected to hold
**thousands of rows across many `entry_type`s** soon. Returning the full list to the
caller for client-side scanning becomes slow and token-heavy.

We want server-side **partial and fuzzy** matching that narrows and ranks candidates,
so callers stop pulling the whole list.

## What this is (and isn't)

This is **lexical narrowing**, not semantic search. The strategy explicitly permits it:
the Catalog does keyed lookup at minimum, but "an implementation **may** add partial or
fuzzy matching on its keys when that helps consumers place a question"
(`v0.4/04-strategy.md:120`). The split still holds — the Catalog narrows candidates
lexically; the Query skill still does final semantic placement and ranking. The existing
exact-match `lookup_catalog_entry` stays as the Level 1 fast path.

## Goals

- A server-side query that takes an `entry_type` + a query term and returns
  **ranked candidate rows** matched by partial **and** fuzzy comparison on `subject`.
- Optional `category` pre-filter to narrow before matching.
- Return a bounded, ranked result set (top-N with match scores) — not the full table.
- Scale to thousands of rows without returning the full list to callers.

## Non-Goals

- Semantic / conceptual search inside the Catalog (stays the skill's / source systems' job).
- Abbreviation↔full-name resolution (e.g. "CMS" ↔ "Centers for Medicare") — **deferred**
  to a future alias/synonym data effort. Trigram matching does not bridge this.
- Full-text / tsvector machinery.
- Changing or removing exact-match `lookup_catalog_entry`.

## Recommended Direction

**Trigram matching via Postgres `pg_trgm`.**

- Enable the `pg_trgm` extension; add a GIN trigram index on `subject` (and optionally
  `category`).
- New query ranks rows by trigram `similarity()` against the query term, accelerates
  `ILIKE`, applies the optional `category` filter, returns top-N candidates with scores.
- Smallest mechanism that delivers **both** partial and fuzzy (typos, word reorder,
  near-miss) in one index. Standard Postgres; scales to thousands+ with the GIN index.

Surface it as a **new** MCP query tool alongside the existing ones (exact-match
`lookup_catalog_entry` unchanged). (Exact tool name, params, and SQL are planning decisions.)

### query-project-index skill change

The new tool slots into **Level 1** as a fuzzy fallback after the exact lookup:

1. Exact `lookup_catalog_entry` (unchanged).
2. **On miss, call the new fuzzy/partial query** (still a targeted, bounded keyed
   lookup — top-N ranked candidates — so it runs **without** the "ask before widening"
   prompt, consistent with `v0.4/04-strategy.md:124` "targeted keyed lookup, not a full
   read"). A hit follows the candidate pointer(s) and answers.
3. On a fuzzy miss, fall through to **Level 2** (list + scan, ask first) and **Level 3**
   (Confluence fallback, ask first) — both **unchanged**.

`.claude/skills/query-project-index/SKILL.md` — extend Level 1 (currently lines 24-31);
leave Level 2 (33-45) and Level 3 (47-54) as-is.

### Approaches considered

| Approach | Partial | Fuzzy | Cost | Verdict |
|---|---|---|---|---|
| A. ILIKE substring | ✅ | ❌ | None (no extension) | Misses fuzzy ask |
| **B. pg_trgm trigram** | ✅ | ✅ | 1 extension, 1 index | **Recommended** |
| C. tsvector full-text | partial | ❌ (weak on typos) | Generated col + triggers | Over-built for names/keys |
| Challenger: partition by category, no fuzzy | ❌ | ❌ | None | Rejected — fails fuzzy ask; but its category-filter idea folds into B |

## Success Criteria

- A caller can find a Catalog row by a partial subject string (e.g. a substring of the
  project name) without knowing the exact subject.
- A caller can find a row despite a typo or reordered words in the query term.
- The query returns a bounded ranked candidate set, not the full `entry_type` table.
- Exact-match `lookup_catalog_entry` behavior is unchanged.
- `query-project-index` Level 1 calls the new fuzzy query on an exact miss (no widening
  prompt) and answers from a candidate hit; Level 2 and Level 3 behavior unchanged.

## Dependencies / Assumptions

- Postgres `pg_trgm` extension can be enabled in the deployment (standard, contrib).
- [Assumption] "thousands soon, many entry_types" — sizing that justifies server-side
  narrowing over in-memory scan. Revisit if the catalog stays in the low hundreds.
- Migrations are manual ALTER today (no Alembic) — enabling the extension + index is a
  migration step (`lik-mcp/db/init.sql`).

## Open Questions (for planning)

- New tool vs. extending an existing tool's surface.
- Default top-N and minimum similarity threshold.
- Whether `category` is also trigram-indexed or used only as an equality pre-filter.

## References

- `lik-mcp/src/lik_mcp/catalog.py:105-126` — current exact-match lookup + list
- `lik-mcp/src/lik_mcp/server.py:79-98` — MCP tool wrappers
- `lik-mcp/db/init.sql:7-34` — schema; existing GIN index on `access_groups`
- `v0.4/04-strategy.md:116-125` — Catalog design; line 120 permits optional partial/fuzzy matching on keys
- `v0.4/05-architecture.md:40-89` — Catalog as cache/directory
- `.claude/skills/query-project-index/SKILL.md:24-54` — Level 1/2/3 query escalation (Level 1 extended by this work)
