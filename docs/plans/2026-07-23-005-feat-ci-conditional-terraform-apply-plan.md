---
title: "feat: Gated terraform apply in the image-push CI workflow"
type: feat
status: active
date: 2026-07-23
---

# feat: Gated terraform apply in the image-push CI workflow

## Summary

Extend `.github/workflows/deploy-images.yml` so that, after building and pushing container
images, CI runs `terraform apply` automatically — but only when the plan is a clean image
swap (`Plan: 1 to add, 0 to change, 1 to destroy.` for a single service, or
`2 to add, 0 to change, 2 to destroy.` for both). Any other plan (config drift, or anything
with `to change`) falls through to a step-summary message telling the maintainer to run
`./tf.sh apply -var-file=prod.tfvars` locally so they can review it. This removes the manual
apply step for the common redeploy case while keeping a human in the loop for anything
non-routine.

---

## Problem Frame

Today CI ([.github/workflows/deploy-images.yml](.github/workflows/deploy-images.yml)) only
builds and pushes images; the maintainer must then run `./tf.sh apply -var-file=prod.tfvars`
locally to roll the new image into the running Lightsail deployment (see
[docs/deploy-runbook.md](docs/deploy-runbook.md) "Routine redeploy"). For a routine image bump
that apply is mechanical and predictable — its plan is always a single-service deployment-version
replacement. Automating just that predictable case saves a round-trip while still deferring any
surprising plan to manual review.

---

## Requirements

- R1. After a successful image push, CI runs `terraform plan` against the same infra config and
  the just-pushed image ref(s).
- R2. CI runs `terraform apply` automatically **only** when the plan summary is exactly one of
  the two clean-swap strings: `Plan: 1 to add, 0 to change, 1 to destroy.` or
  `Plan: 2 to add, 0 to change, 2 to destroy.` (both with `0 to change`).
- R3. For any other plan, CI does **not** apply; it writes a step-summary telling the maintainer
  to run `./tf.sh apply -var-file=prod.tfvars` locally, echoing the new image ref(s) to paste in.
- R4. A single-service build (`service: lik-mcp` or `lik-ui`) must still supply **both** image
  refs to terraform, so it never destroys the other service's deployment.
- R5. The CI credentials used for apply are least-privilege and separate from the image-push role.
- R6. No secrets or gitignored files are required on the runner (`prod.tfvars` is gitignored and
  absent in CI).

---

## Scope Boundaries

- Not changing the trigger: the workflow stays `workflow_dispatch` (manual), not push-triggered.
- Not adding a "plan-only / dry-run" input toggle — out of scope for this pass.
- Not moving the local `tf.sh` flow off the maintainer's machine; local apply remains the
  fallback and the tool for non-routine changes.
- Not storing custom-domain URLs in GitHub environment variables — they are hardcoded in the
  workflow for now (single deployment environment). See Key Technical Decisions.
- Not automating the one-time IAM-role bootstrap; that is a manual local apply (see Prerequisites).

### Deferred to Follow-Up Work

- Multi-environment support (staging/prod split) that would force the hardcoded domain URLs and
  region back out into per-environment GitHub variables: future iteration, only when a second
  environment exists.

---

## Context & Research

### Relevant Code and Patterns

- [.github/workflows/deploy-images.yml](.github/workflows/deploy-images.yml) — existing `push`
  matrix job. Uses GitHub OIDC via `aws-actions/configure-aws-credentials@v6`, `environment: prod`,
  and `vars.AWS_DEPLOY_ROLE_ARN` / `vars.AWS_REGION`. The push step already parses and prints the
  `:svc.app.N` ref to `$GITHUB_STEP_SUMMARY`.
- [infra/iam_github_oidc.tf](infra/iam_github_oidc.tf) — existing OIDC provider, the reusable
  `github_trust` policy document (trust is keyed to
  `repo:navapbc/leverage-inst-knowl:environment:prod`), and the image-push role
  `github-actions-lik-image-push` scoped to 4 Lightsail actions. The header comment explicitly
  names "escalating this role to run apply in CI" as deferred work — this plan does that as a
  **separate** role, not by widening the push role.
- [infra/lik_mcp.tf](infra/lik_mcp.tf#L40) / [infra/lik_ui.tf](infra/lik_ui.tf#L40) — the
  `aws_lightsail_container_service_deployment_version` resources are `count`-guarded on the image
  var (`count = var.lik_*_image == "" ? 0 : 1`). An empty image var **destroys** that service's
  deployment. `image` is immutable, so a ref change forces replace → the plan reads
  `1 to add, 0 to change, 1 to destroy` per changed service (the empirical source of R2's string).
- [infra/lik_ui.tf](infra/lik_ui.tf#L29) — the `public_domain_names` block is `for_each`-guarded on
  the custom-domain var; an empty domain var detaches the live custom domain. So the apply must
  pass the domain URLs too (Key Technical Decisions).
- [infra/backend.tf](infra/backend.tf) — S3 backend with native `use_lockfile = true` (no
  DynamoDB). Apply needs S3 object RW on `ik-arch/prod/*` for state + the `.tflock` object.
- [infra/tf.sh](infra/tf.sh) — local wrapper that mints creds from the `lik` SSO profile; **not**
  usable in CI. CI calls `terraform` directly against the OIDC-assumed role.
- [infra/prod.tfvars](infra/prod.tfvars) / [infra/prod.tfvars.example](infra/prod.tfvars.example)
  — `*.tfvars` is gitignored (confirmed via `git check-ignore`), so CI cannot read `prod.tfvars`.
  CI must reconstruct every non-default var (both image refs + both domain URLs) itself.

### Institutional Learnings

- [docs/deploy-runbook.md](docs/deploy-runbook.md) — "Routine redeploy" (line ~392) is the flow
  being automated; "Bootstrap the state bucket" and the image-push prerequisites (line ~252) are
  the model for the new role's setup. `main` is **not** branch-protected (verified via the GitHub
  API), though this plan does not need CI to push commits.

### External References

- None. This is CI + IAM plumbing following patterns already present in the repo; no external
  research warranted (the OIDC + Lightsail patterns are well-established locally).

---

## Key Technical Decisions

- **Separate apply role, not a widened push role**: add `github-actions-lik-apply` reusing the
  existing `github_trust` document. Keeps the push job's blast radius unchanged and gives the apply
  role its own least-privilege policy. Rationale: R5, and the existing header comment's intent.
- **Hardcode the two custom-domain URLs in the workflow** (`https://ui.lik.navapbc.com`,
  `https://mcp.lik.navapbc.com`): per user instruction — there is only one deployment environment,
  so environment-variable indirection adds setup cost with no current payoff. Revisit if a second
  environment appears (see Deferred to Follow-Up Work).
- **Resolve both image refs on every apply**: for each service, use the just-pushed ref if that
  service was built this run, else fetch the currently-deployed ref from Lightsail
  (`aws lightsail get-container-services --service-name <svc>`, reading the current deployment's
  container image). Both refs are always passed as `-var`, satisfying R4 and never tripping the
  `count=0` destroy. **Execution-time verification needed**: confirm `get-container-services`
  returns the ref in `:svc.app.N` form (not a resolved digest); if it does not, fall back to
  reading it from `terraform state show` post-init. Flagged in Open Questions.
- **Pass refs between jobs via artifacts, not matrix outputs**: matrix jobs can't set distinct
  named job outputs without collision. The `push` job writes `:svc.app.N` to a per-service file and
  uploads it as an artifact; the `apply` job downloads all artifacts and reads whichever exist.
- **Gate on the exact plan-summary string** parsed from `terraform plan` stdout, accepting the two
  clean-swap forms in R2. Implemented by capturing `terraform plan` output and grepping for the
  literal summary line. Anything else → no apply, R3 message. Using `-out=tfplan` + `terraform apply
  tfplan` guarantees the applied plan is exactly the one that was gated (no TOCTOU re-plan).
- **`terraform apply` never runs when the gate fails** — the job does not fall back to an
  unattended apply of a dirty plan under any condition.

---

## Open Questions

### Resolved During Planning

- Where does apply run? → In CI, in a new `apply` job (user decision).
- How are domain URLs supplied? → Hardcoded in the workflow (user decision).
- Does `main` branch protection block anything? → No; `main` is unprotected, and this plan does
  not require CI to push commits anyway.

### Deferred to Implementation

- Exact `aws lightsail get-container-services` JMESPath to extract the current image ref, and
  whether it returns `:svc.app.N` or a resolved form — verify against the live service during
  implementation; fall back to `terraform state show` if needed (see Key Technical Decisions).
- Exact IAM action list for the refresh phase (terraform reads IAM/SSM/Lightsail/RDS during plan) —
  start from the enumerated set in U1's Approach and tighten against a real `terraform plan` run
  under the new role, widening only where plan fails with AccessDenied.
- Whether reading the SecureString SSM params (`db_master_password`, etc.) needs an explicit
  `kms:Decrypt` statement or is covered by the AWS-managed `alias/aws/ssm` key's default policy —
  determine from the first plan run.

---

## Implementation Units

- U1. **Add the `github-actions-lik-apply` IAM role**

**Goal:** A least-privilege role CI can assume to run `terraform plan`/`apply`, separate from the
image-push role.

**Requirements:** R5

**Dependencies:** None

**Files:**
- Modify: `infra/iam_github_oidc.tf` (new `aws_iam_role.github_apply` + `aws_iam_role_policy`,
  reusing `data.aws_iam_policy_document.github_trust`)
- Modify: `infra/outputs.tf` (new output `github_apply_role_arn`)

**Approach:**
- New role trusts the same OIDC subject as the push role (reuse `github_trust`).
- Policy statements (tighten during implementation per Open Questions):
  - S3: `GetObject`/`PutObject`/`DeleteObject`/`ListBucket` on
    `arn:aws:s3:::ik-arch-tfstate-293033346213` + `.../ik-arch/prod/*` (state + `.tflock`).
  - SSM: `GetParameter`/`GetParameters` on
    `arn:aws:ssm:us-east-1:293033346213:parameter/ik-arch/prod/*` (+ `kms:Decrypt` on the SSM key
    only if the first plan run shows it is needed).
  - Lightsail (read + the one write): `GetContainerServices`, `GetContainerServiceDeployments`,
    `GetContainerImages`, `GetRelationalDatabase*`, and `CreateContainerServiceDeployment` — all
    `Resource: "*"` (Lightsail has no resource-level ARNs, matching the existing policy's note).
  - IAM read for refresh of the OIDC resources: `GetRole`/`GetRolePolicy`/`ListRolePolicies`/
    `GetOpenIDConnectProvider`, scoped to the two role ARNs + provider ARN.

**Patterns to follow:**
- The existing `aws_iam_role.github_image_push` + `data.aws_iam_policy_document.image_push` +
  `aws_iam_role_policy.image_push` triple in [infra/iam_github_oidc.tf](infra/iam_github_oidc.tf).
- Output shape mirrors `github_image_push_role_arn` in [infra/outputs.tf](infra/outputs.tf).

**Test scenarios:**
- Test expectation: none — infrastructure declaration. Verified by `terraform plan`/`apply` (see
  Verification), not unit tests.

**Verification:**
- `./tf.sh plan` shows the new role + policy + output as adds, and nothing destroyed.
- After `./tf.sh apply`, `./tf.sh output github_apply_role_arn` prints the ARN.

---

- U2. **`push` job publishes each image ref as an artifact**

**Goal:** Make the just-pushed `:svc.app.N` refs available to a downstream job.

**Requirements:** R1, R4

**Dependencies:** None (independent of U1)

**Files:**
- Modify: `.github/workflows/deploy-images.yml` (the `push` job's "Push to Lightsail registry"
  step + a new upload step)

**Approach:**
- Reuse the existing `ref=$(... grep -oE ...)` parse. Write `$ref` to a file named for the service
  (e.g. `image-ref/${{ matrix.name }}.txt`).
- Add `actions/upload-artifact@v4` with a per-service artifact name (guarded by the same
  `steps.gate.outputs.skip != 'true'` condition so a skipped service uploads nothing).
- Keep the existing `$GITHUB_STEP_SUMMARY` block (R3 relies on the ref being visible).

**Patterns to follow:**
- The existing gate-conditioned steps in the same job.

**Test scenarios:**
- Test expectation: none — CI config. Behavioral proof is the end-to-end workflow run in
  Verification.

**Verification:**
- A manual run with `service: lik-mcp` produces exactly one `image-ref` artifact; `service: both`
  produces two.

---

- U3. **Add the gated `apply` job**

**Goal:** After push, plan against the resolved refs and auto-apply only on a clean image swap;
otherwise print the manual-apply message.

**Requirements:** R1, R2, R3, R4, R6

**Dependencies:** U1 (role must exist and be applied), U2 (artifacts)

**Files:**
- Modify: `.github/workflows/deploy-images.yml` (new `apply` job)

**Approach:**
- Job header: `needs: push`, `environment: prod`, `runs-on: ubuntu-latest`, single (no matrix),
  `permissions: id-token: write, contents: read`.
- Steps:
  1. `actions/checkout@v6`.
  2. `configure-aws-credentials@v6` with `role-to-assume: ${{ vars.AWS_APPLY_ROLE_ARN }}`,
     `aws-region: ${{ vars.AWS_REGION }}`.
  3. `hashicorp/setup-terraform@v3` (pin the version to match `required_version >= 1.10`;
     `terraform_wrapper: false` so stdout is clean for parsing).
  4. `actions/download-artifact@v4` (all artifacts).
  5. Resolve refs (shell): for each of `lik-mcp` / `lik-ui`, `MCP_REF`/`UI_REF` = artifact file if
     present, else `aws lightsail get-container-services --region "$AWS_REGION"
     --service-name <svc>-prod --query <current-deployment image>`. Fail the job loudly if either
     resolves empty (guards R4's destroy footgun).
  6. `terraform -chdir=infra init`.
  7. `terraform -chdir=infra plan -out=tfplan` with
     `-var lik_mcp_image=$MCP_REF -var lik_ui_image=$UI_REF`
     `-var mcp_custom_domain_url=https://mcp.lik.navapbc.com`
     `-var ui_custom_domain_url=https://ui.lik.navapbc.com`; tee stdout to a file.
  8. Parse the summary line. If it equals `Plan: 1 to add, 0 to change, 1 to destroy.` **or**
     `Plan: 2 to add, 0 to change, 2 to destroy.` → `terraform -chdir=infra apply tfplan` and write
     a "Deployed" step summary. Else → write the R3 message (run `./tf.sh apply
     -var-file=prod.tfvars` locally) plus the new ref(s), and exit 0 (a declined apply is not a
     failure).

**Technical design:** *(directional guidance for review, not implementation specification)*

```
push (matrix) ──uploads──> image-ref/lik-mcp.txt, image-ref/lik-ui.txt
      │
      ▼  needs: push
apply job:
  resolve MCP_REF, UI_REF   (artifact ?? lightsail get-container-services)
  terraform plan -out=tfplan  (both image vars + both hardcoded domain vars)
  summary := last "Plan: ..." line
  if summary ∈ { "1 to add,0 change,1 destroy", "2 to add,0 change,2 destroy" }:
        terraform apply tfplan            # exact gated plan, no re-plan
  else: step-summary → "run ./tf.sh apply -var-file=prod.tfvars locally" + echo refs
```

**Patterns to follow:**
- OIDC + `environment: prod` + `vars.*` usage from the existing `push` job.

**Test scenarios:**
- Happy path (single): manual run `service: lik-ui` → plan is `1 to add, 0 to change, 1 to
  destroy.` → apply runs → lik-ui rolls to the new image; lik-mcp untouched (its ref was resolved
  from Lightsail and matched state).
- Happy path (both): `service: both` → plan is `2 to add, 0 to change, 2 to destroy.` → apply runs.
- Gate-decline (drift): run when an SSM value or domain changed so the plan includes `to change` →
  job does **not** apply, step summary shows the manual command + refs, job succeeds (exit 0).
- Edge / footgun: a service's ref resolves empty → job fails loudly before any plan/apply (must
  never proceed with an empty image var, which would destroy a deployment — R4).
- Edge: `service: lik-mcp` only → lik-ui ref comes from Lightsail, both vars non-empty, plan is a
  single-service swap.

**Verification:**
- Trigger the workflow for one service; confirm the run applies and the container rolls (health
  check green per [docs/deploy-runbook.md](docs/deploy-runbook.md) "Verify").
- Trigger a run that produces drift; confirm no apply and the manual-command summary appears.

---

- U4. **Document the automated path and the one-time setup**

**Goal:** Keep the runbook truthful about what CI now does and record the prerequisites.

**Requirements:** R3 (discoverability of the fallback), R5

**Dependencies:** U1, U3

**Files:**
- Modify: `docs/deploy-runbook.md` ("Routine redeploy" + a new short "CI auto-apply" note and the
  bootstrap/`AWS_APPLY_ROLE_ARN` prerequisite)
- Modify: `.github/workflows/deploy-images.yml` (update the top-of-file comment block, which
  currently says the workflow "does NOT deploy")

**Approach:**
- Document: the apply role bootstrap (one local `./tf.sh apply` to create it), setting the
  `AWS_APPLY_ROLE_ARN` repo/prod variable to the new output, the gate semantics, and the manual
  fallback for declined plans.

**Test scenarios:**
- Test expectation: none — docs/comments.

**Verification:**
- The workflow header no longer claims it never deploys; the runbook's redeploy section reflects
  auto-apply + fallback.

---

## System-Wide Impact

- **Interaction graph:** New `apply` job depends on `push`. No change to the push job's behavior
  beyond an added artifact upload.
- **Error propagation:** Ref-resolution failure and plan failure must fail the job; a *declined*
  apply (gate not met) is a success with an advisory summary — these two outcomes must be
  distinguishable in the run status.
- **State lifecycle risks:** S3 native lockfile — two concurrent applies would collide. The apply
  job is single (no matrix) and `needs: push`, so only one apply per run. Concurrent *workflow*
  runs are still possible; consider `concurrency:` on the workflow if that becomes real (noted, not
  required now).
- **API surface parity:** The gate string is provider-version-sensitive — if the AWS provider ever
  changes how a deployment-version replace is summarized, the gate silently stops matching and
  everything routes to manual (safe-fail). Called out in the runbook.
- **Unchanged invariants:** The image-push role and the local `tf.sh` flow are unchanged; local
  apply remains fully functional and is still the tool for non-routine changes.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Empty image var destroys a deployment (R4 footgun) | Resolve both refs; fail loudly if either is empty; never apply on empty. |
| `get-container-services` returns a non-`:svc.app.N` image form | Execution-time verification; fall back to `terraform state show`. |
| Apply role too narrow → plan/apply AccessDenied | Start from the enumerated action set, widen against a real plan run under the role. |
| Gate string drifts with a provider upgrade | Safe-fail: unmatched plans route to manual, never to an unattended dirty apply. |
| Concurrent workflow runs collide on state lock | Single apply per run; add workflow `concurrency:` if it becomes a real problem. |

---

## Prerequisites (one-time, manual — done by the maintainer)

1. **Bootstrap the role:** after U1 lands, run `cd infra && ./tf.sh apply -var-file=prod.tfvars`
   locally once to create `github-actions-lik-apply` (chicken-and-egg: CI can't assume a role that
   doesn't exist yet).
2. **Set the CI variable:** add repo/`prod`-environment variable `AWS_APPLY_ROLE_ARN` =
   `./tf.sh output github_apply_role_arn`, alongside the existing `AWS_DEPLOY_ROLE_ARN` /
   `AWS_REGION`.

---

## Sources & References

- Related code: [.github/workflows/deploy-images.yml](.github/workflows/deploy-images.yml),
  [infra/iam_github_oidc.tf](infra/iam_github_oidc.tf), [infra/lik_mcp.tf](infra/lik_mcp.tf),
  [infra/lik_ui.tf](infra/lik_ui.tf), [infra/backend.tf](infra/backend.tf),
  [infra/outputs.tf](infra/outputs.tf)
- Runbook: [docs/deploy-runbook.md](docs/deploy-runbook.md) ("Routine redeploy", bootstrap notes)
