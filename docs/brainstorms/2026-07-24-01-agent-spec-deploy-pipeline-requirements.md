# Requirements: Agent spec deploy pipeline (GitHub → Managed Agents)

**Date:** 2026-07-24
**Status:** Ready for planning
**Scope:** Deep — feature (extends the existing skill deploy pipeline)
**Origin / siblings:**
[docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md](docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md)
(the skill pipeline this mirrors),
[docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md](docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md)
(established `agents.toml` as a checked-in roster — **this doc evolves its Requirement 1**, see Relationship below).

## Problem

Skills are now GitHub-source-of-truth with a manual GitHub Action that deploys new versions
(the skill pipeline). Agents are not: an agent's full definition (system prompt, model, MCP servers,
tool permissions, skill attachments, environment) is **hardcoded as Python dicts inside a create-only
script**, [lik-ui/scripts/init_workspace.py](lik-ui/scripts/init_workspace.py). There is no declarative
spec and no update path — editing a live agent's system prompt today means editing it by hand on the
Claude Platform (the same two-sources-of-truth problem the skill pipeline solved) or re-running a script
that creates a *new* agent. The goal: manage and deploy agents from GitHub the way skills are, so GitHub
is the single authority for agent definitions and updates sync via a GitHub Action.

## Decisions (confirmed)

- **Agents are resolved by name, not by stored id.** The repo holds no `agent_id` or `environment_id`.
  Deploy matches an agent by name via `beta.agents.list()` (update if found, create if not); lik-ui
  resolves each agent name → id at startup. Chosen because it makes GitHub the true single source and,
  critically, survives re-initializing into a new workspace with **no id rewrites** — which matches how
  workspaces are actively being migrated.
- **Environments are managed by the same pipeline.** Each agent spec declares its environment; deploy
  resolves/creates the environment by name and the agent references it by name. Keeps both halves of the
  agent definition GitHub-authoritative (no env config drifting back to Console-only edits).
- **The skill pipeline is the model.** Manual `workflow_dispatch`, PR-review-plus-deliberate-deploy as
  the gate, Anthropic SDK deploy script, no ungated path to a running agent.
- **All three resource types live under a single `claude_platform/` folder** — `claude_platform/skills/`,
  `claude_platform/agents/`, `claude_platform/environments/`. This **moves skills out of `.claude/skills/`**,
  which means the two skills are **no longer Claude Code skills** — `/lik-query-project-index` and
  `/lik-sync-catalog-from-project-indexes` stop being invocable in Claude Code. Accepted deliberately in
  favor of one grouped tree for all Managed-Agents platform resources. (The alternative — keeping skills
  dual-use in `.claude/skills/` — was rejected; the grouping was preferred over Claude Code usage.)

## The core constraint that shaped this

Skills carry no id into the repo because nothing in the repo's *runtime* references a `skill_id`.
Agents differ: **lik-ui needs the concrete `agent_id`/`environment_id` at runtime** to launch sessions
(today's [agents.toml](lik-ui/src/lik_ui/agents.toml)). So "GitHub source of truth, no ids in repo" could
not transfer for free — it required moving id-resolution into lik-ui's startup (the confirmed decision
above), rather than storing ids the deploy would otherwise have to write back.

## Requirements

1. **Declarative agent specs in the repo, in the platform's raw format.** All Managed Agents platform
   resources are grouped under a repo-root **`claude_platform/`** folder: `claude_platform/agents/`,
   `claude_platform/environments/`, and `claude_platform/skills/` (skills moved here from `.claude/skills/`
   — see "Skills relocation" below). Not under `.claude/`, which is Claude Code's own convention space.
   The on-disk format is the **Claude Platform's own agent export/import YAML** — the exact
   shape `beta.agents.create`/`update` consumes (name, model, description, system, mcp_servers, tools +
   permission policies, skills, metadata). Chosen so there is no bespoke schema to maintain and no
   translation drift: capturing an agent from the Console (cf. the capture one-liner in
   [init_workspace.py](lik-ui/scripts/init_workspace.py)) is copy-paste. Two deviations from the raw
   export are required (below): `skills` by name, and environment held separately.

   - **Environments** are separate platform resources with no place in the raw agent block, so they live
     in their own raw-format files (e.g. `environments/<name>.yaml`), also round-trippable. The
     agent↔environment pairing (which env an agent runs in) lives in the name roster, replacing today's
     `default_environment_id`.
   - **Accepted cost:** the raw format's `system:` is a single quoted YAML line, so a long prompt is one
     long line — worse to read/diff than a markdown body. Accepted as the price of round-trip fidelity and
     zero translation code.

2. **Skills referenced by name, not `skill_id`.** In the raw export, `skills` entries carry a platform
   `skill_id`; storing that in the repo would reintroduce the id-rewrite-on-re-init problem the by-name
   decision exists to avoid (skill_ids change per workspace exactly as agent_ids do). So the one
   documented divergence from the raw format: each `skills` entry names the skill (its directory name),
   and the deploy translates name → `skill_id` immediately before the SDK call, pinning `version:
   "latest"`. Reuses `find_existing_skill_id` ([scripts/deploy_skills.py](scripts/deploy_skills.py)) and
   the merge logic in [scripts/attach_skills_to_agent.py](scripts/attach_skills_to_agent.py). No
   `skill_id`s in the repo.

3. **Skills must exist on the platform before agent deploy.** Guarantee ordering by running the
   skills-deploy step before the agents-deploy step in the pipeline (reuses `deploy_skills.py`
   unchanged; the agent deploy stays a pure resolve-and-attach). A referenced skill missing at deploy
   time is a fail-fast error, not a silent skip.

4. **A GitHub Action deploys agents**, mirroring `deploy-skills.yml`: manual `workflow_dispatch` with an
   agent-choice input (`all` | a specific agent, default `all`), `environment: prod`, the same
   workspace-scoped `ANTHROPIC_API_KEY` secret. The deploy script, per selected agent: reads the spec,
   resolves the environment by name (create if missing), resolves referenced skills by name, then
   `create`s the agent if no name match exists or `update`s (new version) if it does. Preserves the
   agent's other fields on update (mirror the field-preservation care already in
   `attach_skills_to_agent.py`).

5. **lik-ui resolves agents (and their environments) by name at startup.** The roster
   ([agents.toml](lik-ui/src/lik_ui/agents.toml)) becomes a list of agent **names** to offer, not
   `agent_id:environment_id` pairs. At startup lik-ui resolves each name → id via the SDK and produces
   the same `list[AgentOption]` the app already consumes downstream unchanged. The human-readable label
   continues to come live from the agent definition (as today).

6. **`init_workspace.py` writes/points to a spec, not hardcoded dicts.** Creating the initial agent
   becomes: author (or update) its spec under `agents/`, then run the deploy. The `AGENT_DEFINITION` /
   `ENV_DEFINITION` constants and the roster-id-append logic are retired in favor of the spec + name
   roster. (This subsumes the create path; `init_workspace` may remain as a thin workspace-bootstrap
   wrapper over the same deploy code.)

7. **Skills relocation: `.claude/skills/` → `claude_platform/skills/`.** The move drops Claude Code
   skill discovery (accepted). Ripple effects the implementation must handle:
   - `SKILLS_ROOT` in [scripts/deploy_skills.py](scripts/deploy_skills.py) repointed to
     `claude_platform/skills/`; the agent deploy's skill-name resolution reads the same new path.
   - `deploy-skills.yml` path filters / any `.claude/skills` references updated.
   - Repo docs that reference `.claude/skills/` (e.g. `CLAUDE.md`'s skill-naming note, `scripts/README.md`,
     the skill plan) updated to the new location.
   - Tests referencing the old path updated.
   - The move should land atomically with the `SKILLS_ROOT` change so the skill deploy is never pointed at
     a nonexistent path.

## Relationship to the prior `agents.toml` doc

[2026-07-23-agents-config-as-checked-in-file-requirements.md](docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md)
moved the roster out of SSM into a checked-in file of `agent_id:environment_id` pairs. This doc keeps
the "checked-in, PR-reviewed roster" decision but **changes its content from id-pairs to agent names**
(Requirement 5 above supersedes that doc's Requirement 1). The startup-loads-the-file and
init-script-appends behaviors carry forward; only the stored values change (names, resolved to ids at
startup).

## Success criteria

- A maintainer edits an agent's system prompt (or skills, model, tools) by editing files under
  `agents/`, opens a PR, and after review runs the Action to sync the change to the live agent — with no
  Console editing and no new-agent duplication.
- Re-initializing into a fresh workspace requires no id edits in the repo: names resolve to whatever ids
  the new workspace assigns.
- Deploying an agent that references a skill Just Works as long as the skill is deployed first; a missing
  skill fails the run with a clear message.
- lik-ui offers the same agent picker and resolves connections/chat identically; only the roster's
  stored form (names, not ids) and a startup resolution step changed.
- No `agent_id`/`environment_id` values remain checked into the repo.

## Out of scope (deferred)

- **API-key creation** — Console-only by design; unchanged (`init_workspace.py` docstring).
- **Non-engineer editing UI / admin console** for agents — deferred until a recurring non-engineer editor
  exists (mirrors the skill pipeline's stance).
- **Per-agent staged rollout / pinned skill versions** — agents pin skills at `latest`; staged rollout is
  a supported-but-deferred escalation (same as the skill plan).
- **Auto-deploy on merge** — manual dispatch keeps a human in control of *when* a prod agent changes.
- **Database-backed agent registry / hot reload** — restart-to-change is accepted (per the prior roster doc).

## Assumptions / open items for planning

- **Spec format decided: the platform's raw agent export YAML** (Requirement 1), with `skills` by name
  and environment held in a separate raw-format file. Planner still finalizes file layout details
  (single `agents/<name>.yaml` vs. a directory per agent; where the roster lives) and how the
  name-for-`skill_id` substitution is applied to the raw block before the SDK call (parse → swap the
  `skills` list → send). The rejected alternative (markdown + frontmatter mirroring `SKILL.md`) reads
  better for the long prompt but requires a bespoke schema and a two-way translation to/from the platform
  shape — that maintenance and drift cost is why the raw format won.
- **Environment update semantics.** Whether `beta.environments` supports update or only create is
  unverified. If create-only, changing an environment's config may require a new environment *name*
  (and the spec/pipeline must handle that), rather than an in-place update. Verify against the SDK during
  planning.
- **Startup resolution cost/caching in lik-ui.** Resolving names → ids adds a `beta.agents.list()` (and
  environment lookup) at boot. Confirm this is acceptable at startup and whether any caching is warranted;
  the roster is already loaded once at boot with no hot reload.
- **Agent name uniqueness.** By-name resolution requires agent names (and environment names) to be unique
  within the workspace; the deploy should assert uniqueness of a match (mirrors the skill plan's
  name-uniqueness note).
- **Repo visibility** (private assumed). If names/prompts must not disclose org structure and the repo is
  public, revisit — same caveat the prior roster doc raised for ids.
- **One agent exists today.** This pipeline is built for a roster that grows; if it stays at one agent
  indefinitely, the manual-run ergonomics still hold but the payoff is smaller. Not a blocker — the
  declarative-spec + update-path value applies even at n=1 (it removes Console hand-editing).
