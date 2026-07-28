# Production Deploy Runbook (AWS Lightsail, us-east-1)

This is the step-by-step procedure to deploy and rebuild the `lik-mcp` and `lik-ui`
services on AWS. Terraform (in `infra/`) owns all AWS resources; this runbook owns the
steps Terraform can't do declaratively: bootstrapping the state bucket, populating secrets,
pushing images, and initializing the database schema.

> **OAuth is documented separately.** Registering the OAuth clients each data-source connection
> needs (Google, GitHub, Slack), the provider-specific challenges (Atlassian re-auth, Google
> Drive preview gating, GitHub org transfer), and how to diagnose a failing connection all live
> in [`oauth.md`](oauth.md). Step 2 below is a pointer into it.

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
> `./tf.sh plan`, `./tf.sh apply`, `./tf.sh output`. It mints fresh credentials at the start of
> each run. Use it in place of the manual export + bare `terraform` in the steps below.
>
> ⚠️ **Long applies can still outlive the minted credentials.** The credentials are minted once
> at invocation and are short-lived; an apply that **creates or replaces a Lightsail deployment**
> waits ~3 min per deployment, which can exceed the session's remaining lifetime and expire the
> token mid-apply. When that happens Terraform fails to save state to S3 and to release the lock
> (the AWS changes may have already landed). So: run `AWS_PROFILE=lik mise exec -- aws login`
> **immediately before** any deployment-replacing apply, to maximize the remaining lifetime.
> Recovery if it does expire: `aws login`, then `./tf.sh force-unlock <id>`, then
> `terraform state push errored.tfstate` (Terraform writes the local `errored.tfstate` and
> prints this exact command), then re-run the apply — the tainted deployment recreates cleanly
> (rolling, no downtime) and state re-converges.

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
./tf.sh init
```

---

## Deploy sequence (first time)

The order matters: services must exist to yield the URLs that OAuth clients are keyed to,
and secrets must be in SSM before the container deployments boot under real auth.

### 1. Create the database, container services, and CI role ✅ done (2026-07-15)

Bootstrap everything except the container deployments (those need image refs + secrets).
`tf.sh` mints fresh credentials for you, so no manual export is needed:

```
cd infra
./tf.sh apply \
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
>      lik-ui/LIK_UI_SLACK_CLIENT_SECRET lik-ui/LIK_UI_SLACK_RESOURCE_URL shared/ANTHROPIC_API_KEY; do
>      AWS_PROFILE=lik mise exec -- aws ssm put-parameter --region us-east-1 --type SecureString \
>        --name "/ik-arch/prod/$n" --value PLACEHOLDER_REPLACE_ME; done
>    ```
> 2. **Run this apply in the background / with a long timeout.** DB creation takes 5–10 min.
>    If the apply process is killed mid-flight, resources get created in AWS but not recorded
>    in state (orphans), and you must `./tf.sh force-unlock <id>` then `./tf.sh import`
>    each orphan (`random_password.db_master` must be imported from a `bash` script file to
>    dodge the password-quoting gotcha). Prefer letting it run to completion.

Record the outputs:

```
./tf.sh output
```

You'll use `lik_mcp_service_url`, `lik_mcp_resource_server_url`, `lik_ui_service_url`,
`lik_ui_oauth_callback_urls`, and `github_image_push_role_arn` — captured values are in the
Deployment status table above.

### 2. Register OAuth clients under Nava org ownership ✅ done

**Moved to [`oauth.md`](oauth.md).** Create new Nava-org-owned clients (Google app-login + lik-mcp
+ Drive, GitHub) keyed to the service URLs from step 1, then record each client id + secret for
step 3. The two equality constraints that affect the SSM values in step 3:

- The lik-mcp connection's **client id** must equal lik-mcp's `LIK_OAUTH_CLIENT_ID` (same Google
  client) — Terraform reuses the single SSM param, so store it once.
- lik-ui's lik-mcp **resource URL** must equal `lik_mcp_resource_server_url` (Terraform-derived —
  nothing to store).

See [`oauth.md`](oauth.md) → "Registering OAuth clients under Nava org ownership" for the full
per-provider procedure and the provider-specific challenges (Google Drive preview enrollment,
GitHub org transfer, Atlassian re-auth).

### 3. Populate SSM secrets ✅ done (no placeholders remain)

Overwrite the placeholder SecureStrings with real values. Edit **one** file mapping each SSM
name to its value, then run a loop that injects each via a per-line temp file and `file://`.
This keeps secrets off the command line (out of shell history / `ps`) and avoids the
special-char quoting breakage (a `)` trips the mise zsh hook, same as the DB password) — while
only asking you to edit a single file.

**The agent roster is no longer in SSM.** It lives in the checked-in `lik-ui/src/lik_ui/agents.toml`,
shipped inside the container image. The roster lists agents **by name** (not platform ids); lik-ui
resolves those names to ids at startup via the SDK. Add/remove agents by editing it via PR (the agent
and environment definitions themselves live under `claude_platform/` and deploy via
`.github/workflows/deploy-agents.yml`), then rebuild the image and redeploy. The old
`/ik-arch/prod/lik-ui/LIK_UI_AGENTS_CONFIG` SSM parameter is now orphaned and can be deleted
out-of-band: `AWS_PROFILE=lik mise exec -- aws ssm delete-parameter --region us-east-1 --name /ik-arch/prod/lik-ui/LIK_UI_AGENTS_CONFIG`.

**Which params must be real vs. can stay placeholder:** the app's prod fail-closed guard only
requires `LIK_UI_SESSION_SECRET`, `LIK_UI_APP_OAUTH_CLIENT_ID`, `LIK_UI_APP_OAUTH_CLIENT_SECRET`,
the shared `ANTHROPIC_API_KEY` (under `$P/shared/`), plus lik-mcp's `LIK_OAUTH_CLIENT_ID` (and a
non-empty `agents.toml`). The
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
`APP_OAUTH_*`, `ANTHROPIC_API_KEY`, `SESSION_SECRET`, `LIK_OAUTH_CLIENT_ID`).
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
# then redeploy so the container picks it up:  ./tf.sh apply
```

Verify nothing required is still a placeholder before deploying:

```bash
AWS_PROFILE=lik mise exec -- aws ssm get-parameters-by-path --path /ik-arch/prod \
  --recursive --with-decryption --region us-east-1 --output json \
  | grep -B1 PLACEHOLDER_REPLACE_ME | grep '"Name"'
```

Any `LIK_UI_APP_*`, `shared/ANTHROPIC_API_KEY`, `LIK_UI_SESSION_SECRET`,
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
| `AWS_APPLY_ROLE_ARN` | `arn:aws:iam::293033346213:role/github-actions-lik-apply` | env `prod` |
| `AWS_REGION` | `us-east-1` | env `prod` |

`AWS_APPLY_ROLE_ARN` is the `apply` job's role (`terraform output github_apply_role_arn`).
The role is created by Terraform, so it must exist before the first CI apply — run one local
`cd infra && ./tf.sh apply` after merging the role, then set the variable.

To recreate or inspect:
```bash
gh api --method PUT repos/navapbc/leverage-inst-knowl/environments/prod   # create the env
gh variable set AWS_DEPLOY_ROLE_ARN --env prod --repo navapbc/leverage-inst-knowl \
  --body arn:aws:iam::293033346213:role/github-actions-lik-image-push
gh variable set AWS_APPLY_ROLE_ARN --env prod --repo navapbc/leverage-inst-knowl \
  --body arn:aws:iam::293033346213:role/github-actions-lik-apply
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

The DB connection comes from Terraform (the single source of truth) — no hardcoded host and no
hand-set `LIK_DB_*`. Resolve it into your shell with the helper (needs terraform state access +
AWS creds, which you already have if you run terraform); it exports `LIK_DB_*` + `SSM_PREFIX`:

```bash
cd lik-mcp
eval "$(AWS_PROFILE=lik mise exec -- scripts/db_env_from_terraform.sh)"   # LIK_DB_* for the master db (likdb)

# 1. Create lik-ui's database on the shared instance (connect to the master DB 'likdb' first)
psql "host=$LIK_DB_HOST port=$LIK_DB_PORT dbname=$LIK_DB_NAME user=$LIK_DB_USER password=$LIK_DB_PASSWORD sslmode=require" \
  -c "CREATE DATABASE likuidb;"

# 2. lik-mcp schema — its script applies lik-mcp/db/init.sql via psycopg, as master user, using
#    the LIK_DB_* already exported above.
mise exec -- uv run python scripts/init_db.py
cd ..

# 3. lik-ui schema — its script applies lik-ui/db/init.sql via psycopg, as master user
#    (also applies non-destructive migrations like auto_delete_at; idempotent, safe to re-run).
#    --ssm-prefix reads the DB password from SSM and discovers host/port/user from Lightsail,
#    so no LIK_UI_DB_* vars are needed (db name defaults to likuidb).
cd lik-ui
AWS_PROFILE=lik mise exec -- uv run python scripts/init_db.py --ssm-prefix "$SSM_PREFIX"
cd ..
```

> `LIK_DB_PASSWORD` holds the special-char password. It's fine inside the quoted psql conninfo
> string above, but never echo it onto an interactive command line bare (the mise zsh hook
> parse-errors on `)`). If a command trips on it, run these from a `bash` script file.

All init scripts are idempotent (`IF NOT EXISTS`), so re-running is safe. Verify afterward:
`psql "...dbname=likdb..." -c '\dt'` shows `catalog`, `confirmations`; `...dbname=likuidb...`
shows `users`, `user_vaults`, `sessions`.

### 6. Deploy the container versions ✅ done (containers healthy; see step 5 caveat)

This creates the two `deployment_version` resources (the count-guard flips on once the image
vars are non-empty), and the containers boot under real `prod` auth using the SSM values.
`tf.sh` handles credentials and, on `apply`, auto-resolves each service's **latest** Lightsail
image — so a bare apply deploys exactly what step 4c just pushed:

```bash
cd infra
./tf.sh apply
```

To pin a specific build instead of the latest (e.g. redeploying an older ref), pass it with
`-var`; these override the auto-resolved defaults:

```bash
./tf.sh apply \
  -var 'lik_mcp_image=:lik-mcp-prod.app.N' \
  -var 'lik_ui_image=:lik-ui-prod.app.N'
```

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

## Scheduled agent runs (one-time setup)

The `scheduled-runs.yml` workflow runs users' scheduled agent runs on a cadence
(`lik-ui/scripts/run_scheduled.py`; see docs/plans/2026-07-28-002-...). Before enabling it in
prod, three things must be applied **by hand** — none happen automatically on merge:

**1. Create the `scheduled_runs` table on the prod DB.** `db/init.sql` uses
`CREATE TABLE IF NOT EXISTS`, so re-running it will not create the table on a DB that already
exists — apply it as a separate, non-destructive step (no drop/recreate). Connect to the `likuidb`
database as the master user (as in step 5) and run the `CREATE TABLE IF NOT EXISTS scheduled_runs`
+ its indexes from `lik-ui/db/init.sql`. Idempotent; safe to re-run.

**2. Provision a table-scoped DB role** (least privilege — R18). The scanner must NOT use the
master credential; a compromise of the CI credential would otherwise expose the whole DB over the
public endpoint. Create a role granted only on `scheduled_runs` and `sessions`:

```sql
-- as the master user, connected to the likuidb database
CREATE ROLE lik_scheduled_runs LOGIN PASSWORD '<generated>';
GRANT CONNECT ON DATABASE likuidb TO lik_scheduled_runs;
GRANT USAGE ON SCHEMA public TO lik_scheduled_runs;
GRANT SELECT, INSERT, UPDATE, DELETE ON scheduled_runs, sessions TO lik_scheduled_runs;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lik_scheduled_runs;  -- for scheduled_runs.id
```

(The runner touches `users`/`user_vaults` only via read — add `GRANT SELECT ON users, user_vaults`
if a run needs to resolve those; grant the minimum the run actually uses and no more.)

**3. Store the scoped role's credentials in SSM and grant CI read.** Put the user and password in
`$SSM_PREFIX/shared/SCHEDULED_RUNS_DB_USER` (String) and `.../SCHEDULED_RUNS_DB_PASSWORD`
(SecureString). The `github-actions-lik-ssm-read` role already lists these two params
(`infra/iam_github_oidc.tf`, `SharedSecretsRead`) — run `./tf.sh apply` so the IAM change lands
before the workflow's first run, or its `aws ssm get-parameter` will be denied.

After all three, trigger `scheduled-runs.yml` via `workflow_dispatch` to verify end-to-end before
relying on the cron.

---

## Routine redeploy (new image)

Run the **Build and push container images** workflow (UI or `gh workflow run …`). After the
`push` job builds and pushes, the `apply` job deploys automatically **when the plan is a clean
image swap** — `Plan: 1 to add, 0 to change, 1 to destroy.` (one service) or
`2 to add, 0 to change, 2 to destroy.` (both). The run summary shows `✅ Deployed` with the refs.

A single-service run still deploys safely: the `apply` job resolves the *other* service's
current image ref from Lightsail and passes both, so it never destroys the untouched service.

**If the plan is anything else** (config drift, or any `to change`), the `apply` job skips the
apply and the run summary prints the exact command to run locally after review:

```bash
cd infra && ./tf.sh apply -var "lik_mcp_image=…" -var "lik_ui_image=…"
```

(use the exact `-var` image refs the run summary lists).

No secret or DB steps needed unless config changed. The auto-apply gate is intentionally
conservative — it only ever fails *toward* manual review, never toward an unattended dirty apply.
If an AWS-provider upgrade ever changes how a deployment replacement is summarized, the gate
stops matching and every run routes to the manual path until the summary strings are updated.

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

**Why this matters for this deploy:** the agent's spec
(under `claude_platform/agents/`) declares the lik-mcp server URL. If it was
authored pointing at an old deployment (e.g. `https://leverage-inst-knowl.onrender.com/mcp`), update
the `mcp_servers` URL in that spec and redeploy via `deploy-agents.yml` — for example the Lightsail URL:

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

**Moved to [`oauth.md`](oauth.md) → "Adding the Slack MCP connection".** Slack is already wired in
code and infra; what remains is external OAuth setup (create the org-owned Slack app, populate the
`LIK_UI_SLACK_*` secrets, declare the server on the agent) plus a redeploy + verify. The redeploy is
the runbook's deploy step 6; the SSM population uses `set-ssm-secrets.sh` per deploy step 3.

---

## Custom-domain migration (done — reference)

The prod services are served at `https://ui.lik.navapbc.com` and `https://mcp.lik.navapbc.com`.
`tf.sh` defaults `ui_custom_domain_url` / `mcp_custom_domain_url` to these on every `apply`, so
the custom domains are **on by default** — a bare `./tf.sh apply` keeps them set. This section
records how the migration was performed and what to touch if the domains ever change (see
`../domain-name.md` for the console DNS/certificate steps).

1. Validate and attach the custom domains to each container service — a Lightsail-managed
   certificate per service, then point DNS at the services (`../domain-name.md` Steps 1–6).
   This must happen **before** an apply sets the domain vars: the URL-derived env values below
   must not advertise a name that isn't serving yet. Since `tf.sh` now defaults the domain vars
   ON, deploying to a **new** environment whose domain isn't attached yet requires overriding
   them to empty first — `./tf.sh apply -var 'ui_custom_domain_url=' -var 'mcp_custom_domain_url='`
   — to fall back to the Lightsail URLs until the domain is serving. The `public_domain_names`
   attachment is declared in `lik_ui.tf` / `lik_mcp.tf` (a `dynamic` block gated on the domain
   vars, with `certificate_name` `lik-ui-prod-cert` / `lik-mcp-prod-cert`) — so once the vars are
   set it stays under Terraform management. If you attach via the console first, setting the vars
   makes the config match the attachment (no destroy); if the cert names differ from those
   literals, update them in the `.tf` to match, or Terraform will try to remove the attachment.
2. Update the OAuth client redirect URIs (both `/auth/callback` and `/connections/callback`)
   in each provider console to the new `ui.` domain (`../domain-name.md` Step 7.b).
3. Apply. The domain vars default to the nava URLs in `tf.sh`, so a plain `./tf.sh apply`
   applies them (`/mcp` is appended to the mcp URL automatically). To use *different* domains,
   override with `-var`:
   ```bash
   ./tf.sh apply \
     -var 'ui_custom_domain_url=https://ui.example.com' \
     -var 'mcp_custom_domain_url=https://mcp.example.com'
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
