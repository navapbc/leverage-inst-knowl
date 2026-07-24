# Requirements: Make lik-ui private-repo-safe by bundling docs into the image

**Date:** 2026-07-24
**Status:** Parked — revisit after the agent-spec deploy pipeline ships
**Scope:** Standard (removes a runtime dependency; enables flipping the repo private)
**Related:**
[docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md](docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md)
(the agent-spec pipeline whose specs make repo privacy desirable),
[docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md](docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md)
(first flagged this as a deferred dependency — "private → token or bundle").

## Problem

lik-ui has exactly one dependency on the GitHub repo being **public**: a tokenless raw fetch in
[lik-ui/src/lik_ui/repo_docs.py](lik-ui/src/lik_ui/repo_docs.py) that reads markdown from
`raw.githubusercontent.com/{skills_repo}/{skills_ref}/{path}`. Two viewer features ride on it:

1. **"Show full skill instructions"** — [skill_docs.py](lik-ui/src/lik_ui/skill_docs.py) fetches
   `<skills-path>/<name>/SKILL.md` for the `/skill-details` endpoint (connections page).
2. **The FAQ page** — fetches `faq.md`.

Once agent specs (system prompts, MCP server URLs) live in the repo, keeping it public exposes them.
The repo should be able to go **private**, which breaks the tokenless fetch.

## Decision (confirmed direction)

**Bundle the docs into the lik-ui image at build time** (chosen over a server-side GitHub token).
lik-ui reads the docs from its own package/filesystem instead of fetching over the network — the same
way [agents.toml](lik-ui/src/lik_ui/agents.toml) is already shipped as package data. This removes both
the network dependency and the visibility dependency. Accepted cost: refreshing a doc requires a
redeploy (no live edit-to-view), consistent with lik-ui's existing restart-to-change posture.

## Requirements (to flesh out when revisited)

1. The `SKILL.md` files and `faq.md` (any doc `repo_docs.py` currently fetches) are packaged into the
   lik-ui image at build and read locally at runtime; no runtime fetch from GitHub.
2. `repo_docs.py` / `skill_docs.py` read from the bundled location instead of
   `raw.githubusercontent.com`; the "view on GitHub" hyperlink affordance is retained (or revisited if
   the repo is private and the link would 404 for viewers).
3. The build copies the docs from their repo location into the package (note: the agent-spec plan moves
   skills to `claude_platform/skills/<name>/SKILL.md` — the bundling must read from the then-current
   location).
4. After merge, the repo can be flipped to **private** with no lik-ui runtime regression.
5. `settings.skills_repo` / `settings.skills_ref` are removed or repurposed once the fetch is gone.

## Open items for later

- Whether to keep the "view on GitHub" links (dead for external viewers on a private repo) or replace
  with an in-app view only.
- Freshness: confirm redeploy-to-refresh is acceptable for skill instructions and FAQ (expected yes).
- Coordination: this must read docs from wherever the agent-spec plan leaves the skills folder.
