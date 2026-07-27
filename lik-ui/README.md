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

## Add an agent

An agent shown in lik-ui's picker is two things: a **definition** on the Claude Managed Agents
platform (deployed from GitHub, the source of truth) and an entry in lik-ui's **roster**. Adding one
is a PR plus two manual deploy Actions — no ids are hand-copied anywhere; everything resolves by name.

1. **Write the agent spec.** Add `claude_platform/agents/<stem>.yaml` — the platform's raw agent YAML
   (see `cross-source-reference.yaml` for a template): `name`, `model`, `description`, `system`,
   the `mcp_servers` it needs, a matching `mcp_toolset` under `tools` for each server, and `skills`.
   The `name` is the platform identity the deploy and the app match on. `skills` reference skills **by
   name** (the dir under `claude_platform/skills/`), never by id — use `skills: []` if the behavior
   lives inline in `system`. If the agent needs a new skill, add it under
   `claude_platform/skills/<name>/SKILL.md`; `deploy_agents.py` publishes exactly the skills an agent
   references, so there's no separate skills step for it.

2. **Add it to the roster.** Add a `[[agents]]` block naming the agent in
   [`src/lik_ui/agents.toml`](src/lik_ui/agents.toml). Omit `environment` to use `default_environment`
   (`lik-ui-env`), or set it to override. The app reads this file **once at startup** — a new agent
   appears only after a redeploy (step 5), there is no runtime reload.

3. **Expose it in the deploy workflow's picker.** Add the spec's filename stem to the `agent` choice
   `options` in [`.github/workflows/deploy-agents.yml`](../.github/workflows/deploy-agents.yml) (and,
   for a new skill you want dispatchable on its own, to `deploy-skills.yml`). `all` deploys everything
   regardless, so this only affects whether you can dispatch the one agent by name.

4. **Open a PR and merge.** GitHub is the source of truth; nothing is live until the specs land on the
   default branch and you run the deploy.

5. **Deploy, then redeploy the app.**
   - Run the **Deploy agents to Claude platform** Action (Actions → manual dispatch, like
     `deploy-images.yml`), choosing your agent or `all`. It syncs all environments, then creates the
     agent (or updates it in place, matched by name) and publishes+attaches the skills it references
     at `latest`. `deploy_agents.py --dry-run` prints the plan without publishing. Running against the
     real API needs `ANTHROPIC_API_KEY` (a standard org key scoped to the LIK workspace) — CI reads it
     from the `prod` environment secret.
   - Run the **Build and deploy images** Action for `lik-ui` so the app restarts and re-reads
     `agents.toml`; the new agent then shows in the picker.

To change an existing agent's definition (prompt, model, servers), edit its spec and re-run the
Deploy agents Action — it updates in place. Editing only a skill it references? The **Deploy skills to
Claude platform** Action publishes a new version, and agents pinned to `latest` pick it up on their
next session — no app redeploy needed.

## TODO: cache agent `describe` results

The home (agent picker) and connections pages call `AgentsClient.describe(agent_id)` on
every load — one Anthropic SDK `retrieve` per configured agent. With a single agent that's
one call, but the agent definition (system prompt, model, declared servers) changes rarely.
If the agent list grows, cache these results (e.g. a short TTL) rather than fetching per
request.

## DONE: show full skill instructions (SKILL.md)

Expanding a skill's "Details" on the connections page shows its full `SKILL.md` alongside the
name and description. The instructions come from **GitHub**, the single source of truth (skills
are deployed *to* Managed Agents from `claude_platform/skills/<name>/` — see
[`scripts/README.md`](../scripts/README.md)), not from Managed Agents:
`beta.skills.versions.download` is a dead end (it 403s with "Downloading skill content is not
supported with this credential type"). `skill_docs.py` fetches the raw
`claude_platform/skills/<name>/SKILL.md` from the **public** repo with a plain unauthenticated GET —
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

The chat streams the agent's reply to the browser live. On the current Lightsail deployment,
the connection is dropped if it stays quiet for about 60 seconds — and the agent often goes
quiet that long while it's thinking between steps. When that happened, the reply was still
finished and saved on the server, but it never showed up in the open chat.

**Largely fixed** as of PR #33 (navapbc/leverage-inst-knowl):

- A small "still here" signal is sent every 15 seconds during quiet stretches, so the
  connection isn't dropped in the first place.
- If it *is* dropped, the page automatically reconnects and picks up the reply — the user
  doesn't lose it.

**Workaround if a reply ever goes missing:** wait until the agent looks idle, then refresh
the page. The reply is saved on the server, so reloading brings it back. (This is the
fallback the automatic reconnect now handles for you.)

**Remaining risk:** we've confirmed the ~60s *idle* limit, but not whether Lightsail also
caps the *total* length of a single connection regardless of activity. If it does, the
heartbeat won't help (the auto-reconnect still recovers the reply, and refreshing won't if
the server never got to finish), and the real fix is to move off the Lightsail ingress to
ECS/EC2 behind an ALB, where the timeout is configurable. Also avoid fronting the app with a
Lightsail distribution/CDN — its 30s limit breaks live streaming. See `../domain-name.md`
(Caveat: real-time streaming and timeouts).

## TODO: auto-archive or delete stale chat sessions

Today a session lives forever: `SessionsClient.create_session` mints a Managed Agents
session and `db.py` keeps a local row (`session_id`, `user_id`, `agent_id`, `title`,
`shared`, `created_at`), and nothing prunes either side until a user deletes a chat by hand.
The sessions list grows without bound. Consider a policy that automatically **archives** or
**deletes** a session after some period of inactivity (or age).

Archive vs. delete on the platform — both are real, distinct operations on `beta.sessions`
(we currently only call `delete_session`):

- **Archive** (`beta.sessions.archive`) — blocks new events but **keeps the full transcript**;
  the session can be excluded from the list view (the list endpoint takes an
  `include_archived` filter). Reversibility (unarchive/reopen) is **not documented** — verify
  before relying on it. Requires the session to be `idle`.
- **Delete** (`beta.sessions.delete`) — permanently removes the record, its events, and the
  associated sandbox. Not recoverable. Also requires `idle`.

Reasons to prefer archiving over deleting:

- **Retention / auditability.** Keeps the conversation history for later replay or review
  instead of destroying it.
- **List hygiene.** Hides old chats from the picker without losing them, so the list stays
  usable as sessions accumulate.
- **Reversible-ish.** Delete is final; archive at least preserves the data even if reopening
  isn't guaranteed.

What is *not* a strong reason here: **runtime cost.** Managed Agents bill session *runtime*
(per session-hour while `running`); idle sessions are free and there's no documented per-session
storage charge. A chat session sits idle between turns, so archiving it saves ~nothing on
runtime — this is about tidiness and retention, not spend. There's also no documented platform
TTL/auto-expiry, so any expiry is ours to implement.

Design notes if we build this:

- A time-based policy needs a notion of "last activity." The `sessions` row only has
  `created_at` (age), not a last-activity timestamp — key off `created_at`, or add an
  `updated_at`/`last_active_at` column (non-destructive `ALTER`, per the DB-schema rules in
  `CLAUDE.md`) touched on each turn.
- Decide archive-then-delete (grace period) vs. straight delete, and whether it's a background
  sweep or lazy-on-list. Keep the local row and the platform session in sync — the code already
  handles `SessionNotFound` for platform sessions that vanish out-of-band.

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
  `../v0.5/06-access-control.md`); the `xoxb`/`xoxp` / `authed_user` token details are
  handled inside the MCP server, not here. Slack does **not** support DCR, so it uses the
  pre-configured client path (`_acquire_configured`) with `LIK_UI_SLACK_CLIENT_ID` /
  `LIK_UI_SLACK_CLIENT_SECRET` — the same shape as GitHub. (Note: this DCR gap is a hard
  wall for DCR-only clients like Claude Code / Codex CLI; lik-ui works because it already
  has the pre-configured branch.) Constraints when building it: (1) the Slack app must be
  **directory-published or internal** — unlisted apps are rejected by the MCP server; (2)
  the server exposes a **curated tool subset** (search, messages, canvases, users) — no
  file ops, reminders, workflow triggers, or admin methods. Register the app **org-owned
  from the start**.
