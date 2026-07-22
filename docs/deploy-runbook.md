# Production Deploy Runbook (AWS Lightsail, us-east-1)

This is the step-by-step procedure to deploy and rebuild the `lik-mcp` and `lik-ui`
services on AWS. Terraform (in `infra/`) owns all AWS resources; this runbook owns the
steps Terraform can't do declaratively: bootstrapping the state bucket, registering OAuth
clients, populating secrets, pushing images, and initializing the database schema.

**Conventions**
- All AWS CLI commands run with `AWS_PROFILE=lik` and via `mise exec --`, e.g.
  `AWS_PROFILE=lik mise exec -- aws ...`.
- Region is **us-east-1** for everything. The old `us-east-2` Lightsail DB is **not**
  touched by any step here.

> ⚠️ **Terraform cannot use the `lik` profile directly.** The profile authenticates via a
> `login_session` credential provider that the AWS CLI understands but Terraform's Go SDK
> does not (it falls back to IMDS and fails with "No valid credential sources found").
> Export short-lived credentials into the environment before every `terraform` command:
>
> ```bash
> J=$(AWS_PROFILE=lik mise exec -- aws configure export-credentials --format process)
> export AWS_ACCESS_KEY_ID=$(printf '%s' "$J" | python3 -c 'import sys,json;print(json.load(sys.stdin)["AccessKeyId"])')
> export AWS_SECRET_ACCESS_KEY=$(printf '%s' "$J" | python3 -c 'import sys,json;print(json.load(sys.stdin)["SecretAccessKey"])')
> export AWS_SESSION_TOKEN=$(printf '%s' "$J" | python3 -c 'import sys,json;print(json.load(sys.stdin)["SessionToken"])')
> mise exec -- terraform <cmd>
> ```
>
> Do **not** use `--format env` piped through `eval` — the session token can contain
> characters that break unquoted `eval`. Credentials are temporary and expire; re-export
> if a `terraform` command later fails on expired credentials.
>
> **Shortcut:** `infra/tf.sh` does this export for you and runs terraform — e.g.
> `./tf.sh plan`, `./tf.sh apply -var-file=prod.tfvars`, `./tf.sh output`. It mints fresh
> credentials each run, so expiry never bites. Use it in place of the manual export + bare
> `terraform` in the steps below.

> ⚠️ **The DB master password contains shell-special characters** (`()[]{}<>` …). Never put
> it on an interactive command line (the mise zsh hook parse-errors on `)`). Always read it
> into a variable from SSM and reference it quoted, or run the step from a `bash` script
> file — see "Initialize the database schema".

---

## Deployment status (2026-07-15)

Both services are **deployed and serving over HTTPS under real auth**. Live identifiers:

| Resource | Value |
|----------|-------|
| lik-mcp service URL | `https://lik-mcp-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/` |
| lik-mcp resource URL (`LIK_RESOURCE_SERVER_URL`) | `https://lik-mcp-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/mcp` |
| lik-ui service URL (`LIK_UI_APP_BASE_URL`) | `https://lik-ui-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/` |
| DB endpoint | `ls-775fd23f9d76047da44b78ee7307c91023cfc535.celyyosemrsx.us-east-1.rds.amazonaws.com:5432` |
| CI image-push role | `arn:aws:iam::293033346213:role/github-actions-lik-image-push` |
| Deployed images | `:lik-mcp-prod.app.2`, `:lik-ui-prod.app.1` |

**Progress:**

| Step | Status |
|------|--------|
| Bootstrap: DB + services + OIDC role | ✅ applied |
| 2. OAuth clients registered (Nava org) | ✅ done |
| 3. Real SSM secrets set (no placeholders remain) | ✅ done |
| 4. Images built + pushed | ✅ done (`app.2` / `app.1`) |
| 6. Container deployment applied | ✅ done — health checks pass (lik-ui `/healthz` = `{"status":"ok"}`, lik-mcp `/mcp` = 401 under auth) |
| 5. DB schema init | ✅ done — `likdb`: `catalog`, `confirmations` + `pg_trgm`; `likuidb`: `users`, `user_vaults`, `sessions` |
| 7. Verification | ✅ done — end-to-end Google login confirmed |

> ✅ **Deployment is COMPLETE and verified end-to-end.** A Nava Workspace account signed in
> successfully: `/auth/login` → Google → `/auth/callback` (303, user persisted to `likuidb`
> with no DB error) → authenticated `/`, `/sessions`, `/settings`, `/connections` all 200. The
> full OAuth → session → Postgres path works. (Note: the container booted at step 6 *before*
> schema init, so the logs show harmless `database "likuidb" does not exist` pool errors from
> 15:51–15:52; they stopped once step 5 created the DB — the pool self-healed, no restart
> needed. If you ever init schema after deploy again, expect the same transient boot errors.)

> ⚠️ **Do NOT `terraform destroy` a container service in normal operation.** Its public
> URL contains a hash that changes on recreate, which breaks every OAuth registration
> keyed to it. If you must recreate one, plan to re-register OAuth clients and re-apply.

---

## One-time: bootstrap the state bucket ✅ done (2026-07-15)

The S3 backend bucket must exist (with versioning) before `terraform init`. Created once
with the commands below; `terraform init` then succeeded against it.

```
AWS_PROFILE=lik mise exec -- aws s3api create-bucket \
  --bucket ik-arch-tfstate-293033346213 --region us-east-1
AWS_PROFILE=lik mise exec -- aws s3api put-bucket-versioning \
  --bucket ik-arch-tfstate-293033346213 \
  --versioning-configuration Status=Enabled
AWS_PROFILE=lik mise exec -- aws s3api put-public-access-block \
  --bucket ik-arch-tfstate-293033346213 \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

Then, from `infra/`:

```
cd infra
AWS_PROFILE=lik mise exec -- terraform init
```

---

## Deploy sequence (first time)

The order matters: services must exist to yield the URLs that OAuth clients are keyed to,
and secrets must be in SSM before the container deployments boot under real auth.

### 1. Create the database, container services, and CI role ✅ done (2026-07-15)

Bootstrap everything except the container deployments (those need image refs + secrets).
Export credentials first (see the Terraform credential note above), then:

```
cd infra
mise exec -- terraform apply \
  -target=random_password.db_master \
  -target=aws_lightsail_database.main \
  -target=aws_ssm_parameter.db_master_password \
  -target=aws_lightsail_container_service.lik_mcp \
  -target=aws_lightsail_container_service.lik_ui \
  -target=aws_iam_openid_connect_provider.github \
  -target=aws_iam_role.github_image_push \
  -target=aws_iam_role_policy.image_push
```

> **Two gotchas learned during the first run:**
> 1. **Seed SSM placeholders BEFORE this step (or before any `plan`/`import`).** The full
>    config's `ssm.tf` data sources are read on every operation and fail with
>    `ParameterNotFound` if the `/ik-arch/prod/lik-*/…` params don't exist. `-target` prunes
>    them for *apply*, but `import` does not. Seed placeholders (or real values) first:
>    ```
>    for n in lik-mcp/LIK_OAUTH_CLIENT_ID lik-ui/LIK_UI_SESSION_SECRET lik-ui/LIK_UI_APP_OAUTH_CLIENT_ID \
>      lik-ui/LIK_UI_APP_OAUTH_CLIENT_SECRET lik-ui/LIK_UI_LIKMCP_CLIENT_SECRET lik-ui/LIK_UI_GDRIVEMCP_CLIENT_ID \
>      lik-ui/LIK_UI_GDRIVEMCP_CLIENT_SECRET lik-ui/LIK_UI_GDRIVEMCP_RESOURCE_URL lik-ui/LIK_UI_GITHUB_CLIENT_ID \
>      lik-ui/LIK_UI_GITHUB_CLIENT_SECRET lik-ui/LIK_UI_GITHUB_RESOURCE_URL lik-ui/LIK_UI_SLACK_CLIENT_ID \
>      lik-ui/LIK_UI_SLACK_CLIENT_SECRET lik-ui/LIK_UI_SLACK_RESOURCE_URL lik-ui/LIK_UI_ANTHROPIC_API_KEY \
>      lik-ui/LIK_UI_AGENTS_CONFIG; do
>      AWS_PROFILE=lik mise exec -- aws ssm put-parameter --region us-east-1 --type SecureString \
>        --name "/ik-arch/prod/$n" --value PLACEHOLDER_REPLACE_ME; done
>    ```
> 2. **Run this apply in the background / with a long timeout.** DB creation takes 5–10 min.
>    If the apply process is killed mid-flight, resources get created in AWS but not recorded
>    in state (orphans), and you must `terraform force-unlock <id>` then `terraform import`
>    each orphan (`random_password.db_master` must be imported from a `bash` script file to
>    dodge the password-quoting gotcha). Prefer letting it run to completion.

Record the outputs:

```
mise exec -- terraform output
```

You'll use `lik_mcp_service_url`, `lik_mcp_resource_server_url`, `lik_ui_service_url`,
`lik_ui_oauth_callback_urls`, and `github_image_push_role_arn` — captured values are in the
Deployment status table above.

### 2. Register OAuth clients under Nava org ownership ✅ done

Create **new** clients (do not transfer personal ones). Use the URLs from step 1.

| Client | Provider | Redirect / callback URI |
|--------|----------|-------------------------|
| App login (identity) | Google Cloud (Nava org project) | `<lik_ui_service_url>/auth/callback` |
| lik-mcp data connection | Google Cloud (Nava org project) | `<lik_ui_service_url>/connections/callback` |
| Google Drive connection | Google Cloud (Nava org project) | `<lik_ui_service_url>/connections/callback` |
| GitHub connection | GitHub OAuth App (Nava org) | `<lik_ui_service_url>/connections/callback` |

Equality constraints to honor:
- The lik-mcp connection's **client id** must equal lik-mcp's `LIK_OAUTH_CLIENT_ID`
  (same Google client). Terraform reuses the single SSM param for both, so you only store
  it once.
- lik-ui's lik-mcp **resource URL** must equal `lik_mcp_resource_server_url`. Terraform
  derives this automatically — no separate value to store.

#### 2a. Google clients — create in a Nava-org-owned GCP project

The goal is org ownership: the project (and therefore its OAuth clients) must live under
the Nava Google Cloud **Organization**, not a personal Google account. Personal clients are
owned by whoever created them and vanish/leak when that person leaves — the failure mode
this step exists to prevent.

1. **Confirm the org, not a personal project.** In the [Google Cloud console](https://console.cloud.google.com/)
   project picker, the top of the org selector must show the Nava organization (e.g.
   `navapbc.com`), not "No organization". If you can't see the Nava org, you lack org access
   — ask a Google Workspace / GCP admin to grant `resourcemanager.projectCreator` on the org
   (or to create the project for you). Do **not** fall back to a personal project.
2. **Create a dedicated project** under the org, e.g. `lik-prod`. Verify ownership afterward:
   ```
   AWS_PROFILE=lik mise exec -- gcloud projects describe lik-prod \
     --format='value(parent.type,parent.id)'
   # must print:  organization  <nava-org-id>     (NOT "no-org" / a folder you don't recognize)
   ```
   (or in console: IAM & Admin → Settings shows the parent organization).
3. **Configure the OAuth consent screen** as **Internal** (User Type = Internal). Internal
   restricts sign-in to the Nava Workspace domain and is only available on org-owned
   projects — a second guarantee you're not on a personal project (personal projects can
   only pick External).
4. **Create the OAuth 2.0 Client IDs** (APIs & Services → Credentials → Create credentials →
   OAuth client ID → Web application). Create these three, each keyed to a redirect URI from
   the table above:
   - **App login** → redirect `<lik_ui_service_url>/auth/callback`
   - **lik-mcp connection** → redirect `<lik_ui_service_url>/connections/callback`
   - **Google Drive connection** → redirect `<lik_ui_service_url>/connections/callback`
5. **Enable the Google APIs the Drive connection needs** (APIs & Services → Library, on the
   `lik-prod` project). Creating the OAuth client is not enough — the required APIs must be
   enabled on the *same project that owns the OAuth client*, or a tool call returns
   `403 ... has not been used in project <n> before or it is disabled` *after* a successful
   connect (auth works, `initialize` works, the first tool call fails). Enable both:
   - **Drive MCP API** (`drivemcp.googleapis.com`) — the Google-hosted Drive MCP server the
     agent actually talks to. This is the one that is easy to miss: it is a distinct API from
     the Drive API, and its absence is what makes `list_recent_files` fail with a bare
     "access forbidden" once the connection is otherwise fully working.
     ```
     AWS_PROFILE=lik mise exec -- gcloud services enable drivemcp.googleapis.com --project lik-prod
     ```
   - **Google Drive API** (`drive.googleapis.com`) — the underlying files API the MCP server
     calls downstream on the user's behalf.

   The scope requested for the Drive connection is declared in code, not in the console's Data
   Access tab — see `lik-ui/src/lik_ui/sources.py` (the Google Drive source entry):
   `openid`, `email`, `https://www.googleapis.com/auth/drive.readonly`. `drive.readonly` is
   sufficient for reading files/metadata/content (it is one of the scopes the Drive MCP server
   advertises as supported) and grants no write access. After changing scopes, existing
   connections must **reconnect** — a new scope needs fresh consent.
6. **Enroll the project in the Google Workspace Developer Preview Program** — the Drive MCP
   server is a **developer-preview** service, and its *tool execution* is gated behind preview
   enrollment separately from enabling the API. Without enrollment you get the misleading
   failure below: OAuth succeeds, `initialize` and `tools/list` succeed, the token works
   against the raw Drive API — but **every** Drive tool call returns
   `"The caller does not have permission"`. This is not a scope, OAuth-client, or API-enable
   problem and nothing in lik-ui fixes it.
   - Submit the [Developer Preview Program](https://developers.google.com/workspace/preview)
     form (signed in as a `navapbc.com` account with access to `lik-prod`). It asks for the
     **project number** (`954378910957` — shown on the project's Cloud console welcome page /
     "Project info" card, distinct from the project id `lik-prod`). Approval is typically quick.
   - Once approved, the same token/scopes start working — no reconnect or redeploy needed.
     Expect a **propagation delay**: approval does not flip the gate instantly. It can take
     minutes to a few hours (Workspace changes are documented as taking up to ~24h) before
     tool calls stop returning "The caller does not have permission", so don't treat an
     immediate retry failure as proof enrollment didn't work — wait and retry before
     concluding. Verification is functional (a Drive tool call succeeding), as there is no
     console/`gcloud` field that reports preview-enrollment status.

   > Diagnosis tip: the wrapped agent error ("authentication failed: access forbidden" /
   > "caller does not have permission") hides the real cause. To see the ground truth, mint a
   > token for the Drive OAuth client via a loopback redirect and call `drivemcp.googleapis.com`
   > (`initialize` / `tools/list` / `tools/call`) plus the raw Drive API directly — if raw Drive
   > works but every MCP tool 403s, it is preview enrollment, not your config.
7. **Add org co-owners** so the clients aren't bound to one person: IAM → grant another Nava
   admin `Owner`/`Editor` on the `lik-prod` project. Ownership now survives any one departure.

Record each client id + secret for step 3. (The lik-mcp connection's client id is also
lik-mcp's `LIK_OAUTH_CLIENT_ID` — store it once; see the equality constraint above.)

#### 2b. GitHub — create an OAuth App owned by the Nava org

1. Go to the **organization's** developer settings, not your user's:
   `https://github.com/organizations/navapbc/settings/applications` (requires org-owner or a
   granted app-manager role). If you only see `https://github.com/settings/developers`,
   that's your personal account — switch to the org URL.
2. **New OAuth App**: Authorization callback URL = `<lik_ui_service_url>/connections/callback`.
   Homepage URL = `<lik_ui_service_url>`.
3. Generate a client secret. Record the client id + secret for step 3.
4. Confirm ownership: the app's settings page header shows it's owned by `navapbc`, and other
   org owners can administer it.

**If you lack org-level GitHub access:** unlike Google, GitHub OAuth Apps *can* be transferred.
Create the app under your personal account now (`https://github.com/settings/developers`),
get the deployment working, then transfer it to `navapbc` before real users depend on it:

- In the app's settings, use **Transfer ownership** (Advanced section) and name `navapbc` as
  the destination. The **client id and secret are preserved** across the transfer, so the
  SSM values and running config keep working — no redeploy needed in the normal case.
- If a secret ever does get regenerated, just `put-parameter` the new
  `LIK_UI_GITHUB_CLIENT_SECRET` and redeploy.
- Treat the personal-ownership window as temporary: it is the exact state this section
  exists to exit (see the origin doc's "before others depend on this" gate). Don't let it
  become permanent.

  This transfer escape hatch is **GitHub-only**. Google clients (2a) cannot be transferred
  between projects — if you lack GCP org access, get an admin to create the org project or
  recreate the clients there later (which changes the Google client id/secret and requires an
  SSM update).

> If a Slack (or other) connection is added later, follow the same principle: create the app
> in the Nava Slack workspace / org account with multiple admins, never a personal account.
> For Slack specifically, see "Adding the Slack MCP connection (later)" below for the full
> procedure.

Transfer ownership at https://github.com/settings/applications/3731288

### 3. Populate SSM secrets ✅ done (no placeholders remain)

Overwrite the placeholder SecureStrings with real values. Edit **one** file mapping each SSM
name to its value, then run a loop that injects each via a per-line temp file and `file://`.
This keeps secrets off the command line (out of shell history / `ps`) and avoids the
special-char quoting breakage (a `)` trips the mise zsh hook, same as the DB password) — while
only asking you to edit a single file.

**Which params must be real vs. can stay placeholder:** the app's prod fail-closed guard only
requires `LIK_UI_SESSION_SECRET`, `LIK_UI_APP_OAUTH_CLIENT_ID`, `LIK_UI_APP_OAUTH_CLIENT_SECRET`,
`LIK_UI_ANTHROPIC_API_KEY`, `LIK_UI_AGENTS_CONFIG`, plus lik-mcp's `LIK_OAUTH_CLIENT_ID`. The
per-connection groups (`LIK_UI_LIKMCP_*`, `LIK_UI_GDRIVEMCP_*`, `LIK_UI_GITHUB_*`) are only
needed for the connections you actually enable — leave the others as `PLACEHOLDER_REPLACE_ME`
(they must *exist* so Terraform's data sources resolve, but that connection simply won't work
until you set real values). Do **not** set `DB_MASTER_PASSWORD` under `$P/shared/` — Terraform
owns it.

**Step A — create your working copy from the template.** `infra/ssm-secrets.example` lists
every SSM parameter (with `…` placeholders and inline notes). Copy it to a private temp file,
expanding the `$P` path prefix as you go:

```bash
P=/ik-arch/prod
SF=$(mktemp) && chmod 600 "$SF"
P=$P envsubst '$P' < infra/ssm-secrets.example > "$SF"
echo "Edit this file: $SF"
```

(No `envsubst`? `sed "s#\$P#$P#g" infra/ssm-secrets.example > "$SF"` does the same.)

**Step B — edit `$SF`** in your editor: replace each `…` with the real value; delete or
`#`-comment the connection lines you're not setting yet (leave the boot-required ones —
`APP_OAUTH_*`, `ANTHROPIC_API_KEY`, `AGENTS_CONFIG`, `SESSION_SECRET`, `LIK_OAUTH_CLIENT_ID`).
Generate `LIK_UI_SESSION_SECRET` with `openssl rand -hex 32`.

**Step C — push, then shred.** Run `infra/set-ssm-secrets.sh` against the file. It writes each
value to a short-lived temp file and sends it with `file://` (no secret on any command line),
skipping blank, `#`-commented, and still-`…` lines:

```bash
infra/set-ssm-secrets.sh "$SF"
rm -f "$SF"                                                # shred the master file
```

`set-ssm-secrets.sh` also handles **single-secret updates** — e.g. correcting one client
secret without touching the rest:

```bash
printf '%s\n' '/ik-arch/prod/lik-ui/LIK_UI_LIKMCP_CLIENT_SECRET=GOCSPX-…' > /tmp/one.env
infra/set-ssm-secrets.sh /tmp/one.env && rm -f /tmp/one.env
# then redeploy so the container picks it up:  ./tf.sh apply -var-file=prod.tfvars
```

Verify nothing required is still a placeholder before deploying:

```bash
AWS_PROFILE=lik mise exec -- aws ssm get-parameters-by-path --path /ik-arch/prod \
  --recursive --with-decryption --region us-east-1 --output json \
  | grep -B1 PLACEHOLDER_REPLACE_ME | grep '"Name"'
```

Any `LIK_UI_APP_*`, `LIK_UI_ANTHROPIC_API_KEY`, `LIK_UI_AGENTS_CONFIG`, `LIK_UI_SESSION_SECRET`,
or `LIK_OAUTH_CLIENT_ID` still listed here will make the container fail its prod guard at boot.

### 4. Build and push images ✅ done (`:lik-mcp-prod.app.2`, `:lik-ui-prod.app.1`)

> **Prerequisite: the workflow must run from `main`.** The job runs in the `prod` GitHub
> Environment, so the OIDC token's `sub` is `repo:navapbc/leverage-inst-knowl:environment:prod`
> — which the IAM role trusts (see `infra/iam_github_oidc.tf`). The `prod` environment has a
> **deployment branch policy restricting it to `main`**, so a run from any other branch is
> rejected by GitHub before it can assume the role. Merge `.github/workflows/deploy-images.yml`
> to `main` before running. (To allow another branch, add it to the environment's branch
> policy — do not loosen the IAM trust.)

**4a. Repo variables — ✅ done (env-scoped to `prod`).** The two variables live in a GitHub
**Environment** named `prod` (not at repo level), so a future `dev` environment can hold its
own values. The workflow job declares `environment: prod`, which is required for env-scoped
variables to resolve. Already created:

| Variable | Value | Scope |
|----------|-------|-------|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::293033346213:role/github-actions-lik-image-push` | env `prod` |
| `AWS_REGION` | `us-east-1` | env `prod` |

To recreate or inspect:
```bash
gh api --method PUT repos/navapbc/leverage-inst-knowl/environments/prod   # create the env
gh variable set AWS_DEPLOY_ROLE_ARN --env prod --repo navapbc/leverage-inst-knowl \
  --body arn:aws:iam::293033346213:role/github-actions-lik-image-push
gh variable set AWS_REGION --env prod --repo navapbc/leverage-inst-knowl --body us-east-1
gh variable list --env prod --repo navapbc/leverage-inst-knowl
```

> **Environment ↔ OIDC coupling (important):** the job sets `environment: prod`, which does
> two things at once — (1) it scopes the `AWS_DEPLOY_ROLE_ARN` / `AWS_REGION` variables, and
> (2) it changes the OIDC token `sub` to `repo:…:environment:prod` (the branch `ref:` form is
> *not* present when a job uses an environment). The IAM trust matches on that environment
> `sub`, and the environment's branch policy restricts deploys to `main`. **These move
> together:** if you ever remove `environment: prod` from the job, the variables stop
> resolving *and* the OIDC sub reverts to the branch form — breaking role assumption until the
> trust is switched back. A future `dev` needs its own environment (+ role/branch-policy) and
> a parallel Terraform stack (separate DB/services/SSM prefix/state), which is out of the
> current single-env scope.

**4b. Run the workflow** (from `main`):

- **GitHub UI:** repo → **Actions → "Build and push container images" → Run workflow** →
  branch `main`, input `both` → **Run workflow**.
- **Or via `gh` CLI:**
  ```bash
  gh workflow run deploy-images.yml --repo navapbc/leverage-inst-knowl --ref main -f service=both
  gh run watch --repo navapbc/leverage-inst-knowl   # follow to completion
  ```

**4c. Copy the two image refs** the workflow prints (format `:lik-mcp-prod.app.N` /
`:lik-ui-prod.app.N`). They're written to the run summary:

- **GitHub UI:** open the run → the job **Summary** shows each `### <service> pushed` block.
- **Or via `gh` CLI:** `gh run view --repo navapbc/leverage-inst-knowl <run-id>` (or add
  `--log` and grep for `Refer to this image as`).

### 5. Initialize the database schema ✅ done

The DB is empty. lik-ui also needs its own database created on the shared instance. Run
these once as the **master user** (needed for lik-mcp's `pg_trgm` extension + roles).

> **Requires `psql`** (libpq) on your machine — not managed by mise. If missing:
> `brew install libpq && brew link --force libpq` (macOS). The lik-mcp step uses the repo's
> own Python script (psycopg), so it needs no psql.

The DB host is fixed (also in the Deployment status table); the password comes from SSM:

```bash
DB_HOST=ls-775fd23f9d76047da44b78ee7307c91023cfc535.celyyosemrsx.us-east-1.rds.amazonaws.com
DB_PW=$(AWS_PROFILE=lik mise exec -- aws ssm get-parameter --region us-east-1 --with-decryption \
  --name /ik-arch/prod/shared/DB_MASTER_PASSWORD --query Parameter.Value --output text)

# 1. Create lik-ui's database on the shared instance (connect to the master DB 'likdb' first)
psql "host=$DB_HOST port=5432 dbname=likdb user=lik password=$DB_PW sslmode=require" \
  -c "CREATE DATABASE likuidb;"

# 2. lik-mcp schema — its script applies lik-mcp/db/init.sql via psycopg, as master user
cd lik-mcp
LIK_DB_HOST=$DB_HOST LIK_DB_NAME=likdb LIK_DB_USER=lik LIK_DB_PASSWORD="$DB_PW" LIK_DB_SSLMODE=require \
  mise exec -- uv run python scripts/init_db.py
cd ..

# 3. lik-ui schema
psql "host=$DB_HOST port=5432 dbname=likuidb user=lik password=$DB_PW sslmode=require" \
  -f lik-ui/db/init.sql
```

> `DB_PW` holds the special-char password. It's fine inside `"$DB_PW"` and the psql conninfo
> string above (quoted), but never echo it onto an interactive command line bare (the mise
> zsh hook parse-errors on `)`). If a command trips on it, run these from a `bash` script file.

All init scripts are idempotent (`IF NOT EXISTS`), so re-running is safe. Verify afterward:
`psql "...dbname=likdb..." -c '\dt'` shows `catalog`, `confirmations`; `...dbname=likuidb...`
shows `users`, `user_vaults`, `sessions`.

### 6. Deploy the container versions ✅ done (containers healthy; see step 5 caveat)

Export Terraform credentials first (see the credential note near the top). Then apply with
the image refs from step 4c — this creates the two `deployment_version` resources (the
count-guard flips on once the image vars are non-empty), and the containers boot under real
`prod` auth using the SSM values:

```bash
cd infra
# (export AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN per the credential note)

mise exec -- terraform apply \
  -var 'lik_mcp_image=:lik-mcp-prod.app.N' \
  -var 'lik_ui_image=:lik-ui-prod.app.N'
```

Recommended: put the refs (and any custom-domain URLs) in a gitignored `infra/prod.tfvars`
so redeploys don't retype them. Copy the committed template and edit it (`*.tfvars` is
gitignored; `*.tfvars.example` is committed as the reference):

```bash
cp prod.tfvars.example prod.tfvars   # then edit: image refs, optional custom domains
mise exec -- terraform apply -var-file=prod.tfvars
```

`prod.tfvars.example` documents every non-default variable a real `prod.tfvars` may set —
image refs plus the optional `ui_custom_domain_url` / `mcp_custom_domain_url` (see
"Custom-domain migration" for when to populate the domains).

The deployment takes a few minutes per service. Run it in the background or leave it to
finish — a killed apply orphans state (see the step-1 gotcha).

### 7. Verify ✅ done — end-to-end login confirmed

```bash
# lik-ui health (unauthenticated) -> {"status":"ok"}
curl -fsS https://lik-ui-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/healthz
# lik-mcp -> 401 is EXPECTED and healthy (auth is on; there's no unauth route)
curl -s -o /dev/null -w '%{http_code}\n' \
  https://lik-mcp-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/mcp
```

Then open `https://lik-ui-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/` in a browser
and complete Google login and one data-source connect end-to-end. If the container is
unhealthy, check logs (see "Viewing logs") — a boot failure is almost always a missing/placeholder
SSM value (step 3) or an OAuth redirect-URI mismatch (step 2).

---

## Routine redeploy (new image)

1. Run the **Build and push container images** workflow → copy the new refs.
2. `terraform apply -var lik_mcp_image=… -var lik_ui_image=…`.

No secret or DB steps needed unless config changed.

## Viewing logs

```
AWS_PROFILE=lik mise exec -- aws lightsail get-container-log \
  --region us-east-1 --service-name lik-ui-prod --container-name lik-ui
```

---

## Agent MCP-server URL dependency (external — not in this repo)

> ⚠️ The lik-mcp (and Google Drive / GitHub) **connection URLs are declared by the *agent
> definition***, not by lik-ui or Terraform. lik-ui reads the selected agent's `mcp_servers`
> via the Claude Agent SDK and matches each declared URL against its pre-configured OAuth
> clients (keyed by `LIK_UI_*_RESOURCE_URL` — see `lik-ui/src/lik_ui/sources.py`). If the
> agent declares a URL that lik-ui has no client for, the connect fails with
> *"<url> has no dynamic client registration and no configured client."*

**Why this matters for this deploy:** the agent
`agent_016uQNVgNEVtcAmvwKtskh8d` (from `LIK_UI_AGENTS_CONFIG`) was authored pointing at the
old `https://leverage-inst-knowl.onrender.com/mcp` deployment. After migrating to Lightsail,
its declared lik-mcp server URL must be updated to the Lightsail URL:

```
https://lik-mcp-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/mcp
```

- This is changed in the **agent definition on the Claude Managed Agents platform** (via the
  Agent SDK / console) — it is out-of-band agent authoring, not a lik-ui/Terraform change.
- The Managed Agent runs headless server-side and connects to the URL *it* declares, so you
  **cannot** redirect it from lik-ui: pointing `LIK_UI_LIKMCP_RESOURCE_URL` at the old URL
  would only mint a credential for the old server, not move the agent.
- lik-ui's `LIK_UI_LIKMCP_RESOURCE_URL` must **equal** whatever URL the agent declares (it's
  already the Lightsail URL, Terraform-derived), so once the agent is updated, no lik-ui
  change is needed.
- **This recurs on any URL change** (including the custom-domain migration below): whenever
  the lik-mcp public URL changes, the agent's declared `mcp_servers` entry must be updated to
  match. A custom domain (stable across infra changes) removes this recurring coupling.

---

## Adding the Slack MCP connection (later)

Connects agent `agent_016uQNVgNEVtcAmvwKtskh8d` (and any other agent that declares it) to
the **official Slack MCP server** at `https://mcp.slack.com/mcp` (Streamable HTTP, GA Feb
2026). Slack issues per-user OAuth tokens, so each user's Slack permissions are enforced by
Slack — lik-ui stores no shared Slack identity.

> **Slack is already wired in code and infra — only the ops steps below remain.** Slack does
> **not** offer dynamic client registration, so it takes the pre-configured-client path
> (`_acquire_configured`), the same shape as GitHub. What's left is external setup: create the
> Slack app (B), populate the `LIK_UI_SLACK_*` secrets (C), point the agent at the server (D),
> then redeploy + verify (E).

### A. Build ✅ done — Slack is a no-DCR source in code + infra

Wired mirroring the GitHub connection, across four files (no further code change needed):

- **`lik-ui/src/lik_ui/settings.py`** — `slack_client_id` / `slack_client_secret` /
  `slack_resource_url` fields.
- **`lik-ui/src/lik_ui/sources.py`** — the Slack tuple in `build_source_registry`'s `declared`
  list, with a read-focused user-token scope set (search, channel/group/im history, canvases,
  files, users, emoji). Write scopes (`chat:write`, `canvases:write`, `reactions:write`) are
  intentionally omitted; to enable them, add each here **and** to the Slack app in step B.
- **`infra/ssm.tf`** — the three `LIK_UI_SLACK_*` params in `ui_ssm_params`.
- **`infra/lik_ui.tf`** — the three matching `LIK_UI_SLACK_*` container `environment` lines.

### B. Create the Slack app — org-owned in the Nava Slack workspace

Follow the same ownership principle as GitHub (step 2b): create it in the **Nava Slack
workspace / org account with multiple admins, never a personal account**.
Refer to https://slack.com/help/articles/52414744085139-Connect-Slackbot-to-other-apps-with-MCP

1. Create a Slack app in the Nava workspace and configure it as an **OAuth 2.0 client** for
   the Slack MCP server.
2. **The app must be directory-published or internal** — the Slack MCP server rejects
   unlisted apps. This is a hard gate: OAuth will fail at connect time otherwise.
3. Set the OAuth **redirect URI** to `<lik_ui_service_url>/connections/callback` (the same
   callback lik-ui uses for every data connection).
4. Record the app's **client id + secret** for step C.

The Slack MCP server exposes a **curated tool subset** (search, messages, canvases, users) —
no file ops, reminders, workflow triggers, or admin methods.

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

Set the three `LIK_UI_SLACK_*` params — already in `infra/ssm-secrets.example` and the step-1
placeholder seed. Use `set-ssm-secrets.sh` with a single-secret file per "Populate SSM secrets",
step 3. `RESOURCE_URL` is the fixed external URL, stored in SSM like the GitHub one:

```
/ik-arch/prod/lik-ui/LIK_UI_SLACK_CLIENT_ID=…
/ik-arch/prod/lik-ui/LIK_UI_SLACK_CLIENT_SECRET=…
/ik-arch/prod/lik-ui/LIK_UI_SLACK_RESOURCE_URL=https://mcp.slack.com/mcp
```

### D. Update the agent definition to declare the Slack server

The connection only appears once the agent declares it. On the **Claude Managed Agents
platform** (out-of-band, per "Agent MCP-server URL dependency" above), add a `mcp_servers`
entry to `agent_016uQNVgNEVtcAmvwKtskh8d` with url `https://mcp.slack.com/mcp`. That URL
must **exactly equal** `LIK_UI_SLACK_RESOURCE_URL` (normalized — a trailing slash is
tolerated, nothing else); a mismatch means lik-ui has no client for the declared URL and the
connect fails with *"…has no dynamic client registration and no configured client."*

### E. Redeploy and verify

1. `terraform apply` (deploy step 6) so the `LIK_UI_SLACK_*` values land in the container from
   SSM. The Slack code is already in the image, so no rebuild is needed unless the currently
   deployed `lik-ui` image predates it (built before the Slack source entry merged) — in that
   case rebuild + push first (deploy step 4).
2. Sign in and open `/connections`: a **Slack** row now appears (declared by the agent),
   marked not-connected.
3. Click connect → Slack OAuth 2.0 / PKCE → back to `/connections/callback`; lik-ui deposits
   the per-user credential in the vault and the row flips to connected.
4. In a chat session, confirm the agent can call a Slack tool (e.g. a message search). A
   `403`/access-forbidden on the first tool call after a clean connect usually means missing
   or wrong scopes in the `sources.py` entry (step A) — reconnect after fixing, since a new
   scope needs fresh consent.

---

## Custom-domain migration (later)

Currently the services use the Lightsail-provided HTTPS URLs. To move to a custom domain
(see `../domain-name.md` for the console DNS/certificate steps):

1. Validate and attach the custom domains to each container service — a Lightsail-managed
   certificate per service, then point DNS at the services (`../domain-name.md` Steps 1–6).
   Do this **first**: the URL-derived env values below must not advertise a name that isn't
   serving yet. The `public_domain_names` attachment is already declared in `lik_ui.tf` /
   `lik_mcp.tf` (a `dynamic` block gated on the domain vars, with `certificate_name`
   `lik-ui-prod-cert` / `lik-mcp-prod-cert`) — so once the vars are set it stays under
   Terraform management. If you attach via the console first, setting the vars makes the
   config match the attachment (no destroy); if the cert names differ from those literals,
   update them in the `.tf` to match, or Terraform will try to remove the attachment.
2. Update the OAuth client redirect URIs (both `/auth/callback` and `/connections/callback`)
   in each provider console to the new `ui.` domain (`../domain-name.md` Step 7.b).
3. Set the custom-domain variables and `terraform apply`:
   ```
   ui_custom_domain_url  = "https://ui.lik.navapbc.com"
   mcp_custom_domain_url = "https://mcp.lik.navapbc.com"   # /mcp is appended automatically
   ```
   These drive the URL-derived env values (`LIK_UI_APP_BASE_URL`, `LIK_RESOURCE_SERVER_URL`,
   `LIK_UI_LIKMCP_RESOURCE_URL`, and the `*_ALLOWED_HOSTS`). **They do not update on their own**
   — the container service's `.url` attribute always returns the default
   `...cs.amazonlightsail.com` address even after a custom domain is attached, so the friendly
   URL must be supplied explicitly through these variables.
4. Update the **agent definition's** declared lik-mcp `mcp_servers` URL to
   `https://mcp.lik.navapbc.com/mcp` (out-of-band, per the note above) so it matches the new
   `LIK_UI_LIKMCP_RESOURCE_URL`. Because the custom domain is stable across future infra
   changes, this is the last time that URL should need to change.
5. Because the lik-mcp resource URL is the vault credential key, users may need to reconnect
   lik-mcp once after the switch.

---

## TLS note

The DB runs Postgres 18 (>= 15), so `rds.force_ssl=1` is the default — TLS is enforced
server-side and clients connect with `sslmode=require`. If a `< 15` engine is ever used,
additionally run:

```
AWS_PROFILE=lik mise exec -- aws lightsail update-relational-database-parameters \
  --region us-east-1 --relational-database-name lik-prod-db \
  --parameters "parameterName=rds.force_ssl,parameterValue=1,applyMethod=pending-reboot"
AWS_PROFILE=lik mise exec -- aws lightsail reboot-relational-database \
  --region us-east-1 --relational-database-name lik-prod-db
```
