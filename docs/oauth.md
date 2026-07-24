# OAuth Clients & Data-Source Connections

Everything OAuth for the `lik-ui` data-source connections: how connections work, how to register the
OAuth client each connection needs (under Nava org ownership), the provider-specific challenges
(Atlassian forced re-auth, Google Drive preview gating, GitHub org transfer), and how to diagnose a
failing connection.

Deploy mechanics — seeding SSM, `terraform apply`, DB init, image builds — live in
[`deploy-runbook.md`](deploy-runbook.md). This doc owns the OAuth-specific setup and troubleshooting the
runbook points at.

**Conventions** (same as the runbook): AWS CLI runs with `AWS_PROFILE=lik` via `mise exec --`
(`aws`/`gcloud`/`terraform`/`python`/`uv` are not on PATH otherwise); region is **us-east-1**.

---

## How connections work (background)

A "connection" is a per-user OAuth grant to one MCP server (Confluence/Atlassian, Google Drive, Slack,
GitHub, lik-mcp). The moving parts:

- **The agent declares which MCP servers exist.** lik-ui reads the selected agent's `mcp_servers` list
  via the Claude SDK and, for each declared URL, needs an OAuth client to connect with. If the agent
  declares a URL lik-ui has no client for, the connect fails with *"<url> has no dynamic client
  registration and no configured client."* (See "Agent MCP-server URL dependency" in the runbook — the
  agent definition, not lik-ui, is the source of truth for these URLs.)
- **Two ways lik-ui gets a client** (`lik-ui/src/lik_ui/oauth_connector.py`):
  - **Dynamic Client Registration (DCR)** — the authorization server hands out a client on demand.
    Atlassian uses this. lik-ui registers a **fresh client on every connect** (`_acquire_via_dcr`)
    rather than caching one, because some servers silently purge DCR clients (see the Atlassian
    challenge below).
  - **Pre-configured client** — a client id/secret you register by hand in the provider's console and
    store in SSM. Google, GitHub, and Slack take this path (`_acquire_configured`, keyed by
    `LIK_UI_*_RESOURCE_URL` in `lik-ui/src/lik_ui/sources.py`).
- **Credentials live in the platform vault, not this repo.** After the PKCE authorization-code flow,
  lik-ui deposits the credential in the user's vault on the Anthropic Managed Agents platform
  (`lik-ui/src/lik_ui/vault.py`). A reconnect updates the existing credential **in place**. The
  Managed Agent (running headless server-side) reads the vault to authenticate to each MCP server.
- **Refresh vs. reconnect.** If the token response includes a refresh token, lik-ui stores a `refresh`
  block so the platform can refresh silently. If it does **not** (`_refresh_block` returns `None`), the
  platform cannot refresh and the user must reconnect once the access token expires. Whether a provider
  issues a refresh token is provider- and scope-dependent (e.g. Google needs `access_type=offline`).

---

## Registering OAuth clients under Nava org ownership

Create **new** clients owned by the Nava org (do not transfer personal ones except where noted). Use the
service URLs from the runbook's deploy step 1 (`lik_ui_service_url`, `lik_mcp_resource_server_url`).

| Client | Provider | Redirect / callback URI |
|--------|----------|-------------------------|
| App login (identity) | Google Cloud (Nava org project) | `<lik_ui_service_url>/auth/callback` |
| lik-mcp data connection | Google Cloud (Nava org project) | `<lik_ui_service_url>/connections/callback` |
| Google Drive connection | Google Cloud (Nava org project) | `<lik_ui_service_url>/connections/callback` |
| GitHub connection | GitHub OAuth App (Nava org) | `<lik_ui_service_url>/connections/callback` |

Equality constraints to honor (they affect the SSM values in the runbook's deploy step 3):
- The lik-mcp connection's **client id** must equal lik-mcp's `LIK_OAUTH_CLIENT_ID` (same Google
  client). Terraform reuses the single SSM param for both, so you only store it once.
- lik-ui's lik-mcp **resource URL** must equal `lik_mcp_resource_server_url`. Terraform derives this
  automatically — no separate value to store.

Record each client id + secret; you'll set them in SSM per the runbook's deploy step 3.

### Google clients — create in a Nava-org-owned GCP project

The goal is org ownership: the project (and therefore its OAuth clients) must live under the Nava Google
Cloud **Organization**, not a personal Google account. Personal clients are owned by whoever created them
and vanish/leak when that person leaves — the failure mode this step exists to prevent.

1. **Confirm the org, not a personal project.** In the [Google Cloud console](https://console.cloud.google.com/)
   project picker, the top of the org selector must show the Nava organization (e.g. `navapbc.com`), not
   "No organization". If you can't see the Nava org, you lack org access — ask a Google Workspace / GCP
   admin to grant `resourcemanager.projectCreator` on the org (or to create the project for you). Do
   **not** fall back to a personal project.
2. **Create a dedicated project** under the org, e.g. `lik-prod`. Verify ownership afterward:
   ```
   AWS_PROFILE=lik mise exec -- gcloud projects describe lik-prod \
     --format='value(parent.type,parent.id)'
   # must print:  organization  <nava-org-id>     (NOT "no-org" / a folder you don't recognize)
   ```
   (or in console: IAM & Admin → Settings shows the parent organization).
3. **Configure the OAuth consent screen** as **Internal** (User Type = Internal). Internal restricts
   sign-in to the Nava Workspace domain and is only available on org-owned projects — a second guarantee
   you're not on a personal project (personal projects can only pick External).
4. **Create the OAuth 2.0 Client IDs** (APIs & Services → Credentials → Create credentials → OAuth client
   ID → Web application). Create these three, each keyed to a redirect URI from the table above:
   - **App login** → redirect `<lik_ui_service_url>/auth/callback`
   - **lik-mcp connection** → redirect `<lik_ui_service_url>/connections/callback`
   - **Google Drive connection** → redirect `<lik_ui_service_url>/connections/callback`
5. **Enable the Google APIs the Drive connection needs** (APIs & Services → Library, on the `lik-prod`
   project). Creating the OAuth client is not enough — the required APIs must be enabled on the *same
   project that owns the OAuth client*, or a tool call returns
   `403 ... has not been used in project <n> before or it is disabled` *after* a successful connect (auth
   works, `initialize` works, the first tool call fails). Enable both:
   - **Drive MCP API** (`drivemcp.googleapis.com`) — the Google-hosted Drive MCP server the agent
     actually talks to. This is the one that is easy to miss: it is a distinct API from the Drive API,
     and its absence is what makes `list_recent_files` fail with a bare "access forbidden" once the
     connection is otherwise fully working.
     ```
     AWS_PROFILE=lik mise exec -- gcloud services enable drivemcp.googleapis.com --project lik-prod
     ```
   - **Google Drive API** (`drive.googleapis.com`) — the underlying files API the MCP server calls
     downstream on the user's behalf.

   The scope requested for the Drive connection is declared in code, not in the console's Data Access tab
   — see `lik-ui/src/lik_ui/sources.py` (the Google Drive source entry): `openid`, `email`,
   `https://www.googleapis.com/auth/drive.readonly`. `drive.readonly` is sufficient for reading
   files/metadata/content (it is one of the scopes the Drive MCP server advertises as supported) and
   grants no write access. After changing scopes, existing connections must **reconnect** — a new scope
   needs fresh consent.
6. **Enroll the project in the Google Workspace Developer Preview Program** — see the "Google Drive"
   challenge below; this is a hard gate on Drive tool execution, separate from enabling the API.
7. **Add org co-owners** so the clients aren't bound to one person: IAM → grant another Nava admin
   `Owner`/`Editor` on the `lik-prod` project. Ownership now survives any one departure.

Record each client id + secret. (The lik-mcp connection's client id is also lik-mcp's
`LIK_OAUTH_CLIENT_ID` — store it once; see the equality constraint above.)

### GitHub — create an OAuth App owned by the Nava org

1. Go to the **organization's** developer settings, not your user's:
   `https://github.com/organizations/navapbc/settings/applications` (requires org-owner or a granted
   app-manager role). If you only see `https://github.com/settings/developers`, that's your personal
   account — switch to the org URL.
2. **New OAuth App**: Authorization callback URL = `<lik_ui_service_url>/connections/callback`. Homepage
   URL = `<lik_ui_service_url>`.
3. Generate a client secret. Record the client id + secret for the runbook's deploy step 3.
4. Confirm ownership: the app's settings page header shows it's owned by `navapbc`, and other org owners
   can administer it.

See the "GitHub — org transfer escape hatch" challenge below if you lack org-level GitHub access.

DONE: Transfer ownership at https://github.com/settings/applications/3731288
7/23: Nava IT added 'lik-ui-prod' to the 'navapbc' GitHub org's OAuth app -- https://github.com/settings/applications/

---

## Provider-specific challenges

### Atlassian — periodic forced re-authentication (DCR client purge)

**Symptom.** A chat session shows, at the very start of the turn:
`MCP server 'atlassian' initialize failed: credential has been invalidated — re-authentication is
required`. The agent still answers using the other sources; only Atlassian is skipped. The UI surfaces a
"Reconnect / Fix connections" nudge.

**Cause.** Atlassian issues credentials against a **dynamically-registered client** (DCR) and silently
purges those client registrations after some days — despite advertising no expiry. Once the underlying
client is gone, both the access token **and** its refresh token are dead: Atlassian reports the
credential as invalidated, and only a full re-authentication (fresh DCR registration + consent) fixes it.
A silent token refresh cannot save it, even though the stored credential carries a `refresh` block. This
is *not* the "no refresh token" failure mode — Atlassian does issue one; it's invalidated along with the
purged client.

lik-ui already mitigates the *predictable* half of this: it registers a fresh DCR client on every connect
(`oauth_connector.py` `_acquire_via_dcr`), so a stale cached client id never blocks a reconnect. But it
cannot prevent Atlassian from purging an already-issued credential mid-life. **Periodic forced re-auth of
Atlassian is inherent to their DCR behavior** until they honor durable client registrations. The only
real mitigations are on Atlassian's side; lik-ui's job is just to detect the failure and prompt reconnect
(which it does).

**Confirmed instance (2026-07-23).** Session `sesn_01DDw6T1WYK5W19evtqrXuW5` (created 14:04:27 UTC) opened
with two `session.error` / `mcp_authentication_failed_error` events for `atlassian`, both
`retry_status=exhausted`, firing *before* the user message. The user's Atlassian vault credential
(`vcrd_...`, originally created 2026-07-16) then showed `updated_at` 14:06:26 — ~2 minutes after the
failing session — i.e. the user hit "Reconnect" right after the error, which updates the credential in
place. The client id in the credential's refresh block dated to the 07-16 connect: Atlassian had purged
it in the intervening week.

**Diagnostic.** See "Diagnosing a failing connection" below — for this error you'll see the
`session.error` events at session start, and the vault credential's `updated_at` moving after the failure
indicates the user already reconnected.

### Google Drive — developer-preview gating

The Drive MCP server is a **developer-preview** service, and its *tool execution* is gated behind preview
enrollment separately from enabling the API (runbook Google step 5). Without enrollment you get a
misleading failure: OAuth succeeds, `initialize` and `tools/list` succeed, the token works against the
raw Drive API — but **every** Drive tool call returns `"The caller does not have permission"`. This is
not a scope, OAuth-client, or API-enable problem and nothing in lik-ui fixes it.

- Submit the [Developer Preview Program](https://developers.google.com/workspace/preview) form (signed in
  as a `navapbc.com` account with access to `lik-prod`). It asks for the **project number**
  (`954378910957` — shown on the project's Cloud console welcome page / "Project info" card, distinct from
  the project id `lik-prod`). Approval is typically quick.
- Once approved, the same token/scopes start working — no reconnect or redeploy needed. Expect a
  **propagation delay**: approval does not flip the gate instantly. It can take minutes to a few hours
  (Workspace changes are documented as taking up to ~24h) before tool calls stop returning "The caller
  does not have permission", so don't treat an immediate retry failure as proof enrollment didn't work —
  wait and retry before concluding. Verification is functional (a Drive tool call succeeding), as there
  is no console/`gcloud` field that reports preview-enrollment status.

> Diagnosis tip: the wrapped agent error ("authentication failed: access forbidden" / "caller does not
> have permission") hides the real cause. To see the ground truth, mint a token for the Drive OAuth
> client via a loopback redirect and call `drivemcp.googleapis.com` (`initialize` / `tools/list` /
> `tools/call`) plus the raw Drive API directly — if raw Drive works but every MCP tool 403s, it is
> preview enrollment, not your config.

### GitHub — org transfer escape hatch

Unlike Google, GitHub OAuth Apps *can* be transferred. If you lack org-level GitHub access, create the
app under your personal account now (`https://github.com/settings/developers`), get the deployment
working, then transfer it to `navapbc` before real users depend on it:

- In the app's settings, use **Transfer ownership** (Advanced section) and name `navapbc` as the
  destination. The **client id and secret are preserved** across the transfer, so the SSM values and
  running config keep working — no redeploy needed in the normal case.
- If a secret ever does get regenerated, just `put-parameter` the new `LIK_UI_GITHUB_CLIENT_SECRET` and
  redeploy.
- Treat the personal-ownership window as temporary: it is the exact state this section exists to exit.
  Don't let it become permanent.

This transfer escape hatch is **GitHub-only**. Google clients cannot be transferred between projects — if
you lack GCP org access, get an admin to create the org project or recreate the clients there later
(which changes the Google client id/secret and requires an SSM update).

> If a Slack (or other) connection is added, follow the same principle: create the app in the Nava Slack
> workspace / org account with multiple admins, never a personal account.

---

## Adding the Slack MCP connection

Connects any agent that declares a Slack data source connection to the **official
Slack MCP server** at `https://mcp.slack.com/mcp` (Streamable HTTP, GA Feb 2026). Slack issues per-user
OAuth tokens, so each user's Slack permissions are enforced by Slack — lik-ui stores no shared Slack
identity.

> **Slack is already wired in code and infra — only the ops steps below remain.** Slack does **not** offer
> dynamic client registration, so it takes the pre-configured-client path (`_acquire_configured`), the
> same shape as GitHub. What's left is external setup: create the Slack app (B), populate the
> `LIK_UI_SLACK_*` secrets (C), point the agent at the server (D), then redeploy + verify (E).

### A. Build ✅ done — Slack is a no-DCR source in code + infra

Wired mirroring the GitHub connection, across four files (no further code change needed):

- **`lik-ui/src/lik_ui/settings.py`** — `slack_client_id` / `slack_client_secret` / `slack_resource_url`
  fields.
- **`lik-ui/src/lik_ui/sources.py`** — the Slack tuple in `build_source_registry`'s `declared` list, with
  a read-focused user-token scope set (search, channel/group/im history, canvases, files, users, emoji).
  Write scopes (`chat:write`, `canvases:write`, `reactions:write`) are intentionally omitted; to enable
  them, add each here **and** to the Slack app in step B.
- **`infra/ssm.tf`** — the three `LIK_UI_SLACK_*` params in `ui_ssm_params`.
- **`infra/lik_ui.tf`** — the three matching `LIK_UI_SLACK_*` container `environment` lines.

### B. Create the Slack app — org-owned in the Nava Slack workspace

Follow the same ownership principle as GitHub: create it in the **Nava Slack workspace / org account with
multiple admins, never a personal account**. Refer to
https://slack.com/help/articles/52414744085139-Connect-Slackbot-to-other-apps-with-MCP

1. Create a Slack app in the Nava workspace and configure it as an **OAuth 2.0 client** for the Slack MCP
   server.
2. **The app must be directory-published or internal** — the Slack MCP server rejects unlisted apps. This
   is a hard gate: OAuth will fail at connect time otherwise.
3. Set the OAuth **redirect URI** to `<lik_ui_service_url>/connections/callback` (the same callback
   lik-ui uses for every data connection).
4. Record the app's **client id + secret** for step C.

The Slack MCP server exposes a **curated tool subset** (search, messages, canvases, users) — no file ops,
reminders, workflow triggers, or admin methods.

For reference, here is the Slack app's manifest:
```json
{
    "display_information": {
        "name": "lik-ui",
        "description": "Leveraging institutional knowledge",
        "background_color": "#474747",
        "long_description": "This app is created to use Slack's MCP server.\r\nGo to https://ui.lik.navapbc.com and test it out. Log in with your Nava account.\r\nCode at https://github.com/navapbc/leverage-inst-knowl"
    },
    "features": {
        "bot_user": {
            "display_name": "lik-ui",
            "always_online": false
        }
    },
    "oauth_config": {
        "redirect_urls": [
            "https://ui.lik.navapbc.com/connections/callback"
        ],
        "scopes": {
            "user": [
                "canvases:read",
                "canvases:write",
                "channels:history",
                "channels:read",
                "channels:write",
                "chat:write",
                "emoji:read",
                "files:read",
                "groups:history",
                "groups:read",
                "groups:write",
                "im:history",
                "im:write",
                "mpim:history",
                "mpim:read",
                "mpim:write",
                "reactions:read",
                "reactions:write",
                "search:read",
                "search:read.files",
                "search:read.im",
                "search:read.mpim",
                "search:read.private",
                "search:read.public",
                "search:read.users",
                "users:read",
                "users:read.email"
            ],
            "user_optional": [
                "canvases:write",
                "chat:write"
            ],
            "bot": [
                "mcp:connect"
            ]
        },
        "pkce_enabled": true
    },
    "settings": {
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "token_rotation_enabled": false,
        "is_mcp_enabled": true
    }
}
```

### C. Populate SSM secrets

Set the three `LIK_UI_SLACK_*` params — already in `infra/ssm-secrets.example` and the runbook's step-1
placeholder seed. Use `set-ssm-secrets.sh` with a single-secret file per the runbook's deploy step 3.
`RESOURCE_URL` is the fixed external URL, stored in SSM like the GitHub one:

```
/ik-arch/prod/lik-ui/LIK_UI_SLACK_CLIENT_ID=…
/ik-arch/prod/lik-ui/LIK_UI_SLACK_CLIENT_SECRET=…
/ik-arch/prod/lik-ui/LIK_UI_SLACK_RESOURCE_URL=https://mcp.slack.com/mcp
```

### D. Update the agent definition to declare the Slack server

The connection only appears once the agent declares it. On the **Claude Managed Agents platform**
(out-of-band, per "Agent MCP-server URL dependency" in the runbook), add a `mcp_servers` entry to
the agent with url `https://mcp.slack.com/mcp`. That URL must **exactly equal**
`LIK_UI_SLACK_RESOURCE_URL` (normalized — a trailing slash is tolerated, nothing else); a mismatch means
lik-ui has no client for the declared URL and the connect fails with *"…has no dynamic client
registration and no configured client."*

### E. Redeploy and verify

1. `./tf.sh apply` (runbook deploy step 6) so the `LIK_UI_SLACK_*` values land in
   the container from SSM. The Slack code is already in the image, so no rebuild is needed unless the
   currently deployed `lik-ui` image predates it (built before the Slack source entry merged) — in that
   case rebuild + push first (runbook deploy step 4).
2. Sign in and open `/connections`: a **Slack** row now appears (declared by the agent), marked
   not-connected.
3. Click connect → Slack OAuth 2.0 / PKCE → back to `/connections/callback`; lik-ui deposits the per-user
   credential in the vault and the row flips to connected.
4. In a chat session, confirm the agent can call a Slack tool (e.g. a message search). A
   `403`/access-forbidden on the first tool call after a clean connect usually means missing or wrong
   scopes in the `sources.py` entry (step A) — reconnect after fixing, since a new scope needs fresh
   consent.

---

## Diagnosing a failing connection

Chat transcripts and credentials are **not** stored in this repo — they live on the Anthropic Managed
Agents platform and are read back via the Python `anthropic` SDK. To investigate an MCP auth failure:

1. **Get the API key** from SSM (needs `AWS_PROFILE=lik`; run `aws login` first if the session expired):
   ```
   AWS_PROFILE=lik mise exec -- aws ssm get-parameter --name /ik-arch/prod/lik-ui/LIK_UI_ANTHROPIC_API_KEY \
     --with-decryption --region us-east-1 --query Parameter.Value --output text
   ```
2. **Query the session** (`sesn_...`) from `lik-ui/` with `uv run python`:
   - `client.beta.sessions.retrieve(sid)` → status, agent (with declared `mcp_servers`), `vault_ids`.
   - `client.beta.sessions.events.list(sid, order="asc")` → the event stream. MCP auth failures appear as
     `session.error` events with `type == "mcp_authentication_failed_error"`, a `mcp_server_name`, and a
     `retry_status` (`exhausted` means the platform gave up). They fire at session init, *before* the
     `user.message` event.
3. **Inspect the vault** to see credential health:
   - `client.beta.vaults.credentials.list(vault_id)` → each credential's `auth.mcp_server_url`,
     `auth.expires_at`, and whether it has a `refresh` block (`null` = platform can't refresh → user must
     reconnect on expiry). **Redact tokens before printing.**
   - A credential whose `updated_at` moved *after* a failing session usually means the user already
     reconnected (a reconnect updates the credential in place), so the state you see is the healthy
     post-fix one, not what failed.

Agent IDs (which change) come from the SSM param `LIK_UI_AGENTS_CONFIG`, not hardcoded here; the
Atlassian MCP url is the stable provider endpoint `https://mcp.atlassian.com/v1/mcp`.
