---
title: "feat: Ad-hoc Catalog registration skill (adhoc-catalog-registration)"
type: feat
status: active
date: 2026-07-29
origin: docs/brainstorms/2026-07-29-02-ad-hoc-catalog-registration-requirements.md
---

# feat: Ad-hoc Catalog registration skill (adhoc-catalog-registration)

## Summary

Add a new agent-facing skill, `adhoc-catalog-registration`, that lets an end-user register an existing Data Source
record (a Confluence page or a Google doc/sheet) into the Discovery Layer Catalog mid-chat as a **human-owned** row
(`row_provenance = human`), attributed to their verified SSO identity. It composes the two MCP tools that already exist —
a Data Source fetch and `register_catalog_entry` — so **no backend work is required**. Alongside the skill, wire it into
the Catalog Registration Agent and reconcile a few small residuals in the `v0.5/` design docs (the bulk of the doc work
already landed in commit `1267822`).

---

## Problem Frame

While chatting, a user may know the entry points (records) for a topic (a team onboarding page, a canonical
spec, a rollup sheet), but the only automated way a record enters the Catalog is a producer skill marking a record and
the registrar discovering it by that marker. The one human path that exists (Level 4 saved synthesis) is scoped to an
answer the agent *just authored in-session*. The gap: a user cannot promote a **pre-existing** record to one-lookup
discovery without waiting for a producer skill to be built for that source. The cost is coverage latency — good entry
points stay undiscoverable. (See origin: docs/brainstorms/2026-07-29-02-ad-hoc-catalog-registration-requirements.md.)

**Late-breaking scope correction (leads the plan):** The requirements doc lists v0.5 doc edits as "the core of the
original ask," but those edits already landed in commit `1267822 docs(v0.5): add manual (human) Catalog-registration
path`, made the same day *after* the requirements doc was written. Concept 4's two-path split, the marker-optional §2
language, the §3/§4 data-flow prose, and five of six open questions all already exist. **The real remaining deliverable
is the skill itself, which does not exist yet.** This plan treats the skill as primary and scopes doc work down to the
genuine residuals (U3).

---

## Requirements

Carried from origin (R-IDs preserved):

- R1. Register an *existing* DS record the user points at as a **human-owned** Catalog row (`row_provenance = human`),
  attributed to the user's verified identity.
- R2. Registering **designates** the target an entry-point DL record. Tagging the source `discovery-layer` is
  **optional** — offered only with write access and user opt-in. The Catalog row is the authoritative record of the role.
- R3. **Write access to the target is not required** — a user can register a page they can only read.
- R4. Guide the user to an `entry_type` from the **established vocabulary** describing *what the record is*. Never
  invent a registration-specific type (`manual`/`ad-hoc`); coining a brand-new `entry_type` is deliberate and
  discouraged-by-default (a novel key nobody queries is undiscoverable).
- R5. Ask **vouching vs. flagging a pointer**, and set `verification` accordingly (`human-verified` with the user as
  verifier, or `unverified`). Framed as a **ranking** choice — vouched rows sort as the default entry point on their key.
- R6. Default `provenance` silently (no user decision) — it drives no consumer or ranking behavior for a human row.
- R7. Populate remaining fields from the fetched record: the pointer + how to fetch it, a content-state marker for
  staleness detection, and an audience no broader than the source (default-deny if unspecified). `computed_by` = the
  skill's own name.

Derived during planning:

- R8. The skill is **store-agnostic**: it works for any store the running agent can fetch (Confluence, Google
  doc/sheet in v1), recording the correct `store_kind` literal and a store-appropriate content-state marker — no logic
  pinned to one source's quirks.

**Origin actors:** A1 (End-user — points at the record, chooses the key and vouch), A2 (Agent running the skill —
fetches, proposes the key, populates fields, calls the tool), A3 (Governed writer — existing; performs the write under
the user's SSO identity).
**Origin flows:** F1 (Register an existing record as an entry point).
**Origin acceptance examples:** AE1 (covers R5 — vouched second row outranks a skill row on the same key), AE2 (covers
R2, R3 — read-only page registers, source left untagged), AE3 (covers R4 — novel `entry_type` requires deliberate
confirmation), AE4 (covers R5 — "just a pointer" → `unverified`, ranks below vouched).

---

## Scope Boundaries

- No new backend or MCP tool work. The existing `register_catalog_entry` + DS fetch tools and the governed-writer path
  suffice (verified against live code).
- No new offline `sync-catalog`/producer skill on user request (that is a dev+deploy workflow, not a runtime feature).
- No automatic re-derivation or maintenance of ad-hoc rows. Human-owned rows are never re-derived by design; staleness
  is surfaced to the owner, as for any human row.
- No bulk/batch registration. One record at a time, initiated in conversation.
- No spam/quality-gating, row cap/expiry, or key-metadata validation logic in this iteration — recorded as open
  questions only (already present in `08-open-questions.md`; U3 optionally adds a distinct spam/abuse bullet).

### Deferred to Follow-Up Work

- Actual **deployment** of the skill + agent to the Claude platform: run the `Deploy agents to Claude platform` action
  (`deploy_agents.py`, which republishes referenced skills) after this PR merges. This is a manual dispatch, not a code
  change — see Documentation / Operational Notes.
- FAQ mention of the feature (`lik-ui/src/lik_ui/faq.md`) — confirm with the user whether to add it (per CLAUDE.md); a
  one-line unit (U4) is included but is low-cost and may be dropped.

---

## Context & Research

### Relevant Code and Patterns

- `claude_platform/skills/sync-catalog-from-project-indexes/SKILL.md` — the closest sibling and the structural template:
  frontmatter (`name` == folder, lowercased), numbered `## Step N` prose, the **field-list-under-tool-name** shape for
  `register_catalog_entry` (its Step 3, lines ~189–210), the **content-state marker recipe** (SHA-256 of verbatim
  markdown body), the **Response integrity guard**, and the "hold back and ask / never block" interaction pattern. The
  new skill mirrors its shape but **flips** `row_provenance` to `human`, omits `refresh_due_at`/`last_computed_at`, and
  sets `verification` from a vouch question rather than an Update-History table.
- `claude_platform/skills/query-org-guidance/SKILL.md` — the "confirm the exact source (title + last-updated) before
  acting" and single-letter/number choice interaction patterns to reuse for the vouch confirmation.
- `lik-mcp/src/lik_mcp/catalog.py` — `CatalogEntry` model + `register_catalog_entry`. Key facts verified against code:
  - `computed_by` is **required, no default** (a bare `str`); passing the skill name satisfies it. Resolves the origin's
    deferred "computed_by constraint" question — **no tool change needed**.
  - Upsert conflict clause `ON CONFLICT (entry_type, subject, computed_by) WHERE row_provenance = 'skill'` — human rows
    are **excluded**, so **every human registration INSERTs a new row**; duplicates on a key coexist as ranked rows.
    Superseding an earlier human row is a separate deliberate write.
  - Lookup ranking: `ORDER BY (verification = 'human-verified') DESC, freshness, updated_at DESC` — confirms R5's vouch
    choice is consumer-facing (AE1/AE4).
  - `refresh_due_at` / `last_computed_at` default to a value **only when `row_provenance='skill'`** — human rows keep
    null (never scheduled for re-derivation). The skill must leave these unset.
  - `store_kind` enum in code + `citations.py` `KNOWN_STORE_KINDS`: `gdoc | gsheet | confluence | postgres | bigquery`.
    **There is no `gdrive`.** The skill must use `confluence` / `gdoc` / `gsheet`.
  - `sensitivity` enum `restricted | cleared`, default `restricted`. `access_groups` is the audience hint (never trusted
    for enforcement).
- `lik-mcp/src/lik_mcp/server.py` — identity is **server-stamped** from the verified bearer token into `updated_by`; the
  caller must **not** pass identity in the payload.
- `claude_platform/agents/catalog-registration.yaml` — the agent that must reference the new skill. Today `skills:`
  lists only `sync-catalog-from-project-indexes`; `mcp_servers` wires `lik-mcp` + `atlassian`; the `system` prompt says
  "This is the only cataloging skill for now." Google doc/sheet support needs the `google-drive-drivemcp` server
  (`https://drivemcp.googleapis.com/mcp/v1`, as wired in `claude_platform/agents/knowledge-search.yaml`).
- `scripts/README.md`, `scripts/deploy_skills.py`, `scripts/deploy_agents.py` — upload rules: single top-level folder
  named exactly `<skill-name>` matching the `name:` frontmatter (lowercased), or the upload 400s.

### Institutional Learnings

- `docs/solutions/` is nearly empty for this domain (one tangential SSE-timeout entry). Durable knowledge lives in the
  brainstorms + CLAUDE.md. Worth a `/ce-compound` capture after this lands.
- CLAUDE.md skill-rename gotcha: a Catalog-writing skill's `name` becomes its `computed_by` literal. For **skill** rows
  it is part of the upsert key (rename → data migration). For **human** rows `computed_by` is audit-only and not in the
  upsert key, so a rename won't orphan them the same way — but pick the name deliberately anyway (chosen:
  `adhoc-catalog-registration`).

### External References

- None. This is internal skill authoring composing existing tools; no external research warranted.

---

## Key Technical Decisions

- **`created_by` does not exist; attribution lands in `updated_by`.** The origin's "Attribution resolved — the schema
  carries both `created_by` and `updated_by`" is **false against live code**: `init.sql` has only `created_at`,
  `updated_at`, `updated_by`. The server stamps the registrant's SSO email into `updated_by`. Since "no backend work"
  is in scope, U3 reconciles the doc (`05-architecture.md` §3) rather than adding a column. The skill relies on
  server-stamped `updated_by` for R1 attribution and passes no identity.
- **`provenance` left unset (accepts the tool's `ai-generated` default).** R6 says it drives nothing on a human row and
  is defaulted silently; leaving it unset is the minimal choice. Resolves the origin's deferred "provenance default when
  the target may be AI-generated" — the answer is "it does not matter for a human row, so do not ask or branch."
  *(Alternative considered: set `human-created`. Rejected — adds a decision/branch for zero behavioral effect.)*
- **`sensitivity` defaults to `restricted`; `cleared` only on explicit user signal.** Default-deny. The skill sets
  `cleared` only when the user explicitly indicates the target is broadly/publicly readable (mirrors the sync skill
  setting `cleared` for public project indexes). Resolves the origin's deferred sensitivity-default question for v1.
- **`access_groups` = user-chosen audience, no broader than the source; empty (default-deny) if unspecified.** Paired
  with `restricted` sensitivity, an unspecified audience yields the most conservative row.
- **`verification` from a vouch question, with confirm-the-source-first.** Before writing `human-verified`, the skill
  fetches the record and shows title + last-updated for the user to confirm it is the right target (mirrors the
  confirmation path's mis-citation guard). `unverified` = "just a pointer." Sets `verified_by`/`verified_at` only when
  vouching.
- **Novel-`entry_type` guardrail (AE3).** If the user proposes an `entry_type` outside the established vocabulary, the
  skill surfaces that the row will be hard to discover and requires deliberate confirmation rather than accepting it.
- **Content-state marker per store (R7).** Confluence → `source_refs=[{id: pageId, source_state: <SHA-256 of verbatim
  markdown body>}]` via the shared recipe + Response integrity guard. Google doc/sheet → the file's
  `modifiedTime`/version identifier as `source_state`. `source_state` is optional but populated so later staleness
  checks compare by equality.
- **Optional source tagging (R2).** Tagging the source `discovery-layer` (e.g. a Confluence label) is offered **only**
  when the user has write access and opts to make the role visible in the source; otherwise skipped. The row is
  authoritative regardless.
- **Skill/agent stay store-agnostic (R8).** The skill fetches via whatever DS MCP the agent has for the target and
  records the right `store_kind` literal; it does not hard-code one source's fetch tool.

---

## Open Questions

### Resolved During Planning

- `computed_by` NOT-NULL constraint — satisfied by passing the skill name; no tool change. (Origin deferred item.)
- `provenance` default — left unset; drives nothing on a human row. (Origin deferred item.)
- `sensitivity` default — `restricted`; `cleared` only on explicit user signal. (Origin deferred item.)
- Store-kind literal for Google Drive — `gdoc`/`gsheet`, never `gdrive`.
- Whether the Drive fetch-tool signature must be pinned — **no.** `store_kind` is a text routing hint; the agent fetches
  via its available Drive MCP. The only dependency is wiring `google-drive-drivemcp` into the agent (U2).

### Deferred to Implementation

- Exact Google Drive MCP tool name/args for fetching a doc/sheet's title, last-modified, and content — resolved when the
  skill is authored against the live `google-drive-drivemcp` server; the skill references it store-agnostically.
- Exact established `entry_type` vocabulary to guide users toward — enumerate from live Catalog contents / existing
  skills at authoring time (e.g. `index`, and whatever else is in use) rather than hard-coding a stale list.
- Spam/quality-gating, row cap/expiry, key-metadata validation — recorded as open questions only; not built now.

---

## Implementation Units

- U1. **Author the `adhoc-catalog-registration` skill**

**Goal:** Create the new SKILL.md that walks a user through registering a pre-existing DS record as a human-owned
Catalog row. This is the primary deliverable (satisfies F1 end-to-end).

**Requirements:** R1, R2, R3, R4, R5, R6, R7, R8

**Dependencies:** None (composes existing tools).

**Files:**
- Create: `claude_platform/skills/adhoc-catalog-registration/SKILL.md`

**Approach:**
- Frontmatter: `name: adhoc-catalog-registration` (== folder, lowercased); a trigger-heavy `description` naming the
  capability and the phrases that should invoke it ("register this page as the entry point for X", "add this doc to the
  catalog", "catalog this page") plus "Do NOT use" exclusions (not the project-index sync; not authoring a new
  producer skill).
- Prose mirrors `sync-catalog-from-project-indexes` structure. Suggested steps:
  1. **Resolve & fetch the target once** via the agent's DS MCP for that store (Confluence `getConfluencePage` markdown;
     Drive fetch for gdoc/gsheet). Apply the Response integrity guard. Read title, last-updated, content, and compute
     the store-appropriate content-state marker.
  2. **Propose `entry_type` (from established vocabulary) + `subject`;** user confirms/adjusts. Novel-`entry_type`
     guardrail per AE3.
  3. **Ask vouch vs. flag** → `verification`; confirm-the-source (show title + last-updated) before writing
     `human-verified`.
  4. **Ask audience** (`access_groups`), default-deny if unspecified; set `sensitivity` (`restricted` default,
     `cleared` only on explicit public signal).
  5. **Optional tagging:** only if write access + user opts in, tag the source `discovery-layer`; else skip.
  6. **Register** via `register_catalog_entry` with `row_provenance: "human"`, `computed_by:
     "adhoc-catalog-registration"`, the fields above, `source_refs` with the marker; **omit** `refresh_due_at` /
     `last_computed_at`; **omit** `provenance` (accept default); **pass no identity**.
  7. **Summary:** what was registered, its key, ranking (vouched/pointer), and whether the source was tagged.
- Reuse the shared content-state marker recipe and Response integrity guard by reference (do not duplicate the exact
  bytes-and-hashing prose beyond what is needed; keep store-agnostic).

**Execution note:** Author against the live tool field names in `lik-mcp/src/lik_mcp/catalog.py` — do not trust the
origin doc's field claims (it got `created_by` wrong).

**Patterns to follow:**
- `claude_platform/skills/sync-catalog-from-project-indexes/SKILL.md` (Step 3 field list, marker recipe, integrity
  guard, summary shape).
- `claude_platform/skills/query-org-guidance/SKILL.md` (confirm-source-before-acting, single-letter/number choices).

**Test scenarios:**
<!-- A skill is prose/config, not executable code. "Tests" here are dry-run walkthroughs against the live tool schema
     and the acceptance examples — there is no unit-test harness for SKILL.md. -->
- Covers AE2 (R2, R3). Walkthrough: a Confluence page the user can read but not edit → skill registers a
  `row_provenance=human` row and leaves the source untagged (no DS write). Verify the payload sets no marker/tag and
  requires no write access.
- Covers AE1 (R5). Walkthrough: a `(entry_type, subject)` key already has a skill row; user registers a second record
  and chooses "vouching" → payload sets `verification=human-verified`; per the lookup `ORDER BY`, the human row sorts
  above the skill row.
- Covers AE4 (R5). Walkthrough: user chooses "just a pointer" → `verification=unverified`; ranks below any vouched row.
- Covers AE3 (R4). Walkthrough: user proposes a novel `entry_type` no consumer queries → skill surfaces the
  discoverability warning and requires deliberate confirmation before proceeding.
- Field-population check (R6, R7): payload omits `provenance`, `refresh_due_at`, `last_computed_at`; sets
  `computed_by="adhoc-catalog-registration"`, `row_provenance="human"`, `store_kind` in {`confluence`,`gdoc`,`gsheet`}
  (never `gdrive`), `source_refs` with a content-state marker, `sensitivity="restricted"` by default, `access_groups`
  no broader than source.
- Attribution check (R1): payload carries **no** identity field; rely on server-stamped `updated_by`.
- Store-agnostic check (R8): the same step flow produces a valid row for a Google doc/sheet, differing only in
  `store_kind` and the marker derivation.

**Verification:** A dry-run of each acceptance example produces a `register_catalog_entry` payload consistent with the
live `CatalogEntry` schema and the decisions above; the skill never writes to a DS unless the user has write access and
opts into tagging; the skill never passes identity.

---

- U2. **Wire the skill into the Catalog Registration Agent**

**Goal:** Make the new skill runnable in a session and ensure the agent can fetch both Confluence and Google Drive
targets.

**Requirements:** R1 (the skill can only run when referenced), R8 (Drive fetch requires the Drive MCP).

**Dependencies:** U1 (skill must exist to reference by name).

**Files:**
- Modify: `claude_platform/agents/catalog-registration.yaml`

**Approach:**
- Add `adhoc-catalog-registration` to the agent's `skills:` list.
- Update the `system` prompt: describe the new capability (registering a user-designated pre-existing record as a
  human-owned entry point), and remove/adjust the "This is the only cataloging skill for now" line so the agent routes
  correctly between the two skills (sync = crawl+upsert project indexes; adhoc = register one record the user points
  at).
- Add the `google-drive-drivemcp` MCP server (`https://drivemcp.googleapis.com/mcp/v1`) to `mcp_servers` and a matching
  `mcp_toolset` entry, so gdoc/gsheet targets are fetchable. Mirror the block shape in
  `claude_platform/agents/knowledge-search.yaml`.

**Patterns to follow:**
- `claude_platform/agents/knowledge-search.yaml` (the `google-drive-drivemcp` server + toolset block).
- The existing `atlassian` / `lik-mcp` toolset blocks in this same file.

**Test scenarios:**
- Config validity: the YAML still parses and `deploy_agents.py` resolves both skill names to skill_ids (dry-run or local
  validation of the deploy script's name-resolution path).
- Routing: the updated `system` prompt distinguishes the two skills so a "register this page" request routes to
  `adhoc-catalog-registration`, not the project-index sync.
- MCP coverage: `mcp_servers` includes `lik-mcp`, `atlassian`, and `google-drive-drivemcp`, each with an enabled
  `mcp_toolset`.

**Verification:** Deploy dry-run resolves both skills; the agent spec lists all three MCP servers; the system prompt
names both cataloging skills and their distinct triggers.

---

- U3. **Reconcile residual v0.5 design-doc discrepancies**

**Goal:** Close the small gaps left after commit `1267822` and fix the one factual error the origin introduced.

**Requirements:** Supports R1 (attribution), R2 (spam/quality open question); keeps the design docs true.

**Dependencies:** None (independent of U1/U2).

**Files:**
- Modify: `v0.5/04-strategy.md`
- Modify: `v0.5/05-architecture.md`
- Modify: `v0.5/08-open-questions.md`
- Modify (optional wording tweak): `v0.5/02-concepts.md`

**Approach:**
- `04-strategy.md` §4.2 — add an explicit clause that **the registering user need not be the record's author**
  (currently only "no write access needed" is stated, which is a different claim). One sentence.
- `05-architecture.md` §3 — reconcile the `created_by` claim: the live schema/tool have only `updated_by` (server-stamped
  with the registrant's SSO email). Either state that human attribution is carried by `updated_by`, or explicitly mark
  `created_by` as not-yet-implemented. **Do not** add a column (no backend work in scope).
- `08-open-questions.md` `## Catalog` group — optionally add a distinct **spam / abuse-gating** bullet, or add a note
  that "Row cap / bound" (already present) subsumes it. Do not re-open the items already tagged `*Decided*`.
- `02-concepts.md` line ~12 — optional: demote the "marked `discovery-layer`" lead so the marker reads as
  clearly-optional-for-humans. Wording only, not a concept change.

**Approach note:** Before editing, diff the mental model against commit `1267822` — most of the origin's "Documentation
Updates" section is already implemented. Plan these as **refinements**, not insertions, to avoid duplicate/contradictory
prose (e.g. a second "two non-exclusive paths" block).

**Test scenarios:**
- Test expectation: none — prose design docs. Verification is a read-through confirming (a) the author clause is present
  in §4.2, (b) no doc still asserts a `created_by` column the code lacks, (c) no duplicated "two paths" prose was
  introduced, (d) store-agnostic and long-single-line conventions preserved.

**Verification:** The four docs read consistently with the implemented schema and with commit `1267822`; no contradiction
or duplication introduced; the `created_by` discrepancy is resolved in text.

---

- U4. **(Optional) FAQ mention of ad-hoc registration**

**Goal:** Surface the new user-facing capability in the LIK FAQ, if the user wants it (per CLAUDE.md's "ask about FAQ
for new user-facing features" rule).

**Requirements:** None directly; discoverability/adoption support.

**Dependencies:** U1 (feature must be defined).

**Files:**
- Modify: `lik-ui/src/lik_ui/faq.md`

**Approach:** Add a short Q&A: how a user asks the Catalog Registration Agent to register a page/doc/sheet they point at
as an entry point, and what vouching vs. flagging means for ranking. Match the FAQ's existing voice and length. Confirm
with the user before adding — this unit may be dropped.

**Test scenarios:**
- Test expectation: none — documentation. Verify the entry renders and matches FAQ style/length.

**Verification:** FAQ contains an accurate, concise entry; or the user declines and the unit is dropped.

---

## System-Wide Impact

- **Interaction graph:** The new skill is a second writer on the `register_catalog_entry` path. It writes only
  `row_provenance='human'` rows, which are excluded from the skill upsert key — so it cannot collide with or overwrite
  `sync-catalog-from-project-indexes` rows; both coexist as ranked rows on a shared key.
- **Error propagation:** Follow the sibling skills' rule — on any tool/source failure, stop and report the error, likely
  cause, and remedy; never partially write. Do not pass identity; a missing/invalid token surfaces as a server auth
  error, not a silent unattributed write.
- **State lifecycle risks:** Human rows are never scheduled for re-derivation (`refresh_due_at`/`last_computed_at` stay
  null). Duplicates on a key are intentional and coexist as ranked rows; superseding is a deliberate separate write, not
  automatic — no cleanup logic in this iteration.
- **API surface parity:** No API/tool changes. `store_kind` must use the Catalog enum (`confluence`/`gdoc`/`gsheet`);
  the `gdrive` literal used by one read skill's citations is **not** valid here.
- **Unchanged invariants:** `register_catalog_entry`, the upsert conflict clause, the lookup `ORDER BY`, and the
  server-side identity stamping are all unchanged — this feature is pure composition. The Catalog invariant "only ever
  indexes DL records" still holds: a registered entry point is a DL record by designation.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Planner/implementer trusts the origin doc's `created_by` claim and expects a column that doesn't exist | U3 reconciles the doc; U1 execution note says author against live `catalog.py`, not the origin doc |
| Wrong `store_kind` literal (`gdrive`) breaks `citations.py` shape resolution | Decision fixes literals to `confluence`/`gdoc`/`gsheet`; U1 test scenario asserts it |
| Skill name typo (`registeration`) becomes a permanent `computed_by`/folder literal | Corrected to `adhoc-catalog-registration` in this plan; flagged to the user to confirm before authoring |
| Google Drive fetch tool details unknown until authoring | `store_kind` is a routing hint; skill stays store-agnostic and references the live `google-drive-drivemcp` server; only agent wiring (U2) is a hard dependency |
| Re-adding already-committed doc prose creates duplication/contradiction | U3 framed as refinement-not-insertion; diff against commit `1267822` first |
| Skill runs but isn't referenced by the agent → never invoked | U2 adds it to the agent `skills:` list and updates routing prose |

---

## Documentation / Operational Notes

- **Deployment (manual, post-merge):** run the `Deploy agents to Claude platform` GitHub Action (dispatches
  `deploy_agents.py`, which republishes each referenced skill at `latest` and attaches it). Deploying the skill alone
  (`Deploy skills to Claude platform`) is insufficient — the agent must reference it. Merging to `main` does **not**
  deploy on its own.
- **Upload rules:** the skill folder must be a single top-level folder named exactly `adhoc-catalog-registration`
  (matching the `name:` frontmatter, lowercased) or the upload 400s.
- **Post-merge:** consider a `/ce-compound` capture of the outcome (esp. the resolved provenance/sensitivity decisions
  and the `created_by` discrepancy), since `docs/solutions/` is thin for this domain.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-29-02-ad-hoc-catalog-registration-requirements.md](docs/brainstorms/2026-07-29-02-ad-hoc-catalog-registration-requirements.md)
- Sibling skill (template): [claude_platform/skills/sync-catalog-from-project-indexes/SKILL.md](claude_platform/skills/sync-catalog-from-project-indexes/SKILL.md)
- Tool + schema: [lik-mcp/src/lik_mcp/catalog.py](lik-mcp/src/lik_mcp/catalog.py), [lik-mcp/src/lik_mcp/server.py](lik-mcp/src/lik_mcp/server.py)
- Agent to modify: [claude_platform/agents/catalog-registration.yaml](claude_platform/agents/catalog-registration.yaml)
- Drive MCP wiring reference: [claude_platform/agents/knowledge-search.yaml](claude_platform/agents/knowledge-search.yaml)
- Deploy: [scripts/README.md](scripts/README.md)
- Already-landed doc work: commit `1267822` (docs(v0.5): add manual (human) Catalog-registration path)
