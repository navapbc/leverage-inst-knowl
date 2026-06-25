---
date: 2026-06-25
topic: signed-confirmation-feedback
---

# Signed Confirmation Feedback (thumbs up / down)

## Summary

Make the confirmation signal *signed*: a person can vouch that a cited source was right (thumbs-up) or wrong (thumbs-down), with the least typing possible. A thumbs-down records a reason — *bad retrieval* or *wrong content* — and wrong-content captures a free-text note and offers the existing correction path. At query time the skill demotes flagged sources and explains why, using the note.

---

## Problem Frame

The strategy and architecture already promise two-way feedback — Architecture §4 ("users confirm whether a cited source was right or wrong") and Strategy §3.1 ("a person vouching that a cited source... was right or wrong") — but nothing downstream models the negative half. The confirmation store, the confirm path, and the §3.2 query-time ranking stages all assume positive-only trust. A user who sees a wrong or irrelevant source cited has no way to warn the next person; the bad source keeps getting retrieved with no counter-signal, and the docs describe a capability the system can't perform.

This is an inconsistency to close, not a net-new capability invented from nothing: the product intent ("right or wrong") predates the implementation gap.

---

## Actors

- A1. **Asker** — the person who got an AI answer with cited sources and gives feedback on them.
- A2. **Future asker** — later consumer whose ranking and explanations are shaped by A1's feedback.
- A3. **Query skill** — reads accumulated signals at query time, demotes flagged sources, and explains demotions.
- A4. **Service account** — writes the signal under A1's verified identity (users never write directly).

---

## Key Flows

- F1. **Give feedback on a cited source**
  - **Trigger:** after an answer, the skill offers feedback on its numbered citations.
  - **Actors:** A1, A4
  - **Steps:**
    1. User replies with a source number alone for thumbs-up (e.g. `2`).
    2. For thumbs-down, user appends `-` (e.g. `2-`).
    3. On a down, the skill asks one quick pick: **bad retrieval** or **wrong content**.
    4. On **wrong content**, the skill asks what's wrong and captures the free-text note; it also offers the §6 correction path (guide the user to fix the underlying DS record under their own SSO).
    5. Service account records the signal (kind + reason + optional note) under the user's verified identity, against the same citation/content-state marker positive confirmations use.
  - **Outcome:** the user's single current vote for that source is stored or replaced.
  - **Escape:** an unresolvable citation is rejected (same as today); the skill says so and doesn't retry.

- F2. **Demotion explained at query time**
  - **Trigger:** a query surfaces a source that carries negative signals.
  - **Actors:** A2, A3
  - **Steps:** the skill weighs the signal, soft-demotes the source, and annotates *why* — the reason kind and, when present, the free-text note.
  - **Outcome:** the future asker sees the demotion and its rationale; the source is never hidden.

---

## Requirements

**Feedback capture**
- R1. A user can vouch a cited source as right (positive) or wrong (negative). A bare source number is a thumbs-up; a trailing `-` is a thumbs-down. (`+` is accepted but redundant.)
- R2. A thumbs-down records a reason, one of: **bad retrieval** (poor/irrelevant result) or **wrong content** (the source is factually wrong). The reason is stored distinctly, not collapsed into a single "negative".
- R3. The store has a single reason-agnostic free-text comment field, usable by any feedback regardless of reason.
- R4. On **wrong content**, the skill prompts the user to describe what's wrong and stores that text in the comment field, and additionally offers the §6 correction flow (fix the underlying DS record under the user's SSO).
- R5. On **bad retrieval**, the skill records the demote signal with no required prompt; the comment field stays optionally available.
- R6. A user holds one current vote per source. Re-voting (including flipping up↔down or changing reason) replaces their prior vote rather than stacking a second.
- R7. Writes go through the service account under the user's verified identity (`confirmed_by`); users never write directly. Citation-as-join-key and content-state marker capture are unchanged from positive confirmations.

**Query-time use**
- R8. Negative signals **soft-demote** a source and annotate it; positive signals boost. Neither ever hides a record the user is entitled to — trust advises, never gates.
- R9. When a source is demoted by negative feedback, the Query skill explains the demotion using the reason kind and the free-text note.
- R10. Negative signals are subject to the same lifecycle as positive: edited-since (a changed source's prior signal no longer cleanly applies) and recency aging. A wrong-content signal whose source is later corrected ages out / archives like §3.3.

---

## Acceptance Examples

- AE1. **Covers R1.** Given an answer citing sources 1–3, when the user replies `2`, then source 2 is recorded as a positive confirmation.
- AE2. **Covers R1, R2, R4.** Given the same answer, when the user replies `2-` and picks *wrong content* and types "states the 2019 rate, superseded in 2022", then a negative signal is stored with reason `wrong-content` and that note, and the skill offers to help correct the DS record.
- AE3. **Covers R5.** Given `3-` and pick *bad retrieval*, then a negative signal is stored with reason `bad-retrieval` and no note required.
- AE4. **Covers R6.** Given a user previously thumbed-up source 2, when they later reply `2-` / *bad retrieval*, then their vote becomes the negative one — there is one row for that user+source, not two.
- AE5. **Covers R8, R9.** Given a future query surfaces a source carrying a wrong-content signal, then the skill returns the source demoted, not hidden, with an explanation citing the stored note.

---

## Success Criteria

- A user can express positive or negative feedback in one keystroke beyond the source number (`2` or `2-`), with at most one follow-up pick on a down.
- A future asker sees *why* a source was demoted, not just that it ranked lower.
- Architecture §2/§4/§6 and Strategy §3.1/§3.2/§3.3 describe a signed signal with no remaining positive-only language.
- ce-plan can implement without inventing feedback semantics, reason taxonomy, or query-time behavior.

---

## Scope Boundaries

- Auto-correcting the DS on wrong-content is out — correction stays user-driven under their own SSO (§6 unchanged).
- The free-text note is solicited only on wrong-content; it is not prompted on bad-retrieval or on up-votes (the field merely exists for them).
- More than two down-reasons is out — exactly *bad retrieval* and *wrong content*.
- Concrete schema (column names, types), tool signatures, and the SKILL.md offer wording are ce-plan / implementation work, not this brainstorm.

---

## Key Decisions

- **Signed confirmation, not a separate "dispute" entity:** negative feedback reuses the confirmation model (citation join key, content-state marker, one-row-per-user-per-source, service-account write). Rationale: minimal new surface, store-agnostic, and consistent with the existing positive path.
- **Two reasons, captured distinctly:** the write model (§6) already splits "wrong content" (→ DS correction) from a retrieval-quality signal (stays in DL). Storing the reason lets the skill route and explain correctly.
- **Reason-agnostic comment field:** named generically so any feedback can carry a note later, rather than binding the column to wrong-content.
- **Soft-demote + explain, never hide:** preserves "trust advises, never gates" for the negative direction.

---

## Dependencies / Assumptions

- Depends on the existing confirmation store and confirm/read path (Strategy §3.1, Architecture §2).
- Follow-on edits beyond the two architecture docs: the `confirm_source` tool/store (gain reason + comment), the `read` path (return them), and the Query skill SKILL.md (offer wording, down follow-up, demotion explanation). Tracked as implementation, not part of this doc's doc-consistency edits.
- Min-distinct-voters and recency-window guards that gate positive trust's ranking effect apply to negative too.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R3][Technical] Exact column name/shape for the reason and the comment field.
- [Affects R8][Technical] How negative and positive combine into a net ranking adjustment (single net score vs. separate weighted terms).
- [Affects R2][Technical] Enum values / wire form for the two reasons.
