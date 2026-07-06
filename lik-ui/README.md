# lik-ui

A hosted web app that lets a Nava user sign in, connect the data sources a Claude Managed
Agent needs (lik-mcp, Atlassian, more later), and chat with that agent. lik-ui runs the
OAuth flow for each source and deposits the resulting tokens in the user's Claude
credential vault — the part the Managed Agents platform does not do for you.

See the design and plan:
- Requirements: `docs/brainstorms/2026-07-06-01-lik-ui-managed-agent-app-requirements.md`
- Plan: `docs/plans/2026-07-06-001-feat-lik-ui-managed-agent-app-plan.md`

## Setup

Uses Python 3.14 + uv (see the repo root `mise.toml`).

```
uv venv
uv pip install -e ".[dev]"
cp .env.example .env   # edit as needed
```

Run everything through `uv run` (it uses `.venv` automatically).

## Run

```
docker compose up -d db          # Postgres for the store
uv run python -m lik_ui          # serves on http://127.0.0.1:8001
```

Or the whole stack in containers:

```
docker compose up
```

## Test

```
docker compose up -d db
uv run pytest
```

The suite refuses to run unless `LIK_UI_DB_NAME` ends in `_test` (it truncates tables).

## Configuration

All config is `LIK_UI_`-prefixed; see `.env.example`. Outside `local`/`test`, the app
fails closed if app-login, vault, or agent config is missing. Secrets are never logged.
