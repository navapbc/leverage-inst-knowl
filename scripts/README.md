# Skill deploy tooling

Operational scripts that publish the repo's skill directories (`.claude/skills/<name>/`) to Claude
Managed Agents. GitHub is the source of truth for skill instructions; these scripts push them to the
platform. See `docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md`.

## `deploy_skills.py` — publish a skill version (recurring)

Packages a skill directory and creates a new **version** on the platform (or creates the skill on
first deploy). Versions are immutable; agents that pin the skill to `latest` pick up the new version
on their next session.

Normally run by the **Deploy skills to Managed Agents** GitHub Action (manual dispatch, choose which
skill). To run locally against the real API:

```sh
ANTHROPIC_API_KEY=sk-ant-api03-... uv run python deploy_skills.py --skill all
# or a single skill:
ANTHROPIC_API_KEY=sk-ant-api03-... uv run python deploy_skills.py --skill lik-query-project-index
```

`ANTHROPIC_API_KEY` must be a **standard org API key** scoped to the workspace that holds the
agents/skills (not an admin key). In CI it comes from the `ANTHROPIC_API_KEY` secret on the `prod`
environment.

## `attach_skills_to_agent.py` — pin skills to an agent (one-time bootstrap)

Attaches skills to a Managed Agent at `version: "latest"` so deploys roll out automatically. Run
this **once per new skill**, not on every deploy — once an agent references a skill at `latest`, new
versions from `deploy_skills.py` are picked up with no further attach step.

```sh
ANTHROPIC_API_KEY=sk-ant-api03-... LIK_AGENT_ID=agent_01... \
  uv run python attach_skills_to_agent.py --skill all
```

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
