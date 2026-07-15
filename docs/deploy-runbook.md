# Production Deploy Runbook (AWS Lightsail, us-east-1)

This is the step-by-step procedure to deploy and rebuild the `lik-mcp` and `lik-ui`
services on AWS. Terraform (in `infra/`) owns all AWS resources; this runbook owns the
steps Terraform can't do declaratively: bootstrapping the state bucket, registering OAuth
clients, populating secrets, pushing images, and initializing the database schema.

**Conventions**
- All commands run with `AWS_PROFILE=lik` and via `mise exec --`, e.g.
  `AWS_PROFILE=lik mise exec -- aws ...` / `mise exec -- terraform ...`.
- Region is **us-east-1** for everything. The old `us-east-2` Lightsail DB is **not**
  touched by any step here.

> ⚠️ **Do NOT `terraform destroy` a container service in normal operation.** Its public
> URL contains a hash that changes on recreate, which breaks every OAuth registration
> keyed to it. If you must recreate one, plan to re-register OAuth clients and re-apply.

---

## One-time: bootstrap the state bucket

The S3 backend bucket must exist (with versioning) before `terraform init`. Create it once:

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

### 1. Create the database, container services, and CI role

Bootstrap everything except the container deployments (those need image refs + secrets):

```
cd infra
AWS_PROFILE=lik mise exec -- terraform apply \
  -target=aws_lightsail_database.main \
  -target=aws_lightsail_container_service.lik_mcp \
  -target=aws_lightsail_container_service.lik_ui \
  -target=aws_iam_role.github_image_push \
  -target=aws_iam_role_policy.image_push
```

Record the outputs:

```
AWS_PROFILE=lik mise exec -- terraform output
```

You'll use `lik_mcp_service_url`, `lik_mcp_resource_server_url`, `lik_ui_service_url`,
`lik_ui_oauth_callback_urls`, and `github_image_push_role_arn`.

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
