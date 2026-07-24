---
title: "feat: Agent spec deploy pipeline (GitHub → Managed Agents)"
type: feat
status: active
date: 2026-07-24
origin: docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md
---

# feat: Agent spec deploy pipeline (GitHub → Managed Agents)

## Summary

Make GitHub the single source of truth for Managed Agent *definitions* the same way it already is for
skills. Agents and their environments become declarative spec files (the platform's own export YAML)
under a new `claude_platform/` folder; a manually-dispatched GitHub Action deploys them via the
Anthropic SDK — resolving/creating each environment and agent **by name**, translating skill *names*
to platform `skill_id`s at deploy time, and creating on first deploy or updating (new version) after.
lik-ui stops storing platform ids: it resolves agent/environment names to ids at startup. Skills move
out of `.claude/skills/` into `claude_platform/skills/` so all Managed-Agents resources share one tree
(accepted cost: the two skills stop being Claude Code skills).

---

## Problem Frame

An agent's full definition (system prompt, model, MCP servers, tool permissions, skill attachments,
environment) is hardcoded as Python dicts inside a create-only script,
[lik-ui/scripts/init_workspace.py](lik-ui/scripts/init_workspace.py). There is no declarative spec and
no update path — editing a live agent means hand-editing the Claude Platform (the two-sources problem
the skill pipeline already solved) or re-running a script that makes a *new* agent. See origin:
docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md.

---

## Requirements

- R1. Declarative agent specs live in the repo under `claude_platform/agents/`, in the platform's raw
  agent export/import YAML. *(origin R1)*
- R2. Skills are referenced by **name**, not `skill_id`; the deploy translates name → id before the SDK
  call and pins `version: "latest"`. No `skill_id`s in the repo. *(origin R2)*
- R3. Skills must exist on the platform before agent deploy; the pipeline guarantees ordering
  (skills-deploy step runs before agents-deploy step). A missing referenced skill fails fast. *(origin R3)*
- R4. A manually-dispatched GitHub Action deploys agents, mirroring `deploy-skills.yml` (agent-choice
  input, `environment: prod`, workspace-scoped `ANTHROPIC_API_KEY`). Deploy resolves env by name
  (create/update), resolves skills by name, then creates the agent by name or updates it (new version),
  preserving other fields. *(origin R4)*
- R5. Environments are managed by the same pipeline: each is a raw-format spec under
  `claude_platform/environments/`, resolved/created by name. *(origin, "manage environments")*
- R6. lik-ui resolves agent and environment **names → ids at startup**; no ids checked into the repo.
  The roster becomes a list of agent names (+ the environment name each runs in). Downstream runtime
  behavior is unchanged. *(origin R5, R6)*
- R7. Skills relocate `.claude/skills/` → `claude_platform/skills/`; all references repointed. The two
  skills stop being Claude Code skills (accepted). *(origin R7 / "Skills relocation")*
- R8. `init_workspace.py` no longer hardcodes agent/env dicts or appends id-blocks; the initial agent +
  environment become spec files, and workspace bootstrap runs the same deploy code (create path). *(origin R6, Requirement 6)*

**Origin actors:** A1 agent author, A2 reviewer, A3 GitHub Action (CI), A4 Managed Agents platform,
A5 lik-ui (runtime consumer resolving names→ids).
**Origin flows:** F1 edit an agent spec, F2 deploy to Managed Agents, F3 lik-ui offers/launches the agent.

---

## Scope Boundaries

- No API-key creation (Console-only; unchanged).
- No non-engineer editing UI / admin console for agents.
- No per-agent staged rollout or pinned skill versions (skills pinned at `latest`, as in the skill plan).
- No auto-deploy on merge (manual dispatch keeps a human controlling *when* a prod agent changes).
- No database-backed agent registry / hot reload (restart-to-change accepted, per the prior roster doc).
- The recurring Action does not create API keys or manage the `prod` secret's value.

### Deferred to Follow-Up Work

- **Making lik-ui private-repo-safe (bundle docs into the image)** so the repo can be flipped private:
  captured in [docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md](docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md).
  This plan is visibility-agnostic; see Risks for the current-public implication.

---

## Context & Research

### Relevant Code and Patterns

- [scripts/deploy_skills.py](scripts/deploy_skills.py) — the pipeline to mirror: `SKILLS_ROOT`
  resolution, `find_existing_skill_id` (matches `display_title == name`), `create`-else-`versions.create`,
  `$GITHUB_STEP_SUMMARY` emission. The agent deploy reuses `find_existing_skill_id` for skill-name→id.
- [scripts/attach_skills_to_agent.py](scripts/attach_skills_to_agent.py) — `resolve_skill_ids`
  (name→id, errors if absent = R3 fail-fast), `merge_skills` (pin `latest`), and the field-preservation
  care on `agents.update` (re-send name/model/system/tools/mcp_servers so a new version doesn't drop them).
- [lik-ui/scripts/init_workspace.py](lik-ui/scripts/init_workspace.py) — the current hardcoded
  `AGENT_DEFINITION` / `ENV_DEFINITION` (source for the initial spec files) and the capture one-liner
  (how to snapshot an agent/env from the Console into raw YAML).
- [lik-ui/src/lik_ui/settings.py](lik-ui/src/lik_ui/settings.py) — `AgentOption(agent_id, environment_id)`,
  the `agents` property parsing `agents.toml` (`[[agents]]`, `default_environment_id`), and
  `require_production_config` (fails closed on empty roster). The roster ships as package data.
- [lik-ui/src/lik_ui/agents.py](lik-ui/src/lik_ui/agents.py) — `AnthropicAgentsClient.describe`
  (`beta.agents.retrieve`), `build_agents_client`. New name→id resolution lives alongside this.
- [lik-ui/src/lik_ui/app.py](lik-ui/src/lik_ui/app.py) / [lik-ui/src/lik_ui/__main__.py](lik-ui/src/lik_ui/__main__.py)
  — where collaborators are built and `app.state` is populated; the resolution step slots in here.
- [lik-ui/src/lik_ui/chat.py](lik-ui/src/lik_ui/chat.py) — sessions created/stored keyed by `agent_id`
  (`beta.sessions.create(agent=agent_id, environment_id=...)`, `store.create_session(..., agent_id, ...)`);
  why resolution must yield concrete ids and leave downstream code untouched.
- [.github/workflows/deploy-skills.yml](.github/workflows/deploy-skills.yml) — workflow skeleton to mirror.
- [lik-ui/src/lik_ui/skill_docs.py](lik-ui/src/lik_ui/skill_docs.py) — hardcodes
  `.claude/skills/{name}/SKILL.md`; a folder-move consumer (R7).

### Institutional Learnings

- None recorded (`docs/solutions/` is empty).

### Verified API behavior (SDK 0.118.0, probed offline)

- `beta.agents` exposes `create, list, retrieve, update, archive, versions` → by-name resolution via
  `list()` and update-in-place are both available.
- `beta.environments` exposes `create, list, retrieve, update, archive, delete` → **environments update
  in place** (resolves the origin's "update vs create-only" open item; no new-name dance needed).
- `beta.skills` exposes `create, list, retrieve, delete, versions` (unchanged from the skill plan).
- The platform agent definition carries **no environment** — env is bound at `beta.sessions.create`.
  So the agent↔environment pairing is a lik-ui runtime concern (roster), not part of the agent spec, and
  the deploy never pairs them.

---

## Key Technical Decisions

- **On-disk format = the platform's raw agent export YAML, with one divergence: `skills` by name.**
  No bespoke schema to maintain; capturing from the Console is copy-paste. The deploy parses the YAML,
  swaps each `skills` entry's name for `{type: custom, skill_id: <resolved>, version: latest}`, and
  sends the rest verbatim. Accepted cost: `system:` is one long quoted line.
- **Environments are separate raw-format files; pairing lives in the roster.** `claude_platform/environments/<name>.yaml`
  holds the env; `agents.toml` says which env each offered agent runs in. Deploy manages agents and envs
  independently (no pairing at deploy); only lik-ui pairs them at session-launch.
- **By-name resolution is isolated to lik-ui startup.** Keep `AgentOption(agent_id, environment_id)` and
  every downstream consumer unchanged; add a resolver that turns the name roster into resolved
  `AgentOption`s once at boot using the SDK. Settings stays network-free; resolution lives where the
  agents_client already does.
- **Ordering via a two-step workflow, not create-if-missing.** `deploy-agents.yml` runs
  `deploy_skills.py` then `deploy_agents.py`, so referenced skills are current before agents attach
  (R3). Keeps the agent deploy a pure resolve-and-attach and reuses the skill script unchanged.
- **Reuse, don't fork, the skill helpers.** `deploy_agents.py` imports `find_existing_skill_id` /
  `select_skill_dirs` from `deploy_skills.py` and mirrors `merge_skills`/field-preservation from
  `attach_skills_to_agent.py`. The one-time attach script is subsumed (agents now declare skills in
  their spec), so `attach_skills_to_agent.py` is retired.

---

## Open Questions

### Resolved During Planning

- **Environment update semantics** — `beta.environments.update` exists; envs update in place.
- **Format** — platform raw YAML, skills-by-name (origin-decided; substitution mechanism above).
- **Ordering** — two-step workflow (skills then agents).
- **Where name→id resolution lives** — lik-ui startup, isolated; downstream unchanged.

### Deferred to Implementation

- **`agents.list` / `environments.list` match field.** Confirm the stable field to match a name on
  (mirror the skill plan's `display_title` approach; agent `name` vs `display_title` to be verified
  against list-item shape). Fallback: `retrieve` per id.
- **Field-preservation on `agents.update`.** Confirm which fields must be re-sent so a new version
  doesn't drop them (tools/mcp_servers/system/model), mirroring `attach_skills_to_agent.py`.
- **Orphaned DB sessions after a workspace re-init.** Sessions are stored by `agent_id`; a new workspace
  assigns new ids, so old rows won't resolve. Expected acceptable (migration = fresh start); confirm no
  cleanup is needed.

---

## Output Structure

    claude_platform/
      skills/                         # moved from .claude/skills/ (R7)
        lik-query-project-index/
          SKILL.md
        lik-sync-catalog-from-project-indexes/
          SKILL.md
      agents/
        knowledge-search.yaml         # raw platform agent YAML, skills-by-name
      environments/
        lik-ui.yaml                   # raw platform environment YAML
    scripts/
      deploy_agents.py                # new
      test_deploy_agents.py           # new
    .github/workflows/
      deploy-agents.yml               # new

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation
> specification. The implementing agent should treat it as context, not code to reproduce.*

Deploy (`deploy_agents.py`, per selected agent):

    read claude_platform/agents/<name>.yaml (raw platform YAML)
    for each environment referenced by the run:
        env_id = find_env_by_name(name) ? environments.update(env_id, <config>)
                                        : environments.create(<config>)
    resolve skills:
        for each entry in spec.skills:               # entry is a NAME in the repo
            skill_id = find_existing_skill_id(client, name)   # reused from deploy_skills
            if skill_id is None: FAIL FAST (R3)
            replace entry -> {type: custom, skill_id, version: "latest"}
    agent_id = find_agent_by_name(spec.name) ? agents.update(agent_id, <spec + preserved fields>)
                                             : agents.create(<spec>)
    emit name -> id -> version to $GITHUB_STEP_SUMMARY

lik-ui startup (resolution isolated; downstream unchanged):

    roster (agents.toml)  = [{agent: "knowledge-search", environment: "lik-ui"}, ...]  # NAMES
    for entry in roster:
        agent_id = resolve_agent_id(client, entry.agent)          # beta.agents.list -> match name
        env_id   = resolve_env_id(client, entry.environment)      # beta.environments.list -> match name
        AgentOption(agent_id=agent_id, environment_id=env_id)     # same shape as today

---

## Implementation Units

- U1. **Relocate skills `.claude/skills/` → `claude_platform/skills/` and repoint all references**

**Goal:** Move both skill directories under the new shared tree and update every consumer atomically so
nothing points at a dead path.

**Requirements:** R7

**Dependencies:** None

**Files:**
- Move: `.claude/skills/lik-query-project-index/` → `claude_platform/skills/lik-query-project-index/`
- Move: `.claude/skills/lik-sync-catalog-from-project-indexes/` → `claude_platform/skills/lik-sync-catalog-from-project-indexes/`
- Modify: `scripts/deploy_skills.py` (`SKILLS_ROOT` → `claude_platform/skills`)
- Modify: `.github/workflows/deploy-skills.yml` (any `.claude/skills` reference / comments)
- Modify: `lik-ui/src/lik_ui/skill_docs.py` (path `.claude/skills/{name}/SKILL.md` → `claude_platform/skills/{name}/SKILL.md`)
- Modify: `scripts/README.md`, `CLAUDE.md` (skill-location references; the `lik-` naming note now points at `claude_platform/skills/`)
- Modify: `scripts/test_deploy_skills.py` (any hardcoded `.claude/skills` path in fixtures)
- Test: `scripts/test_deploy_skills.py`, `lik-ui/tests/` (skill_docs path test if present)

**Approach:**
- Git-move the two dirs; grep the whole repo for `.claude/skills` and repoint each hit.
- Land the `SKILLS_ROOT` change in the same commit as the move so `deploy_skills.py` is never pointed at
  a nonexistent path.
- Skill **names** are unchanged (still the dir names), so platform matching (`display_title == name`) and
  already-deployed skills are unaffected — no duplicate skills created.

**Patterns to follow:** existing `deploy_skills.py` path resolution (resolve from `__file__`).

**Test scenarios:**
- Edge — path repoint: `deploy_skills.select_skill_dirs("all")` returns the two dirs under
  `claude_platform/skills/` (not the old path).
- Edge — skill_docs path: `skill_docs` builds `claude_platform/skills/<name>/SKILL.md`.
- Regression: existing `deploy_skills` tests pass unchanged against the new root.

**Verification:** `grep -r ".claude/skills"` returns no live references; `uv run pytest` green in
`scripts/` and `lik-ui/`; a dry inspection shows the two skills under `claude_platform/skills/`.

---

- U2. **Author the initial agent + environment spec files**

**Goal:** Migrate the hardcoded `AGENT_DEFINITION` / `ENV_DEFINITION` into raw-format spec files, with
`skills` expressed by name.

**Requirements:** R1, R2, R5

**Dependencies:** U1 (skills exist under `claude_platform/`; skill names are the reference target)

**Files:**
- Create: `claude_platform/agents/knowledge-search.yaml` (raw platform agent YAML; `skills:` lists the
  skill *name(s)*, e.g. `lik-query-project-index`)
- Create: `claude_platform/environments/lik-ui.yaml` (raw platform environment YAML, from `ENV_DEFINITION`)

**Approach:**
- Transcribe `AGENT_DEFINITION` (name, model, system, mcp_servers, tools+permission policies,
  description) into the raw YAML shape shown in the origin doc; represent `skills` as names only.
- Transcribe `ENV_DEFINITION` (name, config: cloud/limited networking, packages) into the env file.
- Keep the agent `name` stable — it becomes the by-name key for both deploy and lik-ui resolution.

**Patterns to follow:** the raw YAML block in the origin requirements doc; `init_workspace.py`'s
`AGENT_DEFINITION` / `ENV_DEFINITION` as the content source.

**Test scenarios:** `Test expectation: none — static spec files, exercised by U3/U5 tests.`

**Verification:** `deploy_agents.py` (U3) parses both files without error; the agent spec's `skills`
entries resolve to real skill ids in a dry run.

---

- U3. **`deploy_agents.py` deploy script (+ tests)**

**Goal:** Deploy selected agent spec(s): resolve/create environments by name, resolve skill names→ids,
create-or-update the agent by name (new version), preserving other fields.

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** U1, U2

**Files:**
- Create: `scripts/deploy_agents.py`
- Create: `scripts/test_deploy_agents.py` (Test)
- Modify: `scripts/README.md` (add a `deploy_agents.py` section; note `attach_skills_to_agent.py` retirement)

**Approach:**
- `--agent` choice: `all` (every file under `claude_platform/agents/`) or a single agent name; mirror
  `select_skill_dirs`.
- Per agent: parse the raw YAML; resolve the environment(s) it needs by name via `beta.environments.list`
  → `update` if found else `create` from `claude_platform/environments/<name>.yaml`.
- Resolve `skills` names → ids via `find_existing_skill_id` (imported from `deploy_skills`); **fail fast**
  if any is missing (R3); substitute `{type: custom, skill_id, version: "latest"}`.
- Match the agent by name via `beta.agents.list` → `agents.update(agent_id, …)` (new version, re-sending
  preserved fields per `attach_skills_to_agent.py`) else `agents.create(…)`.
- Emit `name → id → version` (agent + env) to stdout and `$GITHUB_STEP_SUMMARY`.
- Assert name uniqueness of a match (agent and env); ambiguous match is an error.

**Execution note:** Build against a faked `anthropic` client, mirroring
[scripts/test_deploy_skills.py](scripts/test_deploy_skills.py) / `test_attach_skills_to_agent.py`.

**Technical design:** see High-Level Technical Design (deploy sketch).

**Patterns to follow:** `deploy_skills.py` (selection, `find_existing_skill_id`, summary emission);
`attach_skills_to_agent.py` (`merge_skills`, field-preservation on update, dry-run posture).

**Test scenarios:**
- Happy — new agent: `agents.list` no match → `agents.create` called with the parsed spec; `skills`
  carry resolved ids at `version:"latest"`.
- Happy — existing agent: `agents.list` matches by name → `agents.update(agent_id, …)` (new version),
  not `create`; preserved fields (tools/mcp_servers/system/model) re-sent.
- Happy — env create vs update: env absent → `environments.create`; env present → `environments.update`.
- Edge — skill name→id substitution: a spec `skills: [lik-query-project-index]` becomes
  `{type: custom, skill_id: <resolved>, version: latest}` before the agent call.
- Edge — `--agent all` vs single: selection resolves every file vs the named one.
- Error — missing skill: a referenced skill not on the platform → exits non-zero, clear message, no
  agent create/update attempted (R3).
- Error — ambiguous name match (two agents/envs same name) → fail with a clear message.
- Error — malformed/missing spec YAML → clear failure, nothing deployed.
- Covers R2 / R3 / R4 / R5.

**Verification:** Faked-client tests pass. A live smoke run creates the agent+env in a throwaway
workspace, a second run on an edited spec produces a new agent *version* (not a duplicate), env update
applies in place.

---

- U4. **`deploy-agents.yml` GitHub Action**

**Goal:** Let a maintainer deploy selected agent(s) from a manual run, with skills deployed first.

**Requirements:** R3, R4

**Dependencies:** U3

**Files:**
- Create: `.github/workflows/deploy-agents.yml`

**Approach:**
- `on: workflow_dispatch` with an `agent` `choice` input (`all` | each agent name, default `all`);
  `environment: prod`; `actions/checkout@v6`; `astral-sh/setup-uv@v7`.
- Two steps in order (R3): `uv run python deploy_skills.py --skill all`, then
  `uv run python deploy_agents.py --agent "${{ inputs.agent }}"`, both with `ANTHROPIC_API_KEY` from the
  `prod`-scoped secret, `working-directory: scripts`.
- Emit deployed refs to `$GITHUB_STEP_SUMMARY` (both scripts already do).

**Patterns to follow:** [.github/workflows/deploy-skills.yml](.github/workflows/deploy-skills.yml) verbatim skeleton.

**Test scenarios:** `Test expectation: none — CI YAML; exercised by the deploy scripts' unit tests and a
live smoke run.`

**Verification:** A manual dispatch on a test workspace deploys skills then the agent; the run summary
shows agent/env name→id→version; re-dispatch after a spec edit shows a new agent version.

---

- U5. **lik-ui resolves agents + environments by name at startup**

**Goal:** Replace the id-pair roster with a name roster; resolve names→ids once at boot; leave all
downstream runtime behavior unchanged.

**Requirements:** R6

**Dependencies:** U2 (agent/env names are the resolution keys)

**Files:**
- Modify: `lik-ui/src/lik_ui/settings.py` (roster parses agent **names** + environment names; retire
  `agent_id`/`environment_id`/`default_environment_id` id fields; the prod guard validates a non-empty
  *name* roster)
- Modify: `lik-ui/src/lik_ui/agents.py` (add name→id resolvers using `beta.agents.list` /
  `beta.environments.list`; extend the `AgentsClient` protocol + fake)
- Modify: `lik-ui/src/lik_ui/app.py` and `lik-ui/src/lik_ui/__main__.py` (at startup, resolve the name
  roster into `list[AgentOption]` via the agents_client; store on `app.state`; consumers read the
  resolved list)
- Modify: `lik-ui/src/lik_ui/agents.toml` (rewrite to name-based `[[agents]]`: `agent = "..."`,
  `environment = "..."`)
- Modify: consumers reading `settings.agents` — `agents.py` (`/connections`), `chat.py` (`new_chat`) —
  to read the resolved list from `app.state`
- Modify: `lik-ui/src/lik_ui/templates/agents.html` (the "No agents configured" hint referencing
  `LIK_UI_DEFAULT_AGENT_ID`, now stale)
- Test: `lik-ui/tests/test_agents.py`, `lik-ui/tests/test_settings.py` (or equivalent roster-parse test)

**Approach:**
- Keep `AgentOption(agent_id, environment_id)` as the resolved shape — chat/connections/db stay byte-for-byte.
- Resolution is a single startup pass; a name that doesn't resolve is a loud startup failure in prod
  (mirror `require_production_config`), an empty/skippable list in local/test (stub, no client).
- `settings.agents` becomes the *name roster* accessor; the *resolved* `AgentOption`s live on
  `app.state` (built in `build_app`/`__main__` where the agents_client exists). Adjust the ~2 consumers.

**Technical design:** see High-Level Technical Design (lik-ui startup sketch).

**Patterns to follow:** `AnthropicAgentsClient.describe` (SDK access shape, fake client in
`test_agents.py`); `settings.require_production_config` (fail-closed posture).

**Test scenarios:**
- Happy — roster resolves: name roster + faked `agents.list`/`environments.list` → `AgentOption`s with
  the matched ids, in roster order.
- Edge — environment override vs default: an entry naming its own environment resolves to that env; the
  shared default applies otherwise.
- Edge — local/test stub: no agents_client → roster resolution is skipped, app boots (matches current
  stub behavior).
- Error — unresolvable name in prod: a roster name with no platform match → startup fails loudly
  (not a silent empty picker).
- Error — empty roster in prod: `require_production_config` still fails closed.
- Integration — `/connections` and `new_chat`: given a resolved `AgentOption`, the existing flows create
  a session with the resolved `agent_id`/`environment_id` (behavior unchanged).
- Covers R6.

**Verification:** With the name roster and a faked client, the agent picker shows the same agent and a
chat session launches with the resolved ids; no `agent_id`/`environment_id` literals remain in
`agents.toml`.

---

- U6. **Retire hardcoded definitions in `init_workspace.py`; bootstrap via the deploy path**

**Goal:** Remove `AGENT_DEFINITION`/`ENV_DEFINITION` and the id-block append; workspace bootstrap
creates the agent+env by running the deploy against the target-workspace key.

**Requirements:** R8

**Dependencies:** U3 (deploy create path), U2 (spec files), U5 (name roster)

**Files:**
- Modify: `lik-ui/scripts/init_workspace.py` (drop hardcoded dicts, `partition_skills`/`build_*_payload`
  create-shaping, `format_agent_block`/`append_agent_to_config`; call the U3 deploy for a fresh
  workspace; keep the capture one-liner docs and the SSM/next-steps guidance)
- Modify: `lik-ui/tests/test_init_workspace.py` (drop tests asserting the hardcoded payloads / id-append;
  cover the new bootstrap-via-deploy behavior)
- Modify: `lik-ui/scripts/` retirement note; `scripts/attach_skills_to_agent.py` + its test removed
  (subsumed — agents declare skills in their spec)

**Approach:**
- `init_workspace` becomes a thin wrapper: given a target-workspace key, run the agent+env deploy
  (create path) using the spec files, then remind the operator of the SSM key + redeploy steps.
- Because the roster is by name and stable, re-init needs no `agents.toml` id rewrite — retire the append.
- Preserve the "which workspace the key targets" framing and the CI skill-deploy-secret reminder in
  `NEXT_STEPS`.

**Patterns to follow:** existing `init_workspace.py` structure (arg parsing, dry-run, redact, NEXT_STEPS);
reuse U3's deploy functions rather than re-implementing create.

**Test scenarios:**
- Happy — bootstrap: given a target key and spec files, the deploy create path is invoked for the
  agent + env (faked client); no `agents.toml` mutation.
- Edge — dry-run: prints the planned create + SSM/next-steps, creates nothing.
- Regression — NEXT_STEPS still surfaces the SSM key line and the CI skill-deploy-secret repoint.
- Covers R8.

**Verification:** Running `init_workspace` against a throwaway workspace creates the agent+env from the
specs; `agents.toml` is untouched; the printed steps match the current SSM/redeploy flow.

---

- U7. **Docs: pipeline runbook + stale-reference cleanup**

**Goal:** Document the agent deploy pipeline and correct references left by the move/retirement.

**Requirements:** R4, R7 (doc portions)

**Dependencies:** U1, U3, U4, U6

**Files:**
- Modify: `scripts/README.md` (add "Deploying agents to Managed Agents": `deploy_agents.py`, the
  `deploy-agents.yml` Action, skills-first ordering; note `attach_skills_to_agent.py` retired)
- Modify: `CLAUDE.md` (skill path now `claude_platform/skills/`; note the agent-spec location + pipeline)
- Modify: `lik-ui/README.md` / `claude-managed-agents.md` if they describe agent creation or the roster
  (id-pairs → names)

**Approach:** Documentation only. State plainly: GitHub is the source of truth for agents + environments;
specs are raw platform YAML under `claude_platform/`; skills are referenced by name and deployed first;
lik-ui resolves names at startup.

**Test scenarios:** `Test expectation: none — documentation.`

**Verification:** A maintainer can deploy an agent from the docs alone; no doc references the old
`.claude/skills` path or the retired hardcoded-definition flow.

---

## System-Wide Impact

- **Interaction graph:** New CI workflow + one deploy script; retires `attach_skills_to_agent.py`. lik-ui
  gains a startup name→id resolution step; chat/connections/db/session code is unchanged (still consume
  `AgentOption`).
- **Blast radius / behavior change:** A deploy run changes what the prod agent runs on its next session
  (intended, R4/R5); manual dispatch keeps a human in control of timing. The skills folder move changes
  where `deploy_skills.py`, `skill_docs.py`, and Claude Code look — landed atomically (U1).
- **Loss of capability (accepted):** the two skills stop being Claude Code skills once moved out of
  `.claude/skills/`.
- **New external contract surface:** a new `prod`-scoped `deploy-agents.yml` (reuses the existing
  `ANTHROPIC_API_KEY` secret). No new public API.
- **Unchanged invariants:** lik-mcp, the Catalog schema, lik-ui's runtime chat/connection/session flows,
  and `deploy-images.yml` are untouched. `AgentOption`'s shape is preserved so downstream lik-ui code
  needs no change beyond where the resolved list is sourced.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| **Repo is public** → agent system prompts + MCP server URLs become publicly readable once specs land. | System prompts are already effectively public (fetched raw by lik-ui; shown on the connections page) and MCP URLs already sit in `init_workspace.py`, so no *new* secret exposure. Flipping the repo private is a deferred follow-up: [2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md](docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md). |
| Skills folder move points a script/consumer at a dead path. | U1 lands the move + all repoints (`SKILLS_ROOT`, `skill_docs.py`, workflow, docs, tests) atomically; grep-gate verifies no stragglers. |
| By-name resolution matches the wrong resource if names aren't unique. | Deploy asserts unique name match (agents + envs); lik-ui resolution fails loudly on no/ambiguous match. Names are curated + `lik-`/spec-file unique. |
| `agents.update` drops fields not re-sent (new version). | Re-send preserved fields, mirroring `attach_skills_to_agent.py`; test asserts tools/mcp_servers/system/model survive an update. |
| A referenced skill isn't deployed yet at agent-deploy time. | Two-step workflow deploys skills first (R3); `deploy_agents.py` fails fast on an unresolved skill name. |
| Startup name resolution adds boot-time SDK calls / a failure mode. | One `list` per resource kind at boot; fail-closed in prod (loud), skipped in stub. Restart-to-change already accepted. |
| Old DB sessions (keyed by prior-workspace `agent_id`) orphan after a re-init. | Expected on workspace migration (fresh start); confirm no cleanup needed (deferred-to-implementation). |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md](docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md)
- **Deferred follow-up:** [docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md](docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md)
- **Sibling pipeline:** [docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md](docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md)
- Related code: `scripts/deploy_skills.py`, `scripts/attach_skills_to_agent.py`, `lik-ui/scripts/init_workspace.py`, `lik-ui/src/lik_ui/{settings,agents,app,chat}.py`, `.github/workflows/deploy-skills.yml`
