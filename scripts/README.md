# Managed Agents deploy tooling

Operational scripts that publish the repo's `claude_platform/` specs to Claude Managed Agents. GitHub
is the source of truth; these scripts push definitions to the platform:

- `claude_platform/skills/<name>/` — skill directories → `deploy_skills.py`
- `claude_platform/agents/<name>.yaml`, `claude_platform/environments/<name>.yaml` — agent and
  environment specs (the platform's raw export YAML) → `deploy_agents.py`

See `docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md` (skills) and
`docs/plans/2026-07-24-001-feat-agent-spec-deploy-pipeline-plan.md` (agents).

## `deploy_skills.py` — publish a skill version (recurring)

Packages a skill directory and creates a new **version** on the platform (or creates the skill on
first deploy). Versions are immutable; agents that pin the skill to `latest` pick up the new version
on their next session.

Normally run by the **Deploy skills to Claude platform** GitHub Action (manual dispatch, choose which
skill) — useful for updating a skill without redeploying its agents. `deploy_agents.py` also invokes
it for each agent's referenced skills. To run locally against the real API:

```sh
ANTHROPIC_API_KEY=sk-ant-api03-... uv run python deploy_skills.py --skill all
# or a single skill:
ANTHROPIC_API_KEY=sk-ant-api03-... uv run python deploy_skills.py --skill query-project-index
```

`ANTHROPIC_API_KEY` must be a **standard org API key** scoped to the workspace that holds the
agents/skills (not an admin key). In CI it is fetched from SSM (`/ik-arch/prod/shared/ANTHROPIC_API_KEY`)
via GitHub OIDC — one shared key, no GitHub secret — using a role scoped to reading only that parameter
(see `infra/iam_github_oidc.tf`). This is the same key the lik-ui container reads.

## `deploy_agents.py` — publish agents + environments (recurring)

Deploys the agent and environment specs under `claude_platform/`, resolving each **by name**
(create if absent, else update in place). An agent's `skills` are listed by name; deploy_agents
**publishes exactly those skills first** (via `deploy_skills.deploy_skill` — create or new version),
then attaches them at `latest`. So only the skills an agent actually references are published — no
separate skills step, no blanket `--skill all`. Environments are always synced so an agent's
environment exists.

Normally run by the **Deploy agents to Claude platform** GitHub Action (manual dispatch, choose which
agent). To run locally against the real API:

```sh
ANTHROPIC_API_KEY=sk-ant-api03-... uv run python deploy_agents.py --agent all
# or a single agent (filename stem under claude_platform/agents/):
ANTHROPIC_API_KEY=sk-ant-api03-... uv run python deploy_agents.py --agent knowledge-search
# --dry-run prints the plan (still queries the platform to decide create-vs-update) without publishing.
```

To publish a skill on its own — independent of any agent — use `deploy_skills.py` (or the
**Deploy skills to Claude platform** workflow) directly.

An agent references skills by **name**, not `skill_id` — no platform ids live in the repo. lik-ui
likewise resolves agent/environment names to ids at startup, so the roster (`lik-ui`'s `agents.toml`)
and specs stay id-free and survive re-initializing into a new workspace.

## Bootstrapping a fresh workspace

`lik-ui/scripts/init_workspace.py` runs both deploy scripts (skills, then agents) against a target
workspace key and prints the SSM key line + next steps. Use it when standing up a new workspace; it
orchestrates the same code CI uses.

## Two platform upload rules (both enforced by `deploy_skills.py`)

The Managed Agents skill-upload endpoint returns opaque `400`s if either rule is broken, so the
script guards them before uploading:

1. **Single top-level folder.** Every file is uploaded under one folder — arcnames are
   `<name>/<relpath>`. A bare `SKILL.md` at the archive root is rejected.
2. **Folder name must equal the skill name.** The top-level folder must match the `name:` in
   SKILL.md (lowercased). The script asserts `name == <directory name>` and fails fast.

## Tests

```sh
uv run pytest
```

Tests fake the Anthropic SDK client (no network, no key needed).
