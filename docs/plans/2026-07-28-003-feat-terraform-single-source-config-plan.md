---
title: "feat: Terraform as single source of environment config"
type: feat
status: completed
date: 2026-07-28
origin: docs/brainstorms/2026-07-28-terraform-as-single-source-of-config-requirements.md
---

# feat: Terraform as single source of environment config

## Summary

Make Terraform the single source of environment config and have every consumer read it live at
run time, so scattered hardcoded copies (`DB_INSTANCE`, `LIK_UI_DB_NAME`) and hand-assembled
`LIK_DB_*` incantations go away. CI reads Terraform-authored non-secret SSM **String** parameters
via the `aws ssm get-parameter` call it already makes; the developer CLI (`init_db`) reads a new
Terraform **output** bundle. The split keeps the least-privilege `github_ssm_read` CI role away
from Terraform state (which holds ~15 secrets in plaintext).

---

## Problem Frame

Environment-identifying config is copied across CI workflows, Terraform, and CLI tooling, and each
copy is one more value the next developer must set or keep in sync. The concrete pain: `DB_INSTANCE`
and `LIK_UI_DB_NAME` are hardcoded in `.github/workflows/prune-sessions.yml` yet also defined in
Terraform, and `init_db` requires hand-set `LIK_DB_*` variables the deploy runbook spells out as
long incantations. See origin for the full framing (Sources & References).

---

## Requirements

- R1. Terraform is the single authoritative definition of each environment-config value; no value
  is duplicated in a form that can drift. (origin R1, R6)
- R2. CI workflows read the config they need live at run time, without gaining access to Terraform
  state. (origin R1, R4, R7)
- R3. `prune-sessions.yml` resolves its full DB target (`DB_INSTANCE`, `LIK_UI_DB_NAME`) from the
  Terraform-authored source, together, in the same fetch step. (origin R4)
- R4. A failed or partial resolution fails loudly rather than falling back to a hardcoded default
  or a mismatched target. (origin R5)
- R5. `init_db` targets the deployed DB without the caller hand-assembling `LIK_DB_*` — the
  connection config comes from `terraform output` (+ SSM for the password). (origin R2)
- R6. GitHub Actions stores only the AWS-auth bootstrap it cannot derive after auth; no new GitHub
  secrets; no hardcoded `/ik-arch/prod`, `lik-prod-db`, or `likuidb` left in a workflow body.
  (origin R7, success criteria)

**Origin acceptance-style criteria:** running under `prod` reproduces today's exact behavior with
no hardcoded `prod`/`lik-prod-db`/`likuidb` in workflow bodies; `SSM_PREFIX` and `DB_INSTANCE`
cannot resolve to different environments.

---

## Scope Boundaries

- **Not** adding a second environment (staging): no workspaces, no per-environment backend keys,
  no re-scoping the CI role's `/ik-arch/prod/*` ARNs beyond adding the `/config/*` read. Single
  Terraform state stays as-is. (origin non-goal)
- **Not** changing what the values *are* — only where they are read from.
- **Not** touching the app's `LIK_UI_ENV` runtime mode.
- **Not** consolidating the three CI role ARNs (`AWS_SSM_READ_ROLE_ARN`, `AWS_DEPLOY_ROLE_ARN`,
  `AWS_APPLY_ROLE_ARN`) — orthogonal role-hygiene work.

### Deferred to Follow-Up Work

- Splitting the shared `github_ssm_read` role so deploy-agents/deploy-skills don't carry the DB
  password read (already a `TODO` in `lik-ui/README.md`): separate PR.

---

## Context & Research

### Relevant Code and Patterns

- `infra/ssm.tf` — Terraform **reads** secrets via `data "aws_ssm_parameter"` (values land in
  state); `infra/database.tf` **authors** `aws_ssm_parameter.db_master_password` (String→SecureString
  pattern to mirror for the new String config params).
- `infra/outputs.tf` — existing output style (`db_endpoint` is a `{host, port}` map; role-ARN
  outputs). The new `env_config` bundle follows the same shape.
- `infra/iam_github_oidc.tf` — `data.aws_iam_policy_document.ssm_read` grants `ssm:GetParameter`
  on two named params only; **no S3/state access by design** (comment: "still cannot run
  terraform"). The `/config/*` read is added here.
- `.github/workflows/prune-sessions.yml` — already discovers DB host/port/user from Lightsail at
  run time and fetches secrets from SSM; the "Fetch secrets from SSM" step is where config reads
  are added. `deploy-agents.yml` / `deploy-skills.yml` consume only `SSM_PREFIX`.
- `lik-mcp/scripts/init_db.py` — reads `lik_mcp.settings` (`LIK_`-prefixed); stays unaware of
  Terraform (config is exported into its env by a wrapper/documented step).
- `docs/deploy-runbook.md` — carries the hand-set `LIK_DB_*` incantations to replace.

### Institutional Learnings

- No `docs/solutions/` entries specific to this; conventions drawn from the infra files above.

### Key facts established during planning

- Terraform remote state (`ik-arch-tfstate-.../ik-arch/prod/terraform.tfstate`) contains ~15
  secrets in plaintext (all `data "aws_ssm_parameter"` values + `random_password.db_master`). This
  is why the CI read path must not require state access.

---

## Key Technical Decisions

- **Split read path by consumer.** CI reads Terraform-authored SSM **String** params
  (`${ssm_prefix}/config/*`) via existing `get-parameter`; developer CLI reads a Terraform
  **output** bundle. Both are Terraform-sourced, live, and drift-free. Rationale: `terraform
  output` needs S3 state read, and state holds every secret — routing CI through it would escalate
  the least-privilege `github_ssm_read` role from 2 secrets to the whole secret store. (see origin
  decision + planning Q below)
- **Config SSM params are `String`, not `SecureString`.** They are non-secret
  (instance name, db name); String keeps them cheap and readable and avoids KMS concerns.
- **Config param values reference Terraform resource attributes / vars**, never re-typed literals:
  `DB_INSTANCE` = `aws_lightsail_database.main.relational_database_name`, `LIK_UI_DB_NAME` =
  `var.db_ui_database_name`. This is what makes Terraform the single source (R1).
- **`SSM_PREFIX` becomes a bootstrap GitHub variable** (set once per environment, like
  `AWS_REGION`), not an inline `|| '/ik-arch/prod'` default. It is the *address* of the config, so
  it cannot be read from the config — same class as region and role ARN. (resolves origin R3's
  literal wording; see Open Questions)

---

## Open Questions

### Resolved During Planning

- *How does CI read Terraform config without state access?* → Terraform authors non-secret
  `String` SSM params under `${ssm_prefix}/config/`; CI reads them with existing SSM access. (user-
  confirmed: split path)
- *Origin R3 said "derive SSM_PREFIX from the bundle."* → Infeasible/circular for the SSM channel
  (the prefix is the bundle's address). Resolved by making `SSM_PREFIX` a required bootstrap GitHub
  variable with no inline default, alongside `AWS_REGION` and the role ARN.
- *Does `init_db` shell out to Terraform, or does a wrapper export env vars?* → Wrapper/documented
  step exports `LIK_DB_*` from `terraform output`; `init_db.py` stays Terraform-unaware (keeps the
  script portable to any config source).

### Deferred to Implementation

- Exact `env_config` output field set beyond the core (host, port, user, db names, instance,
  ssm_prefix, region) — add fields only as `init_db`'s wrapper actually needs them.
- Whether the `init_db` helper is a committed `scripts/*.sh` wrapper or a documented
  `eval "$(terraform -chdir=infra output ...)"` snippet — decide when wiring it; both keep
  `init_db.py` unchanged.

---

## Implementation Units

- U1. **Terraform publishes environment config (output bundle + CI String params)**

**Goal:** Make Terraform emit the config every consumer needs — a non-sensitive `env_config`
output for the CLI, and `String` SSM params under `${ssm_prefix}/config/` for CI.

**Requirements:** R1, R2

**Dependencies:** None

**Files:**
- Modify: `infra/outputs.tf` (add `env_config` output map)
- Create: `infra/config.tf` (new `aws_ssm_parameter` String resources for `DB_INSTANCE`,
  `LIK_UI_DB_NAME` under `${var.ssm_prefix}/config/`) — or add to `infra/ssm.tf`

**Approach:**
- `env_config` output = map of `{ ssm_prefix, region, db_instance, db_mcp_name, db_ui_name,
  db_user, db_host, db_port }`, values sourced from resource attributes / vars (not literals).
- Config params: `${var.ssm_prefix}/config/DB_INSTANCE` =
  `aws_lightsail_database.main.relational_database_name`; `${var.ssm_prefix}/config/LIK_UI_DB_NAME`
  = `var.db_ui_database_name`. Mirror the `aws_ssm_parameter` style in `database.tf`.

**Patterns to follow:** `infra/outputs.tf` `db_endpoint` map output; `infra/database.tf`
`aws_ssm_parameter.db_master_password`.

**Test scenarios:**
- Test expectation: none (infrastructure config) — verified via `terraform plan`.

**Verification:** `terraform plan` shows exactly the new `env_config` output and two new `String`
params added, and **no** changes to existing resources; `terraform apply` then makes
`terraform -chdir=infra output env_config` return the populated map and both `/config/*` params
readable via `aws ssm get-parameter`.

---

- U2. **Grant the CI SSM-read role access to the config params**

**Goal:** Let `github_ssm_read` read `${ssm_prefix}/config/*` without gaining any state or
broader access.

**Requirements:** R2, R6

**Dependencies:** U1 (param path must be defined)

**Files:**
- Modify: `infra/iam_github_oidc.tf` (`data.aws_iam_policy_document.ssm_read`,
  `SharedSecretsRead` statement)

**Approach:**
- Add `arn:aws:ssm:${var.aws_region}:293033346213:parameter/ik-arch/prod/config/*` to the
  statement's `resources`. No new statements, no S3, no `terraform`-capable actions.

**Patterns to follow:** existing `SharedSecretsRead` resource list in the same file.

**Test scenarios:**
- Test expectation: none (IAM policy) — verified via `terraform plan` + a live `get-parameter`
  check under the assumed role.

**Verification:** `terraform plan` shows only the policy's resource-list growing by the `/config/*`
ARN; after apply, an assumed-role `aws ssm get-parameter --name $SSM_PREFIX/config/DB_INSTANCE`
succeeds while `aws s3 ls s3://ik-arch-tfstate-293033346213` still fails (state remains
unreachable).

---

- U3. **`prune-sessions.yml` reads its DB target from SSM config**

**Goal:** Remove the hardcoded `DB_INSTANCE` and `LIK_UI_DB_NAME` from the workflow; read both
from `${SSM_PREFIX}/config/*` in the existing SSM fetch step, together.

**Requirements:** R3, R4, R6

**Dependencies:** U1, U2

**Files:**
- Modify: `.github/workflows/prune-sessions.yml`

**Approach:**
- Delete `DB_INSTANCE:` and `LIK_UI_DB_NAME:` from the job `env:` block and the header comment
  that documents them as hardcoded.
- In "Fetch secrets from SSM" (rename to "Fetch config + secrets from SSM"), add
  `get-parameter` calls for `$SSM_PREFIX/config/DB_INSTANCE` and `$SSM_PREFIX/config/LIK_UI_DB_NAME`,
  writing `DB_INSTANCE=…` and `LIK_UI_DB_NAME=…` to `$GITHUB_ENV` so the later Lightsail-discovery
  and prune steps consume them unchanged.
- Keep the existing "could not resolve endpoint" guard; a failed `get-parameter` already exits
  non-zero (fail-loud).

**Patterns to follow:** the existing secret-fetch step in the same workflow (mask + `>> $GITHUB_ENV`).

**Test scenarios:**
- Happy path: a `workflow_dispatch` run resolves `DB_INSTANCE=lik-prod-db` and
  `LIK_UI_DB_NAME=likuidb` from SSM, then prunes exactly as before.
- Error path: if `$SSM_PREFIX/config/DB_INSTANCE` is missing, the fetch step exits non-zero and the
  failure-issue step opens a tracking issue (no silent fallback, no wrong-DB connection).

**Verification:** a manual `workflow_dispatch` run completes with no `DB_INSTANCE`/`LIK_UI_DB_NAME`
literals in the workflow file and the same pruning outcome as today.

---

- U4. **Make `SSM_PREFIX` a bootstrap variable across the three workflows**

**Goal:** Remove the inline `|| '/ik-arch/prod'` default so the prefix has a single source (a
per-environment GitHub variable), satisfying "no hardcoded `/ik-arch/prod` in a workflow body."

**Requirements:** R6

**Dependencies:** None (independent of U1–U3, but see sequencing note in Risks)

**Files:**
- Modify: `.github/workflows/prune-sessions.yml`, `.github/workflows/deploy-agents.yml`,
  `.github/workflows/deploy-skills.yml`

**Approach:**
- Change `SSM_PREFIX: ${{ vars.SSM_PREFIX || '/ik-arch/prod' }}` to `SSM_PREFIX: ${{
  vars.SSM_PREFIX }}` in all three.
- Update each header comment: `SSM_PREFIX` is now a **required** `prod`-environment variable
  (bootstrap tier, alongside `AWS_REGION` and the role ARN), not optional.

**Patterns to follow:** the existing `AWS_REGION` / role-ARN `vars.*` usage in the same files.

**Test scenarios:**
- Happy path: with `SSM_PREFIX` set on the `prod` environment, all three workflows resolve the
  prefix and behave as today.
- Edge case: if `SSM_PREFIX` is unset, the `get-parameter` path becomes `/shared/...` (empty
  prefix) and fails loudly rather than silently hitting the wrong tree — acceptable fail-fast, but
  the runbook must call out setting the variable.

**Verification:** no `'/ik-arch/prod'` literal remains in any of the three workflow bodies; a
`workflow_dispatch` run of each succeeds with the variable set.

---

- U5. **`init_db` connection config from `terraform output` (+ runbook rewrite)**

**Goal:** Let a developer run `init_db` against the deployed DB without hand-assembling `LIK_DB_*`
— source the connection config from `terraform output env_config` and the password from SSM.

**Requirements:** R5, R1

**Dependencies:** U1 (`env_config` output)

**Files:**
- Create: `lik-mcp/scripts/db_env_from_terraform.sh` (thin `eval`-able helper) *or* document an
  inline snippet — decide at implementation (see Deferred)
- Modify: `docs/deploy-runbook.md` (replace hand-set `LIK_DB_*` incantations with the
  `terraform output`-driven flow)
- (No change to `lik-mcp/scripts/init_db.py` — it stays Terraform-unaware.)

**Approach:**
- Helper reads `terraform -chdir=infra output -json env_config`, exports `LIK_DB_HOST/PORT/USER`
  and the target `LIK_DB_NAME` (mcp vs ui) into the env, and fetches `LIK_DB_PASSWORD` from
  `$ssm_prefix/shared/DB_MASTER_PASSWORD` via `aws ssm get-parameter`. Then `init_db.py` runs
  against the resolved settings unchanged.
- Runbook shows the one-liner replacing the current multi-variable incantation, for both the
  `likdb` (mcp) and `likuidb` (ui) init steps.

**Execution note:** Verify end-to-end against a local Postgres before documenting as the canonical
flow — a broken helper silently reintroduces hand-set vars.

**Patterns to follow:** existing SSM fetch in `prune-sessions.yml`; the runbook's current
`init_db.py --ssm-prefix` invocation.

**Test scenarios:**
- Happy path: with AWS creds present, the helper populates `LIK_DB_*` from `terraform output` and
  `init_db.py` connects and applies the idempotent schema (reports the expected tables).
- Error path: with no AWS creds / missing output, the helper fails loudly (non-zero) rather than
  running `init_db` against a half-populated or default connection.

**Verification:** `init_db` succeeds against the deployed DB after running only the helper — no
hand-set `LIK_DB_*` — and the runbook no longer lists them.

---

## System-Wide Impact

- **Interaction graph:** `terraform apply` now emits config to two channels (output + `/config/*`
  SSM params); `prune-sessions.yml` and `init_db` consume them. `deploy-agents`/`deploy-skills`
  change only in the `SSM_PREFIX` variable treatment (U4).
- **Error propagation:** all resolution paths fail loudly on a missing param/output (R4); no silent
  fallback to a hardcoded default after U3/U4.
- **State lifecycle risks:** none new — config params are String, non-secret; the DB password path
  is unchanged.
- **API surface parity:** the `/config/*` SSM namespace is a new, small public-within-account
  surface; the CI role's read scope grows by exactly that prefix and nothing else.
- **Unchanged invariants:** Terraform state access remains apply-role-only; `github_ssm_read` still
  cannot read state or run `terraform`; the app's runtime env injection is untouched.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| **Deploy ordering:** merging U3 before U1+U2 are applied to prod → next `prune` run can't read `/config/*` and fails. | Apply Terraform (U1, U2) to prod **before** merging the workflow change (U3). Sequence in the PR/rollout; the fail-loud behavior surfaces it as a tracking issue rather than a silent wrong-DB run. |
| **`SSM_PREFIX` unset after U4** → workflows resolve an empty-prefix path and fail. | Set `SSM_PREFIX` on the `prod` GitHub environment before/with merging U4; document as bootstrap in the runbook and workflow headers. |
| Applying U1/U2 to prod is a manual/gated `terraform apply`, not automatic on merge. | Call out the apply as an explicit rollout step; verify `terraform output env_config` + `/config/*` readability post-apply. |
| Widening the CI role, even to non-secret `/config/*`, is a security-surface change. | Scope strictly to `parameter/ik-arch/prod/config/*` (String, non-secret); confirm state stays unreachable (U2 verification). |

---

## Documentation / Operational Notes

- Rollout order: (1) apply U1+U2 to prod and verify; (2) set `SSM_PREFIX` prod env variable;
  (3) merge U3+U4; (4) wire/document U5.
- Update `docs/deploy-runbook.md` (U5) and the three workflow header comments (U3, U4).
- No prod DB schema change in this plan.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-28-terraform-as-single-source-of-config-requirements.md](docs/brainstorms/2026-07-28-terraform-as-single-source-of-config-requirements.md)
- Related code: `infra/outputs.tf`, `infra/ssm.tf`, `infra/database.tf`, `infra/iam_github_oidc.tf`,
  `.github/workflows/prune-sessions.yml`, `lik-mcp/scripts/init_db.py`, `docs/deploy-runbook.md`
- Related PRs: #45 (session auto-delete, introduced `SSM_PREFIX`), #46 (Lightsail DB discovery),
  #44 (shared-key consolidation)
