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
`db/init.sql` hook does not run — apply the schema (and any later non-destructive migrations,
e.g. the `auto_delete_at` column) by hand. The script reads the same `LIK_UI_DB_*` config the
app uses and applies `db/init.sql` via psycopg (no `psql` needed):

```
LIK_UI_DB_HOST=... LIK_UI_DB_PORT=... LIK_UI_DB_NAME=... LIK_UI_DB_USER=... \
  LIK_UI_DB_PASSWORD=... LIK_UI_DB_SSLMODE=require uv run python scripts/init_db.py
```

`db/init.sql` is idempotent (`CREATE TABLE IF NOT EXISTS` plus `ADD COLUMN IF NOT EXISTS`
migrations), so re-running it is safe — it only creates schema and applies non-destructive
`ALTER`s, never dropping or truncating. (`scripts/init_db.py` mirrors lik-mcp's
`scripts/init_db.py`.)

Alternatively, apply it with `psql` directly against `settings.conninfo`'s values:

```
psql "host=$LIK_UI_DB_HOST port=$LIK_UI_DB_PORT dbname=$LIK_UI_DB_NAME \
  user=$LIK_UI_DB_USER password=$LIK_UI_DB_PASSWORD sslmode=$LIK_UI_DB_SSLMODE" \
  -f db/init.sql
```

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

## Configuration

All config is `LIK_UI_`-prefixed; see `.env.example`. Outside `local`/`test`, the app
fails closed if app-login, vault, or agent config is missing. Secrets are never logged.

`LIK_UI_APP_BASE_URL` is the public HTTPS URL the app is reached at; **both OAuth callback
URLs are derived from it** (`{base}/auth/callback` for login, `{base}/connections/callback`
for data sources — see `src/lik_ui/__main__.py`). It must match the redirect URIs registered
with each OAuth provider. In the production Terraform deploy this value is not set by hand —
it is computed from the container service's URL (or a custom domain when configured); see
[`../infra/README.md`](../infra/README.md) "URL-derived env values and custom domains".

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
   (`lik-ui-env`), or set it to override. Optionally set `user_prompt` — a short, user-facing
   invitation ("here's what to ask me") shown as a block above the chat transcript. It lives here,
   not in the agent spec, because the Managed Agent spec (step 1) has no field for it. Write it
   concisely from the agent's `description` and `system` prompt, addressed to the user with a couple
   of example asks; omitting it simply renders no block. The app reads this file **once at startup** —
   a new agent appears only after a redeploy (step 5), there is no runtime reload.

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

## TODO items

### Workaround: per-user authorization and billing for Anthropic API access

lik-ui talks to the Managed Agents platform with a single shared Anthropic credential today, so
every user's traffic bills and authorizes as one principal. It would be a **nice-to-have** for
each user's calls to be authorized and billed as that user. Anthropic attributes usage to a
credential, not to an
application-level user identity we pass through, so true per-user attribution requires a distinct
Anthropic API key per user — and the platform does not make that clean:

**The only viable path is a per-user API key minted inside the `lik-ui` workspace.** An admin
creates one key per user in the workspace (see the DONE section below), and lik-ui maps each
app-user to their assigned key. Usage/cost reports can then break down per key, i.e. per user.
The heavy caveat is provisioning: **key creation is Console-only — the Admin API cannot mint keys**
("new API keys can only be created through the Claude Console"). So each key is a manual click,
and offboarding a user means manually deactivating their key. The Admin API *can* automate the
back half (list, rename, deactivate by `api_key_id`); only creation stays manual. Users do **not**
need their own Console seat — the admin mints the keys on their behalf.

Two hard limits remain even with per-user keys: **rate limits are per-workspace** (all users share
one pool, no per-user isolation) and there is **no per-key hard spend cap** on the standard API
(the spend-limits API is Claude-Enterprise-only). So this buys per-user *cost reporting*, not
per-user rate-limiting or spend enforcement.

Keep the single shared workspace
key and do per-user attribution in lik-ui's own DB, which we control and can fully automate.

### TODO: least-privilege credentials for the session-cleanup cron

The daily `prune-sessions` workflow currently connects to Postgres with the **DB master
(superuser) credential** (`DB_MASTER_PASSWORD`), and the single `github-actions-lik-ssm-read`
role that grants it is shared with `deploy-agents` / `deploy-skills` — so those deploy
workflows can now also read the DB master password even though they never touch the database.
Two least-privilege follow-ups (surfaced by code review of PR #45, both infrastructure-only):

- **Dedicated Postgres role for the cron.** Provision a role with only `SELECT, DELETE ON
  sessions` (plus `USAGE` on the schema), store its password at
  `$SSM_PREFIX/shared/PRUNE_DB_PASSWORD`, and point `prune-sessions.yml` at it instead of the
  master credential. Keeps the master password confined to AWS even if a runner or a CI
  dependency is compromised.
- **Split the SSM-read role.** Give the cron its own role that reads the Anthropic key **and**
  the prune DB password; narrow `github-actions-lik-ssm-read` back to the Anthropic key only so
  the deploy workflows can never read a DB credential.

Not blocking — the current setup works and the role is trust-scoped to the repo's `prod`
environment — but it widens the blast radius of a compromised workflow more than necessary.

### DONE: auto-delete stale chat sessions

Sessions no longer live forever. Each `sessions` row carries an `auto_delete_at` timestamp
(`timestamptz`, default `now() + 7 days`); existing rows get `now() + 7 days` (a fresh window
from migration time) via the non-destructive migration in `db/init.sql` — deliberately not
`created_at + 7 days`, which would put every session older than 7 days in the past and delete
them all on the first cleanup run with no warning. The owner can push the date out — or
pull it in — from a date picker in the chat's **Session settings** (`POST
/chat/{session_id}/auto-delete`, owner-scoped), but there is no way to disable it: a session
always has a date. The sessions list flags rows within 3 days of deletion ("Deletes in N days"
/ "Deletes today") and shows the plain date otherwise.

A daily GitHub Action (`.github/workflows/prune-sessions.yml`) runs
`scripts/prune_sessions.py`, which finds due sessions and deletes each **platform transcript
first, then the DB row** — the same ordering as the interactive delete — isolating per-session
failures so one bad delete never aborts the sweep or orphans a transcript. The job needs no
internet-facing endpoint and no long-lived shared secret: it authenticates via GitHub OIDC,
reads the shared Anthropic key + DB master password from SSM, and connects to the public
Lightsail Postgres directly.

We chose **delete**, not archive: the goal is data-minimization (old transcripts and their
credentials shouldn't linger on the platform), and the interactive delete path already destroys
both sides. The policy is age-based off `auto_delete_at` (seeded from creation), not a
last-activity timestamp, so no per-turn `updated_at` write was needed. See
`docs/plans/2026-07-28-001-feat-session-auto-delete-plan.md` for the full design and the manual
prod steps (schema ALTER + backfill, `tf.sh apply` for the widened SSM-read role, and the
`LIK_UI_DB_*` prod environment variables).

### DONE: cache agent `describe` results

The home (agent picker) and connections pages — plus the chat label and chat-resume paths —
call `AgentsClient.describe(agent_id)` on every load, one Anthropic SDK `retrieve` per
configured agent. The agent definition (system prompt, model, declared servers) changes only on
redeploy, so `CachingAgentsClient` (in `src/lik_ui/agents.py`) wraps the real client and memoizes
`describe` per agent for a short TTL, collapsing a burst of loads into at most one fetch per agent
per window. Only `describe` is cached; every other method delegates straight through. The window
is `LIK_UI_AGENT_DESCRIBE_TTL` (default 60s; `0` disables caching). A redeploy restarts the
process and empties the cache, so there is no manual bust.

### DONE: show full skill instructions (SKILL.md)

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

### DONE: dedicated Claude Workspace for LIK

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

### DONE: streaming timeouts on the deployed ingress (infrastructure)

The chat streams the agent's reply to the browser live. On the current Lightsail deployment,
the connection is dropped if it stays quiet for about 60 seconds — and the agent often goes
quiet that long while it's thinking between steps. When that happened, the reply was still
finished and saved on the server, but it never showed up in the open chat.

**Largely fixed** as of PR #33 (navapbc/leverage-inst-knowl):

- A small "still here" signal is sent every 15 seconds during quiet stretches, so the
  connection isn't dropped in the first place.
- If it *is* dropped, the page automatically reconnects and picks up the reply — the user
  doesn't lose it.

**Workaround if a reply ever goes missing:** refresh the page. The reply is saved on the
server, so reloading brings it back. (This is the fallback the automatic reconnect now
handles for you.) The pinned status strip at the bottom of the chat is the cue: while the
agent is busy it reads "⚙ Working…", "✍️ Responding…", "⏸ Waiting for your approval…", or
"⚙ Reconnecting…", and it disappears when the turn is done. Normally you can just wait for
it to clear. But if the underlying connection dies *silently* (a network partition the
browser never detects), the strip can stay frozen on "⚙ Working…"/"✍️ Responding…" and
never clear — so if it looks stuck with no new text arriving, refresh rather than keep
waiting. A refresh always reloads the true state from the server.

**No total-duration cap — measured.** Besides the ~60s *idle* limit, we checked whether the
Lightsail container service also caps the *total* length of a single connection regardless of
activity. It does not: a streaming connection emitting a keepalive every 15s stayed open,
uninterrupted, for the full **31 minutes** tested, with no server-side close (the test ended
on the client's own timeout). So with the 15s heartbeat, a connection lasts as long as the
agent needs — the idle cull is the only ingress timeout, and no total-cap fix is warranted.

Even if a longer cap existed beyond what we tested, it wouldn't lose a reply: a hard cap
closes cleanly, so `onerror` fires and the auto-reconnect re-attaches via `/resume` and keeps
streaming (the turn survives repeated culls by design) — the only symptom would be a periodic
"⚙ Reconnecting…" flicker. One standing constraint regardless: do **not** front the app with a
Lightsail distribution/CDN — its 30s limit breaks live streaming. See `../domain-name.md`
(Caveat: real-time streaming and timeouts).

### DONE: OAuth client registrations: ownership

**All client registrations are now under Nava org ownership with more than one owner.**
Background: OAuth *client* registrations (the client ID/secret in `.env`) identify **this
app**, not the end user — one registration serves all users, and each user's own token is
what lands in their vault. When a registration is personally owned it is a durability and
trust liability: the consent screen shows a personal app, quotas and security contacts
route to an individual, and every user's connection breaks if that person leaves or loses
access. The fix per source was to re-register (or transfer) each client under **Nava org
ownership**, with more than one owner — configuration, not code. Per-source status:

- **Atlassian (Confluence/Jira)** — No action. Atlassian supports Dynamic Client
  Registration, so lik-ui self-registers a client at runtime; there is no static client
  ID/secret to own. See `discover()` / `_acquire_via_dcr()` in `oauth_connector.py`.

- **GitHub** — Done: transferred to the Nava GitHub org, so org owners (plural) now control
  it. The client ID survived the transfer; if the secret was rotated, keep
  `LIK_UI_GITHUB_CLIENT_ID` / `LIK_UI_GITHUB_CLIENT_SECRET` in sync. (If Nava security later
  needs per-repo granularity or org-admin install approval, a GitHub *App* — a different
  primitive with a different token model — is the stricter option; only switch if required,
  as it is a larger change than a transfer.)

- **Slack** — Done: built and installed in the Nava Slack workspace, org-owned from the
  start. It uses the **official Slack MCP server** (hosted at `https://mcp.slack.com/mcp`,
  GA Feb 2026), which fits the existing connector like GitHub does — no Slack-specific code.
  It does per-user OAuth 2.0/PKCE and issues per-user tokens that
  enforce each user's own Slack permissions (matches the no-shared-identity rule in
  `../v0.5/06-access-control.md`); the `xoxb`/`xoxp` / `authed_user` token details are
  handled inside the MCP server, not here. Slack does **not** support DCR, so it uses the
  pre-configured client path (`_acquire_configured`) with `LIK_UI_SLACK_CLIENT_ID` /
  `LIK_UI_SLACK_CLIENT_SECRET` — the same shape as GitHub. (Note: this DCR gap is a hard
  wall for DCR-only clients like Claude Code / Codex CLI; lik-ui works because it already
  has the pre-configured branch.) Constraints when building it: (1) the Slack app must be
  **directory-published or internal** — unlisted apps are rejected by the MCP server; (2)
  the server exposes a **curated tool subset** (search, messages, canvases, users) — no
  file ops, reminders, workflow triggers, or admin methods. The app was registered
  **org-owned** and satisfies both constraints.

The three Google clients below (Google Drive, lik-mcp, App login) all live in the same GCP
project, **`lik-prod`**, under the Nava Google Cloud **organization**. A second project-level
**Owner** has been added to `lik-prod`, so all three survive the original registrant leaving
(three org Admins can also recover access). Consent screen *User Type* stays **Internal** so
consent is restricted to the Nava Workspace org.

- **Google Drive** — Done (see `lik-prod` above).
  Values: `LIK_UI_GDRIVEMCP_CLIENT_ID` / `LIK_UI_GDRIVEMCP_CLIENT_SECRET`.

- **lik-mcp** — Done (see `lik-prod` above). The client reuses lik-mcp's own
  `LIK_OAUTH_CLIENT_ID` (it is the audience lik-mcp validates).
  Values: `LIK_UI_LIKMCP_CLIENT_ID` / `LIK_UI_LIKMCP_CLIENT_SECRET`.

- **App login (Google OIDC, identity-only)** — Done (see `lik-prod` above). Not a data
  source, but shares the same GCP project/consent screen.
  Values: `LIK_UI_APP_OAUTH_CLIENT_ID` / `LIK_UI_APP_OAUTH_CLIENT_SECRET`.
