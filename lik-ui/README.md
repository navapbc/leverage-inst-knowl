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
LIK_UI_DB_PORT=5433 uv run pytest   # compose publishes Postgres on 5433
```

The suite refuses to run unless `LIK_UI_DB_NAME` ends in `_test` (it truncates tables),
and it targets the compose default database `likuidb_test`.

## TODO: cache agent `describe` results

The home (agent picker) and connections pages call `AgentsClient.describe(agent_id)` on
every load — one Anthropic SDK `retrieve` per configured agent. With a single agent that's
one call, but the agent definition (system prompt, model, declared servers) changes rarely.
If the agent list grows, cache these results (e.g. a short TTL) rather than fetching per
request.

## TODO: show full skill instructions (SKILL.md)

The connections page can show each skill's name and description, but not its full instructions
(SKILL.md). The SDK exposes the content via `beta.skills.versions.download` (a zip archive), but
that endpoint returns 403 "Downloading skill content is not supported with this credential type"
for the credential lik-ui currently uses. Surfacing SKILL.md needs a credential with skill-download
permission (likely a standard org API key rather than the managed-agent credential). Until then,
`describe_skill` returns name and description only.

## Configuration

All config is `LIK_UI_`-prefixed; see `.env.example`. Outside `local`/`test`, the app
fails closed if app-login, vault, or agent config is missing. Secrets are never logged.

## OAuth connector: why it's hand-rolled

`src/lik_ui/oauth_connector.py` implements MCP OAuth from scratch rather than using a
library. This is a deliberate choice, not an oversight.

The bulk of that file is discovery and client acquisition — RFC 9728 protected-resource
metadata, RFC 8414 / OpenID authorization-server metadata, and RFC 7591 dynamic client
registration. General OAuth libraries (authlib, httpx-oauth) don't cover any of these;
they only handle the small, already-clean tail (PKCE, the authorization URL, and token
exchange, ~40 lines). Adopting one would add a dependency without removing the hard parts.

The one library that covers the whole chain is the official MCP Python SDK's OAuth client
(`mcp.client.auth`). It's built for a client that *holds* the tokens and injects them into
its own MCP requests. lik-ui deliberately splits **connection** (this app acquires tokens
and deposits them in the user's vault) from **usage** (a separate Managed Agent consumes
them), so the SDK's token-lifecycle model doesn't fit — we'd fight its assumptions to reuse
its discovery internals. If a future SDK release exposes discovery + DCR as standalone
helpers, revisit replacing `discover()` and `_acquire_via_dcr()`.
