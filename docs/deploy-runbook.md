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

Transfer ownership at https://github.com/settings/applications/3731288

### 3. Populate SSM secrets

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

**Step A — create the template file.** This writes a single `NAME=value` file, with the
session secret pre-generated for you:

```bash
P=/ik-arch/prod
SF=$(mktemp) && chmod 600 "$SF"
cat > "$SF" <<EOF
# Replace each … with the real value. DELETE or #-comment any line you are not setting
# (e.g. a connection you haven't configured) — its SSM placeholder is left untouched.
# Value is everything after the first '=' (so '=' inside secrets is fine). No quotes, no
# trailing spaces. One line per secret.

$P/lik-mcp/LIK_OAUTH_CLIENT_ID=…apps.googleusercontent.com

$P/lik-ui/LIK_UI_APP_OAUTH_CLIENT_ID=…
$P/lik-ui/LIK_UI_APP_OAUTH_CLIENT_SECRET=…

$P/lik-ui/LIK_UI_ANTHROPIC_API_KEY=sk-ant-…

$P/lik-ui/LIK_UI_AGENTS_CONFIG=agent_…:env_…

# LIK_UI_LIKMCP_CLIENT_ID is intentionally absent: it must equal lik-mcp's
# LIK_OAUTH_CLIENT_ID (same Google client), so Terraform reuses that one param —
# setting LIK_OAUTH_CLIENT_ID above covers it. Same for LIK_UI_LIKMCP_RESOURCE_URL,
# which Terraform derives from the lik-mcp service URL. Only the secret is separate:
$P/lik-ui/LIK_UI_LIKMCP_CLIENT_SECRET=…

$P/lik-ui/LIK_UI_GDRIVEMCP_CLIENT_ID=…
$P/lik-ui/LIK_UI_GDRIVEMCP_CLIENT_SECRET=…
$P/lik-ui/LIK_UI_GDRIVEMCP_RESOURCE_URL=https://drivemcp.googleapis.com/mcp/v1

# GitHub OAuth App client id — opaque, format varies (NOT the Iv1. "GitHub App" format);
# paste yours verbatim, whatever its shape.
$P/lik-ui/LIK_UI_GITHUB_CLIENT_ID=…
$P/lik-ui/LIK_UI_GITHUB_CLIENT_SECRET=…
$P/lik-ui/LIK_UI_GITHUB_RESOURCE_URL=https://api.githubcopilot.com/mcp

$P/lik-ui/LIK_UI_SESSION_SECRET=$(openssl rand -hex 32)
EOF
echo "Edit this file: $SF"
```

**Step B — edit `$SF`** in your editor: replace each `…` with the real value; delete or
`#`-comment the connection lines you're not setting yet (leave the boot-required ones —
`APP_OAUTH_*`, `ANTHROPIC_API_KEY`, `AGENTS_CONFIG`, `SESSION_SECRET`, `LIK_OAUTH_CLIENT_ID`).

**Step C — push, then shred.** The loop writes each value to a short-lived temp file and
sends it with `file://`, so no secret ever appears on a command line. Lines that are blank,
`#`-commented, or still contain `…` are skipped:

```bash
while IFS='=' read -r name value; do
  case "$name" in ''|\#*) continue ;; esac                 # skip blank / comment lines
  if printf %s "$value" | grep -q '…'; then                # skip un-filled placeholders
    echo "skip (still placeholder): $name"; continue
  fi
  f=$(mktemp)
  printf %s "$value" > "$f"                                # exact value, no trailing newline
  AWS_PROFILE=lik mise exec -- aws ssm put-parameter --region us-east-1 \
    --type SecureString --overwrite --name "$name" --value "file://$f"
  rm -f "$f"
done < "$SF"
rm -f "$SF"                                                # shred the master file
```

Verify nothing required is still a placeholder before deploying:

```bash
AWS_PROFILE=lik mise exec -- aws ssm get-parameters-by-path --path /ik-arch/prod \
  --recursive --with-decryption --region us-east-1 --output json \
  | grep -B1 PLACEHOLDER_REPLACE_ME | grep '"Name"'
```

Any `LIK_UI_APP_*`, `LIK_UI_ANTHROPIC_API_KEY`, `LIK_UI_AGENTS_CONFIG`, `LIK_UI_SESSION_SECRET`,
or `LIK_OAUTH_CLIENT_ID` still listed here will make the container fail its prod guard at boot.

### 4. Build and push images

> **Prerequisite: the workflow must run from `main`.** The OIDC role trusts only
> `repo:navapbc/leverage-inst-knowl:ref:refs/heads/main` (see `infra/iam_github_oidc.tf`), so
> a run from any other branch fails role assumption with "Not authorized to perform
> sts:AssumeRoleWithWebIdentity". Merge/push the `.github/workflows/deploy-images.yml` file to
> `main` before running. (To allow other branches, add their `sub` to the trust policy and
> re-apply — but keep prod deploys on `main`.)

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

> **Two environment gotchas:** (1) env-scoped variables resolve only because the job sets
> `environment: prod` — remove that line and the workflow sees empty values. (2) The OIDC
> trust is still **branch-based** (`ref:refs/heads/main`), independent of the environment. If
> you later want per-environment roles, switch the trust `sub` to
> `repo:navapbc/leverage-inst-knowl:environment:prod` in `infra/iam_github_oidc.tf` and
> re-apply — but that claim is only present because the job declares `environment: prod`, so
> keep the two in sync. Adding a real `dev` also requires a parallel Terraform stack (separate
> DB/services/SSM prefix/state), which is out of the current single-env scope.

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

### 5. Initialize the database schema

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
shows `users`, `user_vaults`, `sessions`, `dcr_registrations`.

### 6. Deploy the container versions

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

Recommended: put the refs in a gitignored `infra/prod.tfvars` so redeploys don't retype them
(`*.tfvars` is already gitignored):

```bash
cat > prod.tfvars <<'EOF'
lik_mcp_image = ":lik-mcp-prod.app.N"
lik_ui_image  = ":lik-ui-prod.app.N"
EOF
mise exec -- terraform apply -var-file=prod.tfvars
```

The deployment takes a few minutes per service. Run it in the background or leave it to
finish — a killed apply orphans state (see the step-1 gotcha).

### 7. Verify

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
