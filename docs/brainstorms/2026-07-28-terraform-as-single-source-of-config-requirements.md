---
date: 2026-07-28
topic: terraform-as-single-source-of-config
status: ready-for-planning
---

# Terraform as the single source of environment config (fewer hand-set variables)

## Problem

Environment-identifying config — the SSM prefix, the DB instance, the lik-ui database name, the
region — is scattered and hand-assembled across CLI tools, Terraform, and CI. A developer running
`init_db` or `terraform`, or an operator reading the runbook, has to reconstruct values that
Terraform already knows:

- `init_db` reads `LIK_`-prefixed settings the caller must supply (host, port, user, name,
  sslmode, password) — see `lik-mcp/scripts/init_db.py`. The runbook is full of
  `LIK_DB_HOST=… LIK_DB_SSLMODE=require …` incantations plus separate SSM and Lightsail lookups.
- The three SSM-fetching workflows (`.github/workflows/prune-sessions.yml`, `deploy-agents.yml`,
  `deploy-skills.yml`) hardcode `SSM_PREFIX` default `/ik-arch/prod`.
- `prune-sessions.yml` additionally hardcodes `DB_INSTANCE: lik-prod-db` and
  `LIK_UI_DB_NAME: likuidb`, then discovers host/port/user from that named Lightsail instance.
- Terraform mirrors the same values in `infra/variables.tf` (`var.ssm_prefix`,
  `var.db_ui_database_name`), and `infra/database.tf` names `lik-prod-db`.

Every one of these is a copy of something Terraform declares. Copies drift, and each copy is one
more variable the next developer has to know to set correctly.

## Goal

**Terraform is the single source of truth for environment config, and every consumer reads it live
via `terraform output`.** A developer running `terraform`, `init_db`, or the CI workflows should
hand-set as few environment-identifying variables as possible — ideally none beyond AWS
credentials and the Terraform working directory. There is one place to change a value, and every
tool reflects it without a second edit.

This is a developer-experience and drift-prevention goal for the **single existing environment**.
A second environment (staging) is **not** a current goal (see Non-goals).

## Decision: Terraform emits a config bundle; consumers read it live

Terraform already declares every environment-specific value. It exposes them as a machine-readable
output bundle (e.g. SSM prefix, DB instance name, lik-ui database name, region — whatever the
downstream resolvers need). CLI tools and CI read that bundle **live** with `terraform output`
rather than hardcoding defaults or requiring hand-set env vars.

- **Live, not generated-and-committed.** Reading `terraform output` at run time means the value is
  always whatever infra currently says — no committed mirror file to regenerate, no drift window.
  The cost (a Terraform/AWS dependency at call time, and needing the backend initialized) is
  already paid by anyone running `terraform` or touching AWS.
- **One lookup, whole bundle.** Consumers read the bundle as a unit, so the SSM prefix and the DB
  target always describe the same environment — they can never half-resolve to a mismatched pair.

Rejected alternatives:

- **Committed generated config file.** No run-time Terraform dependency, but it must be
  regenerated and committed on every infra change, reintroducing exactly the drift this is meant
  to remove.
- **Per-environment GitHub Environment variables / repo config file.** Both put a second copy of
  the values outside Terraform that must be kept in sync by hand — the drift problem, relocated.
- **Coupling the SSM prefix to the app's `LIK_UI_ENV` runtime mode.** Rejected in PR #45 and still
  rejected: the infrastructure namespace and the app's runtime mode are different concepts that
  coincidentally both say "prod"; coupling them lets a rename of one silently break the other.

## Requirements

1. **Terraform exposes an environment-config output bundle** covering at least: SSM prefix, DB
   instance name, lik-ui database name, region. Structured so a consumer reads the whole bundle in
   one call.
2. **`init_db` resolves its target from that bundle** instead of requiring the caller to assemble
   `LIK_DB_*` variables by hand. (Password/host/port that come from SSM/Lightsail are resolved
   downstream of the bundle's instance name + prefix, not hand-set.)
3. **The three SSM-fetching workflows derive `SSM_PREFIX` from the bundle**, removing the
   hardcoded `/ik-arch/prod` default.
4. **`prune-sessions.yml` derives its full DB target (`DB_INSTANCE`, `LIK_UI_DB_NAME`) from the
   same bundle**, resolved together with `SSM_PREFIX` in one lookup.
5. **A failed or partial resolution fails loudly** rather than falling back to a hardcoded default
   or proceeding against a mismatched target.
6. **No environment-identifying value is duplicated outside Terraform.** Changing it in Terraform
   is sufficient; no tool needs a matching manual edit.
7. **GitHub Actions stores the minimum config it cannot derive at run time.** No GitHub secrets
   (secrets are already fetched from SSM at run time — preserve that; nothing moves *into* GitHub
   secrets). GitHub variables shrink to only the **AWS-auth bootstrap** that must exist *before* a
   Terraform/AWS call is possible: the role ARN to assume and the region. Everything obtainable
   *after* auth — `SSM_PREFIX`, `DB_INSTANCE`, `LIK_UI_DB_NAME` — comes from the Terraform bundle,
   not from `vars.*`.

## Scope

**In scope:**
- A Terraform output bundle of environment config.
- `init_db`, the three SSM-fetching workflows, and the runbook consuming it live via
  `terraform output`.
- Removing the hardcoded `/ik-arch/prod`, `lik-prod-db`, `likuidb` copies from CLI/CI call sites.
- Reducing GitHub Actions `vars.*` to the AWS-auth bootstrap only (role ARN + region); keeping
  secrets out of GitHub entirely (fetched from SSM at run time).

**Non-goals:**
- **Multiple environments / staging.** Keep the single Terraform state as-is. No workspaces, no
  per-environment backend keys, no re-scoping the CI OIDC role's `/ik-arch/prod/*` ARNs. The
  single-source design *generalizes* to a second environment if one ever appears, but that is not
  built or designed for now.
- The app's `LIK_UI_ENV` runtime mode — stays decoupled from the infra prefix.
- Changing what the values *are* (this only changes where they are read from).

## Success criteria

- Running `init_db` against the deployed DB requires no hand-set `LIK_DB_*` variables beyond AWS
  credentials — the target is resolved from `terraform output`.
- None of the three workflows contains a hardcoded `/ik-arch/prod`, `lik-prod-db`, or `likuidb`;
  each reads them from the bundle.
- Changing (hypothetically) the SSM prefix or DB instance name in Terraform requires no other
  edit; the next `init_db`/workflow run picks it up.
- There is no code path where `SSM_PREFIX` and `DB_INSTANCE` can resolve to different values.
- The only GitHub Actions `vars.*` remaining are the AWS-auth bootstrap (role ARN + region); no
  GitHub secrets are used beyond `GITHUB_TOKEN`.

## Dependencies / Assumptions

- Consumers can run `terraform output` at call time: Terraform backend initialized and AWS
  credentials present. True for anyone already running `terraform` or `init_db` against AWS; the
  CI workflows already assume AWS access via OIDC.
- The DB master password already tracks `SSM_PREFIX`
  (`$SSM_PREFIX/shared/DB_MASTER_PASSWORD`), so it follows the bundle for free once the prefix is
  sourced from it.

## Open questions for planning (/ce-plan)

- **Consumption ergonomics:** does `init_db` shell out to `terraform output` itself, or does a thin
  wrapper export the bundle into the `LIK_`-prefixed env vars `settings.py` already reads? The
  latter keeps `init_db` unaware of Terraform.
- **Bundle shape:** a single `output "env_config"` map vs. individual named outputs; JSON vs. shell
  `eval`-able form.
- **Which values belong in the bundle** beyond the four named (e.g. role ARN, sslmode)?
- **Runbook rewrite:** the deploy runbook's hand-set incantations should be replaced with the
  `terraform output`-driven flow.

## Related

- PR #45 (session auto-delete) introduced the `SSM_PREFIX` variable + `/ik-arch/prod` default, and
  the `prune-sessions.yml` cron that connects to the prod DB directly.
- PR #46 made `prune-sessions.yml` discover host/port/user from the `lik-prod-db` Lightsail instance
  (hardcoded), and hardcode `LIK_UI_DB_NAME=likuidb`.
- PR #44 (shared-key consolidation) and `infra/iam_github_oidc.tf` (SSM-read role ARNs hardcode
  `/ik-arch/prod`; left as-is under the single-environment non-goal, but noted as the place a future
  second environment would touch).
