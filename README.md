# Leveraging Institutional Knowledge (LIK)

A company's knowledge is scattered across many systems — storage, wikis, trackers, chat, CRM, HR, and
more. To answer one question, every AI agent, app, and person ends up searching all of them, over and
over: slow, costly, inconsistent, and prone to missing the most trusted or current answer.

LIK adds a **Discovery Layer** on top of those systems. Knowledge stays where it already lives — each
source stays authoritative and keeps controlling who may see what — while the Discovery Layer makes it
fast to find and reuse, without copying everything into one place and without becoming a competing
authority. Almost everything it stores is disposable, recomputed from the sources on demand; only what a
person touched by hand is kept.

Start with the design docs in [`v0.5/`](v0.5/) — [`01-overview.md`](v0.5/01-overview.md) is the
plain-language introduction.

## Repository layout

| Path | What it is |
|------|------------|
| [`v0.5/`](v0.5/) | The architecture and design docs (overview, concepts, examples, strategy, architecture, access control, storage, open questions). Source of truth for intent; the code is implemented against these. |
| [`lik-mcp/`](lik-mcp/) | MCP service in front of a Postgres store holding the **Catalog** and **Confirmation signals**. The AI calls a fixed menu of intent-named tools — never the database directly. |
| [`lik-ui/`](lik-ui/) | Hosted web app where a user signs in, connects the data sources an agent needs, and chats with a Claude Managed Agent. Runs the OAuth flow per source and deposits tokens in the user's credential vault. |
| [`claude_platform/`](claude_platform/) | GitHub-sourced specs for the Managed Agents platform: `skills/`, `agents/`, and `environments/`. Referenced by name, not platform id. |
| [`scripts/`](scripts/) | Deploy tooling that publishes `claude_platform/` specs to Claude Managed Agents (`deploy_skills.py`, `deploy_agents.py`). |
| [`infra/`](infra/) | Terraform for the production AWS (Lightsail, us-east-1) deployment of `lik-mcp` and `lik-ui`. |
| [`docs/`](docs/) | Runbook, OAuth notes, and per-feature `brainstorms/`, `plans/`, and `solutions/`. |

Each component has its own `README.md` with setup, run, and test instructions.

## Getting started

Tooling is pinned via [`mise`](https://mise.jdx.dev/) (see [`mise.toml`](mise.toml)) — Python 3.14 and
`uv`. Initialize the environment with:

```sh
eval "$(mise activate)" && mise list
```

Then follow the component you want to work on:

- [`lik-mcp/README.md`](lik-mcp/README.md) — the Catalog + Confirmations MCP service
- [`lik-ui/README.md`](lik-ui/README.md) — the web app / agent front end
- [`infra/README.md`](infra/README.md) — the production deployment
- [`docs/deploy-runbook.md`](docs/deploy-runbook.md) — deploy/rebuild procedure

## Contributing

All changes go through a branch and PR — never commit or push directly to `main`. See
[`CLAUDE.md`](CLAUDE.md) for the working conventions this repo follows.
