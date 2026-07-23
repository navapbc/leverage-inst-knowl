---
title: "feat: Skill instruction deploy pipeline (GitHub → Managed Agents)"
type: feat
status: active
date: 2026-07-23
origin: docs/brainstorms/2026-07-22-01-skill-instruction-hosting-requirements.md
---

# feat: Skill instruction deploy pipeline (GitHub → Managed Agents)

## Summary

Add a manually-dispatched GitHub Action that deploys the repo's skill directories
(`.claude/skills/<name>/`) to Claude Managed Agents as custom skill *versions*, so GitHub stays the
single source of truth and no one edits skills through the Claude Platform by hand. A maintainer runs
the workflow (choosing all skills or a specific one, mirroring `deploy-images.yml`); it packages each
selected skill directory, resolves its platform `skill_id` by name (creating the skill on first
deploy), creates a new immutable version via the Anthropic SDK, and relies on agents pinning the skill
to `latest` to pick the version up. A one-time bootstrap attaches the two existing skills to the
current agent at `version: "latest"`; the workflow stays agent-agnostic.

---

## Problem Frame

Skill instructions currently live only inside Managed Agents (edited via the Claude Platform) while
the `SKILL.md` files also sit in the repo for Claude Code — two copies with no single authority. The
brainstorm settled the WHAT: GitHub is the source of truth, a GitHub Action deploys via
`skills.versions.create`, agents pin `latest`, and the whole thing needs no public mirror or runtime
OAuth (see origin: docs/brainstorms/2026-07-22-01-skill-instruction-hosting-requirements.md). This plan
covers the HOW — the Action, the skill-id resolution, the one-time agent attachment, and correcting a
now-obsolete lik-ui TODO.

---

## Requirements

- R1. Skill instructions are authored/versioned in the repo; Managed Agents is a deploy target, not a second origin. *(origin R1)*
- R2. A skill is a directory (`SKILL.md` + optional reference files); the Action uploads all files under the dir, so on-demand reference loading works without restructuring. *(origin R2)*
- R3. A GitHub Action deploys a new skill *version* (versions are immutable; deploy = add a version). *(origin R3)*
- R4. Deploy authenticates with a standard org API key held as a CI secret, scoped to the workspace holding the agents/skills. *(origin R4)*
- R5. The agent references each skill at `version: "latest"`, so a deployed change rolls out with no per-agent step. *(origin R5)*
- R6. PR review + a deliberate manual deploy is the gate; there is no ungated edit path to a running agent. *(origin R6)*
- R7. lik-ui's "show full instructions" reads from GitHub, not a Managed Agents download. *(origin R7 — see Scope Boundaries; live rendering deferred, decision recorded here.)*

**Origin actors:** A1 skill author, A2 reviewer, A3 GitHub Action (CI), A4 Managed Agents platform, A5 lik-ui viewer.
**Origin flows:** F1 edit a skill, F2 deploy to Managed Agents, F3 view instructions in lik-ui.

---

## Scope Boundaries

- No public read-only mirror of instructions (instructions ship inside the skill version).
- No external live fetch of instructions at runtime (on-demand loading is native to the skill bundle).
- No skill-editing UI in lik-ui (write-through to Managed Agents) — rejected in the brainstorm.
- No non-engineer editing tooling — deliberately deferred until a specific recurring editor exists.
- The recurring Action does **not** manage agent↔skill attachment or agent creation (attachment is a one-time bootstrap; agents are managed outside this repo).
- Not resolving the skill-download credential type — closed as won't-fix, moot under R7.

### Deferred to Follow-Up Work

- **lik-ui live rendering of `SKILL.md` from GitHub** (the full R7 feature): separate PR. It carries an unresolved dependency — repo visibility (private → lik-ui needs a server-side read-only GitHub token or the files bundled into its image). This plan records the *decision* (read from GitHub, not Managed Agents) and corrects the misleading TODO (U3); building the live fetch waits until the visibility/auth approach is chosen.

---

## Context & Research

### Relevant Code and Patterns

- `.claude/skills/lik-query-project-index/SKILL.md`, `.claude/skills/lik-sync-catalog-from-project-indexes/SKILL.md` — the two skill dirs to deploy; frontmatter `name:` already equals the dir name (satisfies the folder-name-must-match-`name:` upload rule).
- `.github/workflows/deploy-images.yml` — existing CI conventions: `environment: prod` for scoped vars/secrets, path/`workflow_dispatch` gating, `actions/checkout@v6`. Mirror the structure; **diverge on auth** (Anthropic key secret, not AWS OIDC) and **trigger** (auto on push to `main`, not manual dispatch).
- `lik-ui/tests/test_agents.py` — `FakeAgentsClient` / faked `anthropic` SDK client pattern; reuse it to unit-test the deploy script without hitting the API.
- `lik-ui/src/lik_ui/agents.py` — `describe`/`describe_skill` show how the SDK's `beta.skills` / `beta.agents` surfaces are used in this repo (`skills.versions.retrieve`, `latest_version` resolution).
- `lik-mcp/scripts/` — precedent for a `scripts/` dir holding operational Python; this plan adds a repo-root `scripts/` for skill-deploy tooling (skills live at repo root, not under a service).

### Institutional Learnings

- None yet (`docs/solutions/` is empty).

### Verified API behavior (from the brainstorm's live SDK test)

- `skills.create(files=[…], display_title=…)` and `skills.versions.create(skill_id, files=[…])` both succeed with a standard `sk-ant-api03` org key.
- Upload requires files nested under a single top-level folder; a bare `SKILL.md` at the archive root → `400 "SKILL.md file must be exactly in the top-level folder."`
- The top-level folder name must equal the SKILL.md `name:` (lowercased) → else 400.
- Agent skill refs use `type: "custom"`, `version` accepts a concrete value or `"latest"`; `agents.update(agent_id, version=<agent_ver>, skills=[…])` re-pins.
- A skill can't be deleted while it has versions (irrelevant to deploys; noted for completeness).

---

## Key Technical Decisions

- **Resolve `skill_id` by name at deploy time; store no id state in the repo.** The script lists skills, matches the dir against an existing skill by its name/`display_title`, and calls `versions.create` if found or `create` if not. Keeps the repo authoritative on *content* and the platform authoritative on *ids*; nothing to keep in sync. *(implementer confirms which field `skills.list` items expose for matching — see Open Questions.)*
- **Trigger: manual `workflow_dispatch` with a `skill` choice input**, mirroring `deploy-images.yml`'s `service` input (`all` | `lik-query-project-index` | `lik-sync-catalog-from-project-indexes`, default `all`). The gate is PR review of the `SKILL.md` change plus a maintainer deliberately running the deploy (R6). The operator selecting a specific skill is how deploy scope is controlled — no auto-publish on merge, and no push-diff logic needed. Consistent with the repo's existing deploy workflow.
- **Python deploy script using the `anthropic` SDK**, invoked by the workflow. Matches repo tooling (uv/python) and the exact SDK calls verified in the brainstorm; avoids depending on unverified `ant` CLI skills support.
- **Auth via a new `ANTHROPIC_API_KEY` repo/environment secret** (env-scoped to `prod`, mirroring how `deploy-images.yml` scopes vars). The AWS OIDC path does not apply — Anthropic is not AWS. Standard org key, workspace-scoped, least privilege.
- **Fail fast on `name:`/dir mismatch** in the script, so the upload never reaches the 400.
- **Agent attachment is a one-time bootstrap, not the Action's job.** One agent exists and skills are added rarely; a small run-once script (U2) attaches both skills at `version:"latest"`. The recurring Action stays agent-agnostic (no `agent_id` config), so it never needs to know which agents consume a skill.

---

## Open Questions

### Resolved During Planning

- Trigger (manual `workflow_dispatch` + per-skill `choice` input), deploy scoping (operator selection, no push-diff), id resolution, auth mechanism, attachment ownership, script language — all decided above.

### Deferred to Implementation

- **Exact `skills.list` match field.** The brainstorm test set `display_title` on create and read `name` off the *version*; the implementer confirms whether `skills.list` items expose `display_title`/`name` and matches on that (fallback: `skills.retrieve` per id, or maintain the match on `display_title` set equal to the skill `name`).
- **Repo visibility** for the deferred lik-ui live-render (private repo → token or bundled files). Out of scope here; recorded so the follow-up starts from it.

---

## Implementation Units

- U1. **Skill-deploy GitHub Action + deploy script**

**Goal:** Let a maintainer deploy the selected skill directory(ies) to Managed Agents as a new custom-skill version via a manual workflow run.

**Requirements:** R1, R2, R3, R4, R6

**Dependencies:** None

**Files:**
- Create: `.github/workflows/deploy-skills.yml`
- Create: `scripts/deploy_skills.py`
- Create: `scripts/test_deploy_skills.py` (Test)
- Create: `scripts/README.md` (brief: what the script does, the `ANTHROPIC_API_KEY` secret, the two upload gotchas)

**Approach:**
- Workflow: `on: workflow_dispatch` with a `skill` `choice` input (`all` | each skill name, default `all`), mirroring `deploy-images.yml`'s `service` input and its per-item gate step; `environment: prod`; `actions/checkout@v6`; set up uv/python; run `scripts/deploy_skills.py --skill "${{ inputs.skill }}"` with `ANTHROPIC_API_KEY` from the env-scoped secret. Emit deployed name→skill_id→version to `$GITHUB_STEP_SUMMARY` (as `deploy-images.yml` does for image refs).
- Script selects the target dirs (`all` → every dir under `.claude/skills/`; otherwise the named one), then per dir:
  1. Read `SKILL.md` frontmatter `name`; assert it equals the dir name (fail fast otherwise).
  2. Collect every file under the dir; build upload tuples with arcnames prefixed by `<name>/` (guards both upload gotchas).
  3. `skills.list()` → find an existing skill matching `name`; if found `versions.create(skill_id, files=…)`, else `create(files=…, display_title=name)`.
  4. Log the skill name → skill_id → new version for the run summary.

**Patterns to follow:** `.github/workflows/deploy-images.yml` (workflow skeleton, `workflow_dispatch` + `choice` input, per-item gate, `environment: prod`, `$GITHUB_STEP_SUMMARY`); `lik-ui/tests/test_agents.py` (faked SDK client for tests); `lik-mcp/scripts/` (operational-script placement).

**Test scenarios:** *(against a faked `anthropic` client, mirroring `test_agents.py`)*
- Happy path — new skill: dir with `SKILL.md` + one reference file, `skills.list` returns no match → `create` called once with `display_title == name` and files whose arcnames are `<name>/SKILL.md`, `<name>/<ref>`; returns a skill_id.
- Happy path — existing skill: `skills.list` returns a skill matching `name` → `versions.create(skill_id, files=…)` called (not `create`).
- Edge — multiple reference files: every file under the dir is included in the upload, each arcname prefixed with `<name>/`.
- Edge — skill selection: `--skill <name>` processes only that dir; `--skill all` processes every dir under `.claude/skills/`.
- Error — `name:`/dir mismatch: `SKILL.md` `name:` differs from the dir name → script exits non-zero with a clear message, no upload attempted.
- Error — missing/invalid `SKILL.md` frontmatter → clear failure, no upload.
- Covers R2 / R3. Happy-path-new asserts the folder-nesting + folder-name==name invariants that the two documented 400s hinge on.

**Verification:** Faked-client tests pass. A live smoke run against a throwaway skill dir creates a skill, then a second run on an edit creates a *version* (not a new skill), then cleanup — matching the brainstorm's verified sequence.

---

- U2. **One-time bootstrap: attach skills to the agent at `latest`**

**Goal:** Make the existing agent reference both skills pinned to `version: "latest"`, so U1's deploys roll out automatically.

**Requirements:** R5

**Dependencies:** U1 (skills must exist on the platform before they can be attached — run this after the first Action deploy, or have the script create-if-missing).

**Files:**
- Create: `scripts/attach_skills_to_agent.py`
- Modify: `scripts/README.md` (document that this is run once per new skill, not per deploy)

**Approach:**
- Given an `agent_id` (config/env; the current one is `agent_01E7mqTKAdtosKpWDSLxALmq`) and the skill names, resolve each skill_id (same name→id lookup as U1), then `agents.update(agent_id, version=<current agent version>, skills=[{type:"custom", skill_id, version:"latest"}, …])`, preserving the agent's other fields.
- Idempotent: re-running with the same skills is a no-op change; safe to re-run when a new skill is added.

**Execution note:** One-time / on-demand operational script, not part of CI. Keep it a thin wrapper over the same resolution helper U1 uses.

**Patterns to follow:** `lik-ui/src/lik_ui/agents.py` (`beta.agents.retrieve`/skill-version resolution); `lik-ui/scripts/smoke.py` (standalone operational script reading `LIK_*` env).

**Test scenarios:** *(faked client)*
- Happy path: given an agent with no skills, `agents.update` is called with both skills at `version:"latest"` and the agent's existing `model`/`system`/`tools` preserved.
- Edge — already attached: re-running yields the same skills list (idempotent), no duplicate entries.
- Covers R5.

**Verification:** After running against the real agent, `agents.retrieve(agent_id).skills` shows both skills with `version` resolving to `latest`; a subsequent U1 deploy is picked up on the next session with no further attach step.

---

- U3. **Correct the lik-ui TODO and document the pipeline**

**Goal:** Remove the now-obsolete "download from Managed Agents" TODO and record the GitHub-source-of-truth resolution; document the deploy pipeline for maintainers.

**Requirements:** R7 (decision-recording portion; live rendering deferred — see Scope Boundaries)

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/README.md` (rewrite the `## TODO: show full skill instructions (SKILL.md)` section: the download-credential 403 is won't-fix; instructions are authoritative in GitHub and the future viewer should render them from there; link the follow-up)
- Modify: `lik-mcp/README.md` or `.claude/skills/`-adjacent docs (add a short "Deploying skills to Managed Agents" note pointing at `scripts/README.md` and the Action)

**Approach:** Documentation only. State plainly that GitHub is the source of truth, the Action deploys versions, and lik-ui's instruction view will read from GitHub (not `beta.skills.versions.download`).

**Patterns to follow:** existing `lik-ui/README.md` TODO/section style; `lik-mcp/README.md` operational-instructions style.

**Test scenarios:** Test expectation: none — documentation change, no runtime behavior.

**Verification:** The lik-ui README no longer implies a missing download credential is the blocker; a maintainer can find how to deploy a skill from the docs alone.

---

## System-Wide Impact

- **Interaction graph:** New CI workflow + two operational scripts; no change to lik-mcp or lik-ui runtime code. The scripts touch the Anthropic control plane (skills, one agent), not the DL data plane.
- **Blast radius / behavior change:** Because agents pin `latest`, a deploy run **immediately changes what a production agent runs** on its next session. This is intended (R5); the manual-dispatch trigger keeps a human in control of *when* it happens — see Risks.
- **New external contract surface:** a repo/environment secret (`ANTHROPIC_API_KEY`) and a new `prod`-scoped manual workflow. No new public API.
- **Unchanged invariants:** lik-mcp service, Catalog schema, lik-ui runtime, and the existing `deploy-images.yml` flow are untouched. Skills remain plain `.claude/skills/<name>/SKILL.md` dirs usable by Claude Code exactly as today — the same files now also deploy to Managed Agents.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| A bad skill edit reaches prod agents once deployed (pin-to-latest). | PR review + a deliberate manual deploy is the gate (R6); revert = re-run the workflow on an earlier commit; if staged rollout is ever needed, switch the agent from `latest` to a pinned version (supported, deferred). |
| `skill_id` resolved by name mismatches if two skills share a name/`display_title`. | Skill names are unique (repo dir names are unique and `lik-`-prefixed); script can assert uniqueness of the match. |
| `skills.list` match field differs from assumption. | Deferred-to-implementation confirmation; fallback to `display_title == name` set on create. |
| A deploy run republishes a skill the operator didn't intend to change. | Manual dispatch with a per-skill `choice` input scopes each run; default `all` is a deliberate operator choice, not an automatic trigger. |
| `name:`/folder mismatch triggers the upload 400. | Fail-fast validation in `scripts/deploy_skills.py` before any upload. |
| New `ANTHROPIC_API_KEY` secret over-scoped. | Standard org key, workspace-scoped, env-scoped to `prod`; not an admin key. |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-22-01-skill-instruction-hosting-requirements.md](docs/brainstorms/2026-07-22-01-skill-instruction-hosting-requirements.md)
- Related code: `.github/workflows/deploy-images.yml`, `lik-ui/src/lik_ui/agents.py`, `lik-ui/tests/test_agents.py`, `.claude/skills/`
- Related plan: [docs/plans/2026-07-06-001-feat-lik-ui-managed-agent-app-plan.md](docs/plans/2026-07-06-001-feat-lik-ui-managed-agent-app-plan.md) (agent/skill IDs)
