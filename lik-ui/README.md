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

## Deploy against a managed Postgres

The app never creates its own schema, and there's no migration step on startup. When you
deploy against an external/managed Postgres (not the compose one), the Docker entrypoint's
`db/init.sql` hook does not run — apply the schema by hand once before first boot:

```
psql "host=$LIK_UI_DB_HOST port=$LIK_UI_DB_PORT dbname=$LIK_UI_DB_NAME \
  user=$LIK_UI_DB_USER password=$LIK_UI_DB_PASSWORD sslmode=$LIK_UI_DB_SSLMODE" \
  -f db/init.sql
```

Use the same `LIK_UI_DB_*` values the app runs with (see `.env.example`); this is the exact
connection string `settings.conninfo` builds. `db/init.sql` is idempotent
(`CREATE TABLE IF NOT EXISTS`), so re-running it is safe.

## Test

```
docker compose up -d db
LIK_UI_DB_PORT=5433 uv run pytest   # compose publishes Postgres on 5433
```

The suite refuses to run unless `LIK_UI_DB_NAME` ends in `_test` (it truncates tables),
and it targets the compose default database `likuidb_test`.

> **Gotcha:** if your `.env` sets `LIK_UI_DB_NAME` to a non-`_test` name (e.g. `likuidb_local`
> for running the app locally), pytest picks it up and **silently skips every DB-backed test**
> — you'll see a green run that actually covered almost nothing. Override the name on the
> command line so the suite hits the test database:
>
> ```
> LIK_UI_DB_NAME=likuidb_test LIK_UI_DB_PORT=5433 uv run pytest
> ```

## Smoke test

After a deploy (especially a domain/URL change), verify the OAuth paths end-to-end against
the live app:

- Open the app at its public URL and sign in — it loads with a valid TLS lock and login
  succeeds (exercises the app-login callback, `/auth/callback`).
- Connect one data source (exercises `/connections/callback`) and make a lik-mcp call
  (exercises the resource URL; expect a one-time reconnect after a resource-URL change).

## TODO: cache agent `describe` results

The home (agent picker) and connections pages call `AgentsClient.describe(agent_id)` on
every load — one Anthropic SDK `retrieve` per configured agent. With a single agent that's
one call, but the agent definition (system prompt, model, declared servers) changes rarely.
If the agent list grows, cache these results (e.g. a short TTL) rather than fetching per
request.

## DONE: show full skill instructions (SKILL.md)

Expanding a skill's "Details" on the connections page shows its full `SKILL.md` alongside the
name and description. The instructions come from **GitHub**, the single source of truth (skills
are deployed *to* Managed Agents from `.claude/skills/<name>/` — see
[`scripts/README.md`](../scripts/README.md)), not from Managed Agents:
`beta.skills.versions.download` is a dead end (it 403s with "Downloading skill content is not
supported with this credential type"). `skill_docs.py` fetches the raw
`.claude/skills/<name>/SKILL.md` from the **public** repo with a plain unauthenticated GET —
addressed by skill *name*, which the deploy pipeline guarantees equals the directory. The repo
and ref are configurable via `LIK_UI_SKILLS_REPO` (default `navapbc/leverage-inst-knowl`) and
`LIK_UI_SKILLS_REF` (default `main`).

Any fetch failure (404, non-200, timeout, or the repo later going private) degrades gracefully:
the view shows a fallback line linking the file on GitHub so the user can open it themselves,
never a page or endpoint error. The `SKILL.md` is rendered as Markdown (headings/lists/links)
client-side with the same `marked` + `DOMPurify` pipeline as the chat transcript — the endpoint
still returns the raw text, and if the CDN libs don't load the view falls back to the literal
text so instructions are never lost.

Deferred: caching the fetched file (align with the `describe`-caching TODO above if per-expand
fetches become a concern).

## TODO: decide how users get Anthropic API access

lik-ui talks to the Managed Agents platform with a single Anthropic credential today. Before
multiple users depend on it, decide how each user's calls are authorized. Two options:

1. **Each user provides their own Anthropic API key.** Simplest to reason about — every user's
   agent traffic bills and authorizes under their own key, nothing is shared. Open questions:
   whether managed agents and skills created under one user's key are visible to or usable by
   others (sharing/visibility model), and where users obtain a key.

2. **Configure Workload Identity Federation.** Map Nava users to Anthropic API access without
   handing out per-user keys — see
   https://platform.claude.com/settings/workload-identity-federation. Keeps agents and skills
   under one org-owned identity while attributing calls to the mapped user.

## DONE: dedicated Claude Workspace for LIK

LIK's Anthropic usage now lives in its own Claude Workspace
(https://platform.claude.com/settings/workspaces) rather than the org's default one. A
dedicated workspace isolates LIK's spend, rate limits, and API keys, so its usage can be
tracked and capped without affecting other Nava work, and access can be scoped to just the
people who run it.

**Why a separate workspace was required.** The lik-ui app uses the Claude
Platform and stores its OAuth secrets in "Credential vaults", which are visible to *everyone*
with access to the workspace they live in — and the vault IDs can be used to get access to
data as other users, which is an impersonation risk. In the shared `Default` workspace,
every member could therefore see LIK's OAuth secrets. To close that gap, a separate `lik-ui`
workspace was created that only the LIK developers and IT admins can access, so the OAuth secrets
are protected.

More details at https://platform.claude.com/docs/en/manage-claude/workspaces.

## TODO: streaming timeouts on the deployed ingress (scaling)

The chat endpoint streams tokens to the browser over **SSE** (`StreamingResponse` with
`media_type="text/event-stream"`, consumed by an `EventSource`). On the current Lightsail
container-service deployment, the managed ingress has a **fixed, undocumented,
non-configurable timeout**: a long LLM generation whose stream exceeds it is cut
mid-response with a 504-class error, and there is no knob to raise the ceiling. Do **not**
front the app with a Lightsail distribution/CDN either — its 30s origin timeout and
chunked-only handling break SSE. If long responses start dying mid-stream, suspect the
ingress timeout before the app code. The fix when this becomes a hard limit is to move off
the managed Lightsail ingress to ECS/EC2 behind an ALB (configurable idle timeout);
switching the browser transport to WebSockets is a lighter mitigation if staying on
Lightsail. See `../domain-name.md` (Caveat: real-time streaming and timeouts).

## Configuration

All config is `LIK_UI_`-prefixed; see `.env.example`. Outside `local`/`test`, the app
fails closed if app-login, vault, or agent config is missing. Secrets are never logged.

`LIK_UI_APP_BASE_URL` is the public HTTPS URL the app is reached at; **both OAuth callback
URLs are derived from it** (`{base}/auth/callback` for login, `{base}/connections/callback`
for data sources — see `src/lik_ui/__main__.py`). It must match the redirect URIs registered
with each OAuth provider. In the production Terraform deploy this value is not set by hand —
it is computed from the container service's URL (or a custom domain when configured); see
[`../infra/README.md`](../infra/README.md) "URL-derived env values and custom domains".

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

## TODO: move OAuth client registrations off personal ownership

**Reminder to fix before other users depend on these connections.** Some source
connections currently use OAuth *client* registrations (the client ID/secret in `.env`)
owned by a personal account. This is a durability and trust liability: the client
identifies **this app**, not the end user — one registration serves all users, and each
user's own token is what lands in their vault. But if the registration is personally
owned, the consent screen shows a personal app, quotas and security contacts route to an
individual, and every user's connection breaks if that person leaves or loses access.

The fix per source is to re-register (or transfer) the client under **Nava org
ownership**, with more than one owner. This is configuration, not code — swap the resulting
values into `.env`. Particulars differ by MCP service:

- **Atlassian (Confluence/Jira)** — No action. Atlassian supports Dynamic Client
  Registration, so lik-ui self-registers a client at runtime; there is no static client
  ID/secret to own. See `discover()` / `_acquire_via_dcr()` in `oauth_connector.py`.

- **GitHub** — Currently a personal OAuth App. Transfer it to the Nava GitHub org
  (the app's settings → *Transfer ownership*), or register a fresh org-owned OAuth App.
  Org owners (plural) then control it. Client ID survives a transfer; rotate the secret and
  update `LIK_UI_GITHUB_CLIENT_ID` / `LIK_UI_GITHUB_CLIENT_SECRET` if it changes. (If Nava
  security later needs per-repo granularity or org-admin install approval, a GitHub *App* —
  a different primitive with a different token model — is the stricter option; only switch
  if required, as it is a larger change than a transfer.)

- **Google Drive** — Registered under a Google Workspace (enterprise) account; survival
  after the registrant leaves is **not** guaranteed. The OAuth client lives inside a GCP
  project and the consent screen is tied to that project. Verify in GCP Console → *IAM*
  that the project sits under the Nava Google Cloud **organization** (not a standalone
  personal project) and add a second **Owner** (a Nava admin or group). Keep the consent
  screen *User Type* = **Internal** so consent is restricted to the Nava Workspace org.
  Values: `LIK_UI_GDRIVEMCP_CLIENT_ID` / `LIK_UI_GDRIVEMCP_CLIENT_SECRET`.

- **lik-mcp** — Same Google-client shape as Google Drive (Google is the AS, no DCR). The
  client reuses lik-mcp's own `LIK_OAUTH_CLIENT_ID` (it is the audience lik-mcp validates),
  so ownership follows wherever that Google client is registered — apply the same GCP
  org-ownership check as Google Drive. Values: `LIK_UI_LIKMCP_CLIENT_ID` /
  `LIK_UI_LIKMCP_CLIENT_SECRET`.

- **App login (Google OIDC, identity-only)** — Not a data source, but the same GCP
  project/consent-screen ownership applies to `LIK_UI_APP_OAUTH_CLIENT_ID` /
  `LIK_UI_APP_OAUTH_CLIENT_SECRET`. Include it in the same GCP ownership check.

- **Slack** — Not built yet, but the **official Slack MCP server** (hosted at
  `https://mcp.slack.com/mcp`, GA Feb 2026) fits the existing connector like GitHub does —
  no Slack-specific code. It does per-user OAuth 2.0/PKCE and issues per-user tokens that
  enforce each user's own Slack permissions (matches the no-shared-identity rule in
  `../v0.4/06-access-control.md`); the `xoxb`/`xoxp` / `authed_user` token details are
  handled inside the MCP server, not here. Slack does **not** support DCR, so it uses the
  pre-configured client path (`_acquire_configured`) with `LIK_UI_SLACK_CLIENT_ID` /
  `LIK_UI_SLACK_CLIENT_SECRET` — the same shape as GitHub. (Note: this DCR gap is a hard
  wall for DCR-only clients like Claude Code / Codex CLI; lik-ui works because it already
  has the pre-configured branch.) Constraints when building it: (1) the Slack app must be
  **directory-published or internal** — unlisted apps are rejected by the MCP server; (2)
  the server exposes a **curated tool subset** (search, messages, canvases, users) — no
  file ops, reminders, workflow triggers, or admin methods. Register the app **org-owned
  from the start**.
