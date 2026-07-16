# infra/ — Production AWS deployment (Terraform)

Terraform configuration for the production deployment of `lik-mcp` and `lik-ui` on AWS
Lightsail in **us-east-1**. See [`docs/deploy-runbook.md`](../docs/deploy-runbook.md) for
the step-by-step deploy/rebuild procedure, and the origin design docs:
[plan](../docs/plans/2026-07-15-001-feat-aws-terraform-production-deploy-plan.md),
[requirements](../docs/brainstorms/2026-07-15-01-aws-terraform-production-deploy-requirements.md).

## Architecture

```
        Internet (HTTPS)
       /                \
 lik-mcp-prod        lik-ui-prod          Lightsail Container Services
 (container, :8000)  (container, :8001)   built-in TLS + public URL
       \                /
        \              /  sslmode=require (public endpoint)
      lik-prod-db (Lightsail Postgres 18)
      databases: likdb (mcp), likuidb (ui)

 Secrets: SSM Parameter Store (/ik-arch/prod/**), read by Terraform, injected as env vars.
 State:   s3://ik-arch-tfstate-293033346213 (native locking, versioned, encrypted).
 CI:      GitHub Actions builds + pushes images via OIDC role (no long-lived keys).
```

## Why Lightsail Container Service + public-mode DB

Container Services give managed TLS, HTTPS URLs, and rolling deploys with minimal ops.
They cannot reach a Lightsail managed DB over its *private* endpoint, so the DB runs in
public mode reached over enforced TLS — an accepted tradeoff for an internal low-traffic
tool. See the plan's "Rejected Alternative: Lightsail Instances" section for the full
reasoning.

## Resource inventory

| File | Resources |
|------|-----------|
| `backend.tf` | S3 remote state backend (native locking) |
| `providers.tf` | aws / random / tls providers, `us-east-1`, default tags |
| `variables.tf` | region, SSM prefix, DB blueprint/bundle/names, container sizing, custom-domain URLs, image refs, GitHub OIDC subject |
| `database.tf` | `aws_lightsail_database` (empty, public mode) + generated master password → SSM |
| `ssm.tf` | `aws_ssm_parameter` data sources for all secrets (read, not authored) |
| `lik_mcp.tf` | lik-mcp container service + deployment version (health check `/mcp`, 200-499) |
| `lik_ui.tf` | lik-ui container service + deployment version (health check `/healthz`) |
| `iam_github_oidc.tf` | GitHub OIDC provider + image-push role (repo/branch-scoped trust) |
| `outputs.tf` | service URLs, OAuth callback URLs, DB endpoint, CI role ARN |

## Conventions

- Run everything with `AWS_PROFILE=lik` via `mise exec --`.
- The deployment versions only materialize when `lik_mcp_image` / `lik_ui_image` are set
  (Lightsail-registered refs from the CI push). A bootstrap apply omits them.
- Secrets live only in SSM (source of truth) and in encrypted state — never in `*.tf` or
  committed tfvars. The `.terraform.lock.hcl` is committed; state and `*.tfvars` are not.

## URL-derived env values and custom domains

Several env vars are **not** stored in SSM — they are computed from each container service's
URL so the cross-service equality constraints hold structurally (see the note at the top of
`ssm.tf`):

- `LIK_UI_APP_BASE_URL`, `LIK_UI_HTTP_ALLOWED_HOSTS` (from lik-ui's URL)
- `LIK_RESOURCE_SERVER_URL`, `LIK_HTTP_ALLOWED_HOSTS` (from lik-mcp's URL)
- `LIK_UI_LIKMCP_RESOURCE_URL` (reuses lik-mcp's value, guaranteeing they match)

**Gotcha:** a Lightsail container service's `.url` attribute **always** returns the default
`...cs.amazonlightsail.com` address — even after a custom domain is validated and attached.
No provider attribute exposes the attached custom domain, so these values do **not** follow a
custom domain on their own. To advertise a friendly domain, set the base URLs explicitly:

```
ui_custom_domain_url  = "https://ui.lik.navapbc.com"
mcp_custom_domain_url = "https://mcp.lik.navapbc.com"   # /mcp is appended automatically
```

When empty (the default), the locals fall back to `.url` — the correct pre-domain / bootstrap
state. Only populate them **after** the custom domain is validated and attached, or the apps
will advertise a name that isn't serving yet. Full procedure (certificate, DNS, OAuth
redirect URIs, agent-definition URL, reconnect caveat): see
[`docs/deploy-runbook.md`](../docs/deploy-runbook.md) "Custom-domain migration" and
[`../domain-name.md`](../domain-name.md).

## Deferred

Full auto-deploy (running `terraform apply` inside CI on merge) is intentionally not built
— the CI role is push-only. See plan sections N2 / Q5 for the escalation path and effort.
