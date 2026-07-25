# Requirements: Make lik-ui private-repo-safe by bundling docs into the image

**Date:** 2026-07-24
**Status:** Ready for planning — the blocking dependency (agent-spec deploy pipeline) has shipped
**Scope:** Standard (removes a runtime dependency; enables flipping the repo private)
**Related:**
[docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md](docs/brainstorms/2026-07-24-01-agent-spec-deploy-pipeline-requirements.md)
(shipped in commit `065048a`; its specs are what make repo privacy desirable),
[docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md](docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md)
(first flagged this as a deferred dependency — "private → token or bundle").

## Problem

lik-ui has exactly one thing keeping the GitHub repo **public**: a tokenless raw fetch in
[lik-ui/src/lik_ui/repo_docs.py](lik-ui/src/lik_ui/repo_docs.py) that reads markdown from
`raw.githubusercontent.com/{skills_repo}/{skills_ref}/{path}` (the repo is `navapbc/leverage-inst-knowl`,
i.e. this repo). Two viewer features ride on it:

1. **"Show full skill instructions"** — [agents.py](lik-ui/src/lik_ui/agents.py) `GET /skill-details`
   (login-gated) fetches `claude_platform/skills/<name>/SKILL.md` via
   [skill_docs.py](lik-ui/src/lik_ui/skill_docs.py).
2. **The FAQ page** — [faq.py](lik-ui/src/lik_ui/faq.py) `GET /faq` fetches `faq.md`.

Agent specs now live in the repo — the shipped agent-spec pipeline exports system prompts and MCP
server URLs into `claude_platform/agents/` and `claude_platform/environments/`. Keeping the repo public
exposes them. The repo should be able to go **private**, which breaks the tokenless fetch.

## Decision (confirmed direction)

Remove both public-repo fetches (chosen over a server-side GitHub token), handled per-doc:

- **Skill instructions (`SKILL.md`) → link-only.** The connections page stops fetching and rendering
  `SKILL.md` in-app; it shows only the "view on GitHub" link. This drops the fetch entirely — no
  bundling of `claude_platform/skills/` is needed. (Revised during planning; the in-app instruction
  render was judged not worth the bundling complexity.)
- **FAQ (`faq.md`) → bundled by relocation.** `faq.md` is lik-ui's own content with no other consumer,
  so it moves into the lik-ui package (the same way [agents.toml](lik-ui/src/lik_ui/agents.toml) ships)
  and is read locally. The FAQ page still renders inline. This keeps `faq.md` inside the narrow
  `lik-ui/` Docker build context, so no Docker/CI/build-context changes are required.

Accepted cost: refreshing the bundled FAQ requires a redeploy (no live edit-to-view), consistent with
lik-ui's existing restart-to-change posture.

## Requirements

1. No production code path fetches `SKILL.md` or `faq.md` from `raw.githubusercontent.com`. The
   connections page no longer fetches/renders skill instructions; `faq.md` is read from the lik-ui
   package at runtime.
2. `faq.md` is packaged into the lik-ui image (relocated into the package) and read locally. The FAQ
   page renders it inline, unchanged from the viewer's perspective.
3. **The "view on GitHub" links are retained.** lik-ui's viewers are internal staff who have access to
   the private repo, so the links stay useful; they resolve for anyone authenticated to GitHub with repo
   access and 404 only for those without — an acceptable, pre-existing property of private-repo links.
   These links are pure URL construction (no network), so nothing here affects them.
4. After merge, the repo can be flipped to **private** with no lik-ui runtime regression.
5. `settings.skills_repo` / `settings.skills_ref` are retained only insofar as they are still needed to
   build the "view on GitHub" blob URLs (repo slug + ref). The fetch-only URL builder and settings usage
   are removed.
6. The connections page carries a note that the linked GitHub instructions are the repo source and **may
   not exactly match what is currently deployed** to the running agents — a workaround for not being able
   to fetch the skill's deployed content from the Claude platform. Exact wording/placement is the
   planner's to finalize.

## Why relocation avoids the build-context problem

The Docker build context is `lik-ui/` in both local (`docker-compose` `build: .`) and CI
([deploy-images.yml](.github/workflows/deploy-images.yml) `docker build ./lik-ui`). Files at the repo
root and under `claude_platform/` are outside that context, so the Dockerfile cannot reach them without
widening the context or staging copies — the original reason "bundle everything" was complex. Dropping
in-app skill instructions removes the `claude_platform/skills/` case entirely, and `faq.md` (lik-ui's
own content, no other consumer) can simply live in the package — inside the existing context and the
existing `package-data`. No Docker, CI, or build-context changes.

## Success criteria

- With the repo set private and no GitHub token configured, a freshly built/deployed lik-ui serves the
  FAQ page correctly and the connections page shows skill entries with working "view on GitHub" links.
- No production code path issues a `raw.githubusercontent.com` request.
- "View on GitHub" links still render and point at correct blob URLs.

## Resolved open items

- **View-on-GitHub links:** keep them (Requirement 3). Viewers have repo access.
- **Skill instructions in-app:** dropped — link-only (revised during planning).
- **Freshness:** redeploy-to-refresh is accepted; matches lik-ui's restart-to-change posture.
- **Skills-folder coordination:** moot now that skill instructions are not bundled.
