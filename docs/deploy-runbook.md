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

> ⚠️ **The DB master password contains shell-special characters** (`()[]{}<>` …). Never put
> it on an interactive command line (the mise zsh hook parse-errors on `)`). Always read it
> into a variable from SSM and reference it quoted, or run the step from a `bash` script
> file — see "Initialize the database schema".

---

## Deployment status (2026-07-15)

Bootstrap (database + both container services + GitHub OIDC role) is **applied and in
Terraform state**. Live identifiers:

| Resource | Value |
|----------|-------|
| lik-mcp service URL | `https://lik-mcp-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/` |
| lik-mcp resource URL (`LIK_RESOURCE_SERVER_URL`) | `https://lik-mcp-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/mcp` |
| lik-ui service URL (`LIK_UI_APP_BASE_URL`) | `https://lik-ui-prod.bf6j3fzhc5rxe.us-east-1.cs.amazonlightsail.com/` |
| DB endpoint | `ls-775fd23f9d76047da44b78ee7307c91023cfc535.celyyosemrsx.us-east-1.rds.amazonaws.com:5432` |
| CI image-push role | `arn:aws:iam::293033346213:role/github-actions-lik-image-push` |

**Remaining before the site is live** (steps 2–7 below): register OAuth clients with the
callback URLs above, replace the placeholder SSM secrets with real values, build+push
images, initialize schema, and run the deployment apply.

> **SSM parameters are currently PLACEHOLDERS.** All `/ik-arch/prod/lik-*/…` secret params
> were seeded with `PLACEHOLDER_REPLACE_ME` so that `terraform plan`/`import` could resolve
> the `ssm.tf` data sources during bootstrap. **They must be overwritten with real values
> (step 3) before the deployment apply**, or the services will boot with garbage config.

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
>      lik-ui/LIK_UI_GITHUB_CLIENT_SECRET lik-ui/LIK_UI_GITHUB_RESOURCE_URL lik-ui/LIK_UI_ANTHROPIC_API_KEY \
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

### 2. Register OAuth clients under Nava org ownership

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
5. **Add org co-owners** so the clients aren't bound to one person: IAM → grant another Nava
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

### 3. Populate SSM secrets

Store every value as a SecureString. Replace the `…` placeholders.

```
P=/ik-arch/prod
put() { AWS_PROFILE=lik mise exec -- aws ssm put-parameter --region us-east-1 --type SecureString --overwrite --name "$1" --value "$2"; }

# lik-mcp
put "$P/lik-mcp/LIK_OAUTH_CLIENT_ID"          "…apps.googleusercontent.com"

# lik-ui — app login + core
put "$P/lik-ui/LIK_UI_SESSION_SECRET"          "$(openssl rand -hex 32)"
put "$P/lik-ui/LIK_UI_APP_OAUTH_CLIENT_ID"     "…"
put "$P/lik-ui/LIK_UI_APP_OAUTH_CLIENT_SECRET" "…"
put "$P/lik-ui/LIK_UI_ANTHROPIC_API_KEY"       "sk-ant-…"
put "$P/lik-ui/LIK_UI_AGENTS_CONFIG"           "agent_…:env_…"

# lik-ui — lik-mcp connection (client id reused from lik-mcp above; only the secret here)
put "$P/lik-ui/LIK_UI_LIKMCP_CLIENT_SECRET"    "…"

# lik-ui — Google Drive connection
put "$P/lik-ui/LIK_UI_GDRIVEMCP_CLIENT_ID"     "…"
put "$P/lik-ui/LIK_UI_GDRIVEMCP_CLIENT_SECRET" "…"
put "$P/lik-ui/LIK_UI_GDRIVEMCP_RESOURCE_URL"  "https://…/mcp"

# lik-ui — GitHub connection
put "$P/lik-ui/LIK_UI_GITHUB_CLIENT_ID"        "Iv1.…"
put "$P/lik-ui/LIK_UI_GITHUB_CLIENT_SECRET"    "…"
put "$P/lik-ui/LIK_UI_GITHUB_RESOURCE_URL"     "https://…/mcp"
```

(`DB_MASTER_PASSWORD` under `$P/shared/` is created by Terraform — do not set it here.)

### 4. Build and push images

Set repo variables `AWS_DEPLOY_ROLE_ARN` (= `github_image_push_role_arn` output) and
`AWS_REGION=us-east-1`, then run the **Build and push container images** workflow
(Actions tab → Run workflow → `both`). Copy the two `:svc.app.N` refs it prints.

### 5. Initialize the database schema

The DB is empty. lik-ui also needs its own database created on the shared instance. Run
these once as the **master user** (needed for lik-mcp's `pg_trgm` extension + roles). Pull
the password from SSM:

```
DB_HOST=$(cd infra && AWS_PROFILE=lik mise exec -- terraform output -json db_endpoint | mise exec -- jq -r .host)
DB_PW=$(AWS_PROFILE=lik mise exec -- aws ssm get-parameter --region us-east-1 --with-decryption \
  --name /ik-arch/prod/shared/DB_MASTER_PASSWORD --query Parameter.Value --output text)

# Create lik-ui's database on the shared instance
mise exec -- psql "host=$DB_HOST port=5432 dbname=likdb user=lik password=$DB_PW sslmode=require" \
  -c "CREATE DATABASE likuidb;"

# lik-mcp schema (script applies lik-mcp/db/init.sql; run as master user)
cd lik-mcp
LIK_DB_HOST=$DB_HOST LIK_DB_NAME=likdb LIK_DB_USER=lik LIK_DB_PASSWORD=$DB_PW LIK_DB_SSLMODE=require \
  mise exec -- uv run python scripts/init_db.py
cd ..

# lik-ui schema
mise exec -- psql "host=$DB_HOST port=5432 dbname=likuidb user=lik password=$DB_PW sslmode=require" \
  -f lik-ui/db/init.sql
```

All init scripts are idempotent (`IF NOT EXISTS`), so re-running is safe.

### 6. Deploy the container versions

```
cd infra
AWS_PROFILE=lik mise exec -- terraform apply \
  -var 'lik_mcp_image=:lik-mcp-prod.app.N' \
  -var 'lik_ui_image=:lik-ui-prod.app.N'
```

(Use the refs from step 4. Consider a `prod.tfvars` — gitignored — to avoid retyping.)

### 7. Verify

```
curl -fsS <lik_ui_service_url>/healthz        # -> {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' <lik_mcp_resource_server_url>   # 401 = healthy (auth on)
```

Then open `<lik_ui_service_url>` in a browser and complete Google login and one data-source
connect end-to-end.

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

## Custom-domain migration (later)

Currently the services use the Lightsail-provided HTTPS URLs. To move to a custom domain:

1. Add `public_domain_names` to the `aws_lightsail_container_service` resources and attach
   a Lightsail-managed certificate; point DNS at the services.
2. Update the OAuth client redirect URIs (both `/auth/callback` and `/connections/callback`,
   and lik-mcp's resource URL) to the new domain in each provider console.
3. `terraform apply` — the derived `LIK_RESOURCE_SERVER_URL`, `LIK_UI_APP_BASE_URL`, and
   allowed-hosts values follow the new URLs automatically once the domain is the primary.

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
