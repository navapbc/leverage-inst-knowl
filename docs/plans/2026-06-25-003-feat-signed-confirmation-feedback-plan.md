---
title: "feat: Signed confirmation feedback (thumbs up / down)"
type: feat
status: active
date: 2026-06-25
origin: docs/brainstorms/2026-06-25-03-signed-confirmation-feedback-requirements.md
---

# feat: Signed confirmation feedback (thumbs up / down)

## Summary

Extend the positive-only confirmation feature into a *signed* signal. The `confirmations` store, the `confirm_source` write path, the `read_confirmations` read path, and the Query skill all gain a vote direction, a down-vote reason (`bad-retrieval` | `wrong-content`), and an optional reason-agnostic free-text comment. The MCP service stays a raw signed-row store; the Query skill does the presentation-level soft-demote-and-explain. Net numeric ranking weighting is deferred — consistent with the existing "stub the hook, don't tune it" posture.

---

## Problem Frame

The strategy and architecture describe a signed (right/wrong) trust signal, but only the positive half exists in code. A user who sees a wrong or irrelevant cited source has no way to warn the next person; the bad source keeps getting retrieved with no counter-signal. This closes the implementation gap against intent already documented in Strategy §3.1/§3.2/§3.3 and Architecture §2/§4/§6 (see origin).

---

## Requirements

- R1. A user can vouch a cited source as right (positive) or wrong (negative). Bare source number = thumbs-up; trailing `-` = thumbs-down. (`+` accepted, redundant.)
- R2. A thumbs-down records a reason — `bad-retrieval` or `wrong-content` — stored distinctly, not collapsed into one "negative".
- R3. The store has a single reason-agnostic free-text comment field, usable by any feedback.
- R4. On `wrong-content`, the skill prompts for what's wrong, stores it in the comment field, and additionally offers the §6 correction flow.
- R5. On `bad-retrieval`, the skill records the demote with no required prompt; the comment field stays optionally available.
- R6. One current vote per user per source. Re-voting (flip up↔down or change reason) replaces the prior vote, never stacks.
- R7. Writes go through the service account under the user's verified identity (`confirmed_by`); users never write directly. Citation-as-join-key and content-state marker capture unchanged.
- R8. Negative signals soft-demote and annotate; positive boost. Neither hides a record the user is entitled to — trust advises, never gates.
- R9. When a source is demoted by negative feedback, the Query skill explains the demotion using the reason kind and the free-text note.
- R10. Negative signals share the positive lifecycle: edited-since and recency aging (aging itself remains unimplemented for both directions — see Scope Boundaries).

**Origin actors:** A1 (Asker), A2 (Future asker), A3 (Query skill), A4 (Service account)
**Origin flows:** F1 (Give feedback on a cited source), F2 (Demotion explained at query time)
**Origin acceptance examples:** AE1 (R1), AE2 (R1,R2,R4), AE3 (R5), AE4 (R6), AE5 (R8,R9)

---

## Scope Boundaries

- Auto-correcting the DS on wrong-content is out — correction stays user-driven under the user's own SSO (§6 unchanged).
- The free-text note is solicited only on wrong-content; not prompted on bad-retrieval or up-votes (field merely exists for them).
- More than two down-reasons is out — exactly `bad-retrieval` and `wrong-content`.
- Numeric net-ranking weighting (Strategy §3.2 stage C) is **not** built. The skill applies stage A (presentation) + B (staleness soft-demote). This mirrors the unbuilt state of positive-side min-distinct-voters and recency aging.

### Deferred to Follow-Up Work

- Recency aging / archival window for both positive and negative signals (`archived_at` column exists, unused) — separate slice, as it always was.
- Min-distinct-voters threshold before negative trust affects ranking — same unbuilt hook as positive side.

---

## Context & Research

### Relevant Code and Patterns

- `lik-mcp/db/init.sql:50-61` — `confirmations` table. UNIQUE `(confirmed_by, store_kind, location, locator)` already gives one-vote-per-user-per-source (R6); marker (`source_state`) is non-key state.
- `lik-mcp/src/lik_mcp/confirmations.py:37-67` — `confirm_source` upsert (`ON CONFLICT … DO UPDATE`). The `DO UPDATE` set-list must also overwrite the new columns so a flip replaces cleanly.
- `lik-mcp/src/lik_mcp/confirmations.py:46-97` — `read_confirmations` + `ConfirmationRow` model.
- `lik-mcp/src/lik_mcp/citations.py:9-34` — `Citation` is `extra="forbid"`, so new fields are separate tool params / a new model, **not** smuggled onto the citation.
- `lik-mcp/src/lik_mcp/server.py:123-153` — `confirm_source` / `read_confirmations` tool wiring; verified-identity write via `_authorize`.
- `.claude/skills/lik-query-project-index/SKILL.md:104-123` — read/rank + positive-only Confirm offer.
- `lik-mcp/tests/test_confirmations.py` — existing suite + `db` fixture (`tests/conftest.py`, `_test`-suffix gate).

### Institutional Learnings

- Input-field name == DB column (e.g. `Citation.source_state`); no translation layer. New `vote`/`reason`/`comment` follow this.
- Extend `confirm_source`/`read_confirmations` — never add a parallel "downvote" tool (no raw-SQL escape hatch; intent-named tools only).
- Marker is an opaque equality token, not in the dedup key. Reason-agnostic comment field must not bind its name to "wrong-content".
- Ranking lives as natural-language instructions in the Query skill, not Python — there is no boost/voter/aging code today. Keep it that way.
- DB schema changes: drop-and-recreate (`docker compose down -v && docker compose up -d`), no migration script (project in drafting mode).

---

## Key Technical Decisions

- **Vote direction as a `vote` text column** (`up`|`down`, CHECK-constrained), default `up`: readable, keeps the positive path ergonomic, store-agnostic. Rejected a boolean (`is_positive`) — less legible in raw SQL and at the tool boundary.
- **`reason` nullable text, CHECK `('bad-retrieval','wrong-content')`**, with a row-level CHECK that reason is present iff `vote='down'`: enforces R2 + the "reason required on down, absent on up" rule at the store, not just the skill.
- **`comment` nullable text, reason-agnostic** (R3): named generically so any feedback can carry a note later.
- **Wire form = kebab strings** (`up`/`down`, `bad-retrieval`/`wrong-content`): matches Strategy §3.1 prose and the origin AEs; no integer enums.
- **MCP returns raw signed rows; skill computes the net** (open Q "single net score vs. separate weighted terms"): resolved as *separate signals surfaced, skill applies presentation + staleness soft-demote*. No numeric net-score function in code. Rationale: consistent with the existing posture (ranking is skill prose), avoids tuning a weight before volume justifies it, keeps the service a dumb durable store.
- **New tool params, not a new payload model on `Citation`**: `Citation` is `extra="forbid"`; `vote`/`reason`/`comment` are added as `confirm_source` tool arguments alongside the citation.

---

## Open Questions

### Resolved During Planning

- Column names/shape (origin Q "Affects R3"): `vote`, `reason`, `comment` — see Key Technical Decisions.
- Net ranking combination (origin Q "Affects R8"): separate weighted terms surfaced raw; skill does presentation + staleness soft-demote; numeric weighting deferred — see Key Technical Decisions + Scope Boundaries.
- Reason enum / wire form (origin Q "Affects R2"): kebab strings, CHECK-constrained.

### Deferred to Implementation

- Exact `ConfirmResult.reason` rejection string for a malformed down-vote (e.g. `missing_reason` vs `invalid_reason`) — name when writing U2.
- Whether `read_confirmations` returns a small aggregate (positive/negative counts) alongside rows, or the skill counts from rows — decide while wiring U3 against the skill's actual needs; default to rows-only to stay minimal.

---

## Implementation Units

- U1. **Add signed-feedback columns to the confirmations store**

**Goal:** The store can hold a vote direction, a down-reason, and a reason-agnostic comment, with integrity enforced at the DB.

**Requirements:** R1, R2, R3, R6, R7

**Dependencies:** None

**Files:**
- Modify: `lik-mcp/db/init.sql`

**Approach:**
- Add to `confirmations`: `vote text NOT NULL DEFAULT 'up'`, `reason text`, `comment text`.
- Add CHECK: `vote IN ('up','down')`.
- Add CHECK: `(vote='down' AND reason IN ('bad-retrieval','wrong-content')) OR (vote='up' AND reason IS NULL)`.
- Leave the UNIQUE dedup key unchanged — one-vote-per-user-per-source already holds; a flip is an upsert on the same key.
- Drop-and-recreate the DB rather than migrating (project drafting mode).

**Patterns to follow:**
- Existing column/comment style in `lik-mcp/db/init.sql:44-61`; `source_state` NOT-NULL-DEFAULT precedent for keeping dedup reliable.

**Test scenarios:**
- Test expectation: none — pure DDL. Integrity is exercised by U2/U3 behavior tests (a down-vote with no reason and an up-vote with a reason are validated in the write path; the DB CHECK is the backstop).

**Verification:**
- `docker compose down -v && docker compose up -d` applies cleanly; the new columns and CHECKs exist on `confirmations`.

---

- U2. **Extend `confirm_source` to record signed votes**

**Goal:** A caller can record an up-vote, or a down-vote with a reason and optional comment, replacing the user's prior vote on that source.

**Requirements:** R1, R2, R3, R4, R5, R6, R7

**Dependencies:** U1

**Files:**
- Modify: `lik-mcp/src/lik_mcp/confirmations.py`
- Modify: `lik-mcp/src/lik_mcp/server.py`
- Test: `lik-mcp/tests/test_confirmations.py`

**Approach:**
- Add `vote` / `reason` / `comment` params to `confirm_source` (business fn) and the `_confirm_source` MCP tool — separate args, not on `Citation` (`extra="forbid"`).
- Validate before write: down requires a valid `reason`; up forbids a `reason`; `comment` optional in both. On violation return `ConfirmResult(status="rejected", reason=<name>)` (don't rely solely on the DB CHECK) so the skill gets a clean signal.
- Extend the upsert `DO UPDATE` set-list to overwrite `vote`, `reason`, `comment` (and keep `source_state`, `created_at=now()`) so a flip / reason-change fully replaces the prior vote (R6).
- Keep unresolvable-citation rejection unchanged (R7).
- Generalize the tool docstring from "was right" to the signed framing.

**Patterns to follow:**
- Upsert + verified-identity write at `confirmations.py:37-67` / `server.py:123-134`; `confirmed_by` from `identity.email`, never self-asserted; never log the token.

**Test scenarios:**
- Covers AE1. Happy path: up-vote (`vote='up'`, no reason) records one positive row.
- Covers AE3. Happy path: down-vote `bad-retrieval` with no comment records a negative row, reason stored, comment null.
- Covers AE2. Happy path: down-vote `wrong-content` with a comment stores reason + the note text.
- Covers AE4 / R6. Re-vote: existing up-vote then `2-`/`bad-retrieval` → exactly one row for that user+source, now negative with the reason (not two rows).
- Edge case: re-vote changing only the reason (`wrong-content` → `bad-retrieval`) replaces in place and clears/updates the comment as sent.
- Error path: down-vote with missing/empty reason → `status="rejected"` (reason name TBD), no row written.
- Error path: down-vote with an out-of-enum reason → rejected, no row.
- Error path: up-vote carrying a reason → rejected (reason must be absent on up).
- Error path: unresolvable citation → `rejected`/`unresolvable_citation`, unchanged.
- Edge case: comment present on an up-vote is accepted and stored (reason-agnostic field, R3).

**Verification:**
- `uv run pytest tests/test_confirmations.py` passes; a flip leaves one row; malformed votes write nothing.

---

- U3. **Return signed fields from `read_confirmations`**

**Goal:** The read path exposes each row's vote, reason, and comment so the Query skill can soft-demote and explain.

**Requirements:** R8, R9, R10

**Dependencies:** U1

**Files:**
- Modify: `lik-mcp/src/lik_mcp/confirmations.py`
- Test: `lik-mcp/tests/test_confirmations.py`

**Approach:**
- Add `vote`, `reason`, `comment` to `ConfirmationRow` and to the `_SELECT` column list.
- Preserve existing matching (store_kind + location + locator, `archived_at IS NULL`, ordered `created_at, id`) and the existing `edited_since` computation (negative signals inherit edited-since unchanged — R10).
- Default to rows-only (no server-side aggregate) per the deferred decision; revisit only if U4 proves it awkward.

**Patterns to follow:**
- `ConfirmationRow` / `_SELECT` / `read_confirmations` at `confirmations.py:14-97`; `edited_since` None-means-unknown semantics preserved.

**Test scenarios:**
- Happy path: a source with one up and one down returns both rows carrying their `vote`/`reason`/`comment`.
- Happy path: a `wrong-content` row returns its stored comment verbatim (feeds AE5's explanation).
- Edge case: `edited_since` still computed correctly for a negative row when `current_source_state` is supplied (marker match/mismatch), and stays None when omitted.
- Edge case: up-vote row returns `reason=None`, `comment` as stored (possibly null).

**Verification:**
- `uv run pytest tests/test_confirmations.py` passes; returned rows expose the signed fields with edited-since intact.

---

- U4. **Signed feedback in the Query skill (offer, follow-up, demotion explanation)**

**Goal:** The skill offers `2` / `2-` feedback, runs the down follow-up (reason pick, wrong-content note + §6 correction offer), and at query time soft-demotes flagged sources with an explanation — never hiding them.

**Requirements:** R1, R2, R4, R5, R8, R9, R10

**Dependencies:** U2, U3

**Files:**
- Modify: `.claude/skills/lik-query-project-index/SKILL.md`

**Approach:**
- Rewrite the Confirm offer (`SKILL.md:115-122`): bare number = up, trailing `-` = down (`+` accepted, redundant). On a down, one quick pick — `bad-retrieval` or `wrong-content`. On `wrong-content`, prompt "what's wrong", pass it as `comment`, and offer the §6 correction path (guide the user to fix the DS record under their own SSO). On `bad-retrieval`, record with no required prompt.
- Pass `vote`/`reason`/`comment` to `confirm_source` with the user's email as token (verified `confirmed_by`); report `recorded` / `rejected` (rejected = don't retry).
- Extend the Rank & present section (`SKILL.md:104-113`): when read rows carry negatives, soft-demote the source and annotate *why* — reason kind + note (e.g. "flagged by N — *<note>*"); positives boost; never hide (R8). Apply staleness gating (edited-since) to negatives as to positives (R10).
- Keep all wording/UX in the skill (architecture rule: design docs stay implementation-free; UI lives in the skill).

**Patterns to follow:**
- Existing offer + result-reporting prose at `SKILL.md:115-123`; edited-since annotation style at `SKILL.md:111-113`; Strategy §3.2 stages A+B for "presentation + staleness, defer ranking".

**Test scenarios:**
- Test expectation: none (Markdown skill instructions, no automated test harness). Validate against AEs by walkthrough — see Verification.

**Verification:**
- Walk the origin AEs by hand: AE1 (`2`→positive), AE2 (`2-`/wrong-content/note→negative + correction offer), AE3 (`3-`/bad-retrieval→negative, no note), AE4 (flip→one vote), AE5 (future query shows the source demoted-not-hidden with the note in the explanation).
- Offer text reflects one-keystroke-beyond-the-number and at most one follow-up pick.

---

- U5. **Confirm v0.4 docs carry no positive-only language**

**Goal:** The design docs match the shipped signed signal (success criterion: "no remaining positive-only language").

**Requirements:** R1–R10 (traceability/consistency)

**Dependencies:** U2, U3, U4

**Files:**
- Modify (verify, edit only if gaps): `v0.4/04-strategy.md`, `v0.4/05-architecture.md`

**Approach:**
- The working tree already generalizes Strategy §3.1/§3.2/§3.3 and Architecture §2/§4/§6 to the signed model. Scan for any residual positive-only phrasing ("confirm … was right", "positive feedback", boost-only language) and reconcile against the implemented vote/reason/comment shape.
- Keep docs implementation-free — no column names, tool signatures, or UI syntax (that lives in code / SKILL.md).

**Patterns to follow:**
- Existing signed phrasing at `v0.4/04-strategy.md:97-115` and `v0.4/05-architecture.md:22,105,122`.

**Test scenarios:**
- Test expectation: none — documentation. Verified by review.

**Verification:**
- `grep -ni "positive feedback\|was right\b\|right and useful"` across `v0.4/` surfaces nothing implying positive-only; the signed model reads consistently across both docs.

---

## System-Wide Impact

- **Interaction graph:** `confirm_source` and `read_confirmations` tools (server) → `confirmations.py` business fns → `confirmations` table; Query skill consumes read rows. No other tool touches confirmations.
- **Error propagation:** Malformed down-votes reject at the write path with a named `ConfirmResult.reason`; the DB CHECK is a backstop. The skill surfaces `rejected` and does not retry.
- **State lifecycle risks:** A flip must fully replace the prior vote (upsert `DO UPDATE` overwriting vote/reason/comment) — a partial set-list would leave a stale reason/comment on a flipped vote. Covered by U2 re-vote tests.
- **API surface parity:** Only the confirmation tools change; the catalog tools are untouched. The `Citation` shape is unchanged (new fields are separate params), so existing callers that send only a citation still work for up-votes (default `vote='up'`).
- **Integration coverage:** Re-vote (flip) one-row invariant and edited-since on negatives are the cross-layer behaviors unit tests must prove (U2/U3).
- **Unchanged invariants:** Citation join key, content-state marker semantics, verified-identity write, unresolvable-citation rejection, one-row-per-user-per-source UNIQUE key — all preserved.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Partial upsert leaves stale reason/comment after a flip | U2 explicitly extends the `DO UPDATE` set-list; re-vote tests assert the replaced values. |
| Skill and store disagree on reason enum strings | Single kebab vocabulary (`bad-retrieval`/`wrong-content`) defined once; DB CHECK + write-path validation enforce it; skill passes the same literals. |
| Over-building ranking (numeric net score) beyond current volume | Explicitly out of scope; skill stays at presentation + staleness (stages A+B), matching the unbuilt positive-side hooks. |
| Doc edits drift from implemented shape | U5 reconciles `v0.4/` after the code lands. |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-25-03-signed-confirmation-feedback-requirements.md](docs/brainstorms/2026-06-25-03-signed-confirmation-feedback-requirements.md)
- Related plan: [docs/plans/2026-06-25-002-refactor-confirmation-content-state-marker-plan.md](docs/plans/2026-06-25-002-refactor-confirmation-content-state-marker-plan.md)
- Code: `lik-mcp/src/lik_mcp/confirmations.py`, `lik-mcp/src/lik_mcp/citations.py`, `lik-mcp/src/lik_mcp/server.py`, `lik-mcp/db/init.sql`
- Skill: `.claude/skills/lik-query-project-index/SKILL.md`
- Design: `v0.4/04-strategy.md` §3.1–§3.3, `v0.4/05-architecture.md` §2/§4/§6
