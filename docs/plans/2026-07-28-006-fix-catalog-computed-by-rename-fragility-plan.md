---
title: "fix: Catalog computed_by must survive a skill rename"
type: fix
status: active
date: 2026-07-28
---

# Catalog `computed_by` must survive a skill rename

## Summary

`computed_by` on a `catalog` row is both the "which skill owns this row" label **and** part of the
skill-row upsert key (`catalog_skill_key` unique index on `(entry_type, subject, computed_by) WHERE
row_provenance='skill'`). It currently stores the skill's **display name**, which is mutable. When a
skill is renamed, its `computed_by` literal changes, so a sync no longer matches the existing rows —
it **inserts duplicates** instead of upserting in place, and the old rows are orphaned under a name
no skill writes anymore.

## Incident that motivated this

The `lik-` prefix removal renamed `lik-sync-catalog-from-project-indexes` →
`sync-catalog-from-project-indexes` (skill dir + `computed_by` literal in its SKILL.md), but the 111
existing prod catalog rows still carried the old `computed_by`. A sync run wrote the new literal and
inserted 10 duplicate rows (ids 222–231) before the agent noticed the mismatch and course-corrected
to the old key by hand. Cleaned up manually service-side (deleted the 10 dupes, migrated all 111 to
the new name) — but nothing prevents a recurrence on the next rename.

## Problem Frame

- `computed_by` couples two concerns: **ownership/identity** (stable) and **display name** (mutable).
- The upsert key depends on the mutable one, so identity breaks exactly when a name changes.
- There is no delete/dedup tool exposed to the skill, so a mismatch requires manual DB surgery.
- No automated guard notices that a sync inserted N new rows where it expected N updates.

## Options (to decide)

1. **Document-only:** add a rule — renaming a catalog-writing skill requires a `computed_by` data
   migration — to the skill-rename checklist / CLAUDE.md. Cheap, but relies on humans remembering the
   exact failure we just hit.
2. **Stable owner key (preferred):** key skill rows on a stable identifier that does not change with
   the display name (e.g. a slug the skill declares once and never renames, or a dedicated
   `owner_key` column separate from the human-facing `computed_by`). The upsert becomes rename-safe.
3. **Guard rail:** have the sync assert its expected update/insert counts (it knows how many pages it
   matched to existing rows) and fail loudly if it starts inserting where it expected updates — turns
   a silent duplicate spray into an immediate, obvious error.

Likely: (2) as the real fix, (3) as a cheap belt-and-suspenders, (1) folded into whichever ships.

## Scope Boundaries

- Not re-litigating the `lik-` prefix removal itself (that convention stands — skills carry no
  prefix). This is about the data/key design surviving *any* rename, not reverting this one.
- The one-time prod data reconciliation is already done (111 rows now under
  `sync-catalog-from-project-indexes`, 0 duplicates); this plan is prevention, not that cleanup.

## Related / adjacent (separate issue)

- The scheduled-runs scanner holds one idle DB connection across the whole multi-minute agent run and
  the terminal `complete_run` fails with `SSL error: unexpected eof` when the idle connection is
  dropped (observed in Actions run 30409045516). Not a `computed_by` issue — tracked separately — but
  both surfaced in the same catalog-sync reliability push.

## References

- Manual reconciliation: catalog rows migrated `lik-sync-catalog-from-project-indexes` →
  `sync-catalog-from-project-indexes`, dupes 222–231 deleted.
- Upsert + key: [lik-mcp/src/lik_mcp/catalog.py](../../lik-mcp/src/lik_mcp/catalog.py) (`_UPSERT`,
  `catalog_skill_key`), [lik-mcp/db/init.sql](../../lik-mcp/db/init.sql).
- Skill literal: `claude_platform/skills/sync-catalog-from-project-indexes/SKILL.md` (Step 3,
  `computed_by`).
