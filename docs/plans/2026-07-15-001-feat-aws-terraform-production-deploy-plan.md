---
title: "feat: Production deployment to AWS via Terraform (Lightsail)"
type: feat
status: active
date: 2026-07-15
origin: docs/brainstorms/2026-07-15-01-aws-terraform-production-deploy-requirements.md
---

# feat: Production deployment to AWS via Terraform (Lightsail)

## Summary

Stand up a Terraform-managed production deployment in `us-east-1` for the two services `lik-mcp` and
`lik-ui`, each running on AWS Lightsail Container Service and backed by a new, empty Lightsail managed
Postgres. Terraform owns all AWS resources (DB, container services + deployments, SSM secret reads,
S3 state backend, GitHub-OIDC IAM role); a documented runbook owns the steps Terraform can't
declaratively own (CI image build+push, OAuth client registration under Nava org, schema
initialization). Secrets live in SSM Parameter Store and are injected as container env vars at apply
time. Public URLs start as the Lightsail-provided HTTPS URLs, with a documented custom-domain
migration path.

---

## Problem Frame

The code was validated on a throwaway onrender.com deployment and now needs a durable, reproducible
production home that a future maintainer can operate and rebuild from declarative configuration. The
containers are the easy part; the risk surface is secret hygiene, stable OAuth-anchoring URLs, an
internet-reachable managed DB, and a clean deploy sequence. Full product context lives in the origin
requirements doc (see Sources & References).

---

## Requirements

- R1. All AWS production resources — including the Lightsail Postgres — are created and maintained
  through Terraform with remote state in S3. (origin G1)
- R2. All production resources reside in `us-east-1`; the new DB starts empty with schema
  initialized; the existing `us-east-2` DB is not touched. (origin G1a, N1a, D0)
- R3. Both services run over HTTPS with real Google auth enforced (`LIK_ENV=prod` /
  `LIK_UI_ENV=prod`). (origin G2)
- R4. No secret value appears in git or plaintext `*.tf`/tfvars; SSM Parameter Store is the source of
  truth, injected as container env vars. (origin G3, D4)
- R5. A maintainer can deploy a new image and roll config forward via a written runbook with no
  undocumented console-only steps. (origin G4)
- R6. Reference documentation exists: architecture, resource inventory, runbook, secret inventory,
  custom-domain migration. (origin G5)
- R7. Production runs on new OAuth client registrations created under Nava org ownership; new
  ids/secrets stored in SSM. (origin G6, D8)
- R8. Image build+push runs in CI (GitHub Actions) so the bandwidth-heavy upload does not run from a
  maintainer's slow uplink; `terraform apply` stays a local maintainer step. (origin D6)
- R9. The DB is reached over its public endpoint with enforced TLS; residual internet-exposure risk
  is accepted for an internal low-traffic tool. (origin D2, D2a, Rejected-Alternative section)

**Origin decisions carried forward:** D0 (region), D1 (Lightsail Container Service), D2/D2a (new empty
Lightsail Postgres, public mode + TLS), D2b (schema init from shipped `db/init.sql`), D3 (Lightsail
default URLs first), D4 (SSM secrets), D5 (S3 state), D6 (CI build+push), D7 (single prod env), D8
(Nava-org OAuth).

---

## Scope Boundaries

- No RDS or non-Lightsail DB engine (origin N1).
- No data migration; no changes to any `us-east-2` resource (origin N1a).
- No multiple environments (single `prod`) (origin N3).
- No autoscaling / multi-node / HA (origin N4).
- No application code changes or new features (origin N5).

### Deferred to Follow-Up Work

- **Full auto-deploy** (`terraform apply` inside CI on merge): deferred (origin N2). Escalation path
  and effort captured in Open Questions → Deferred, and origin Q5.
- **Custom-domain migration** off the Lightsail default URLs: documented as a runbook procedure
  (U9), executed later.

---

## Context & Research

### Relevant Code and Patterns

- `lik-mcp/Dockerfile`, `lik-ui/Dockerfile` — the deploy artifacts; both force `LIK*_ENV=prod`,
  `HTTP_HOST=0.0.0.0`, streamable-http (mcp). One image per service, config supplied at runtime.
- `lik-mcp/src/lik_mcp/settings.py`, `lik-mcp/src/lik_mcp/__main__.py:31-35` — prod fail-closed guard:
  refuses to start unless `LIK_OAUTH_CLIENT_ID` and `LIK_RESOURCE_SERVER_URL` are set.
- `lik-ui/src/lik_ui/settings.py:116-136` (`require_production_config()`, called from `app.py:43`) —
  prod fail-closed guard: requires `LIK_UI_SESSION_SECRET`, `LIK_UI_APP_OAUTH_CLIENT_ID`,
  `LIK_UI_APP_OAUTH_CLIENT_SECRET`, `LIK_UI_ANTHROPIC_API_KEY`, `LIK_UI_AGENTS_CONFIG`.
- `lik-mcp/scripts/init_db.py` + `lik-mcp/db/init.sql` — idempotent schema init (tables `catalog`,
  `confirmations`; `pg_trgm` extension; writer/reader roles). Applied by running the script.
- `lik-ui/db/init.sql` — idempotent schema init (tables `users`, `user_vaults`, `sessions`,
  `dcr_registrations`). No init script; applied via `psql -f`. README: "The app never creates its own
  schema" (`lik-ui/README.md:39`).
- `lik-ui/src/lik_ui/app.py:67-69` — `GET /healthz` → 200 (unauthenticated). lik-mcp has no
  equivalent; only `/mcp`.
- `lik-mcp/src/lik_mcp/server.py:61-64` — `LIK_HTTP_ALLOWED_HOSTS` DNS-rebinding guard (enforced).
  `lik-ui`'s `LIK_UI_HTTP_ALLOWED_HOSTS` is declared but **not** currently wired to middleware.
- No existing Terraform anywhere in the repo — this is greenfield IaC.

### Institutional Learnings

- `docs/brainstorms/2026-07-06-01-lik-ui-managed-agent-app-requirements.md` and its plan — establish
  the OAuth-vault model and the cross-service URL equality constraints that this deploy must honor.

### External References

- Terraform AWS provider: `aws_lightsail_container_service`, `aws_lightsail_container_service_deployment_version`,
  `aws_lightsail_database`, `aws_ssm_parameter` (data source). Container-service `url` and DB
  `master_endpoint_address`/`_port` are exported attributes.
- Lightsail image ref format for pushed images: `:<service>.<label>.<version>` (leading colon);
  captured from `aws lightsail push-container-image` output and passed to TF as a variable.
- `rds.force_ssl` defaults to `1` on Lightsail Postgres **15+** (off on <15); settable only via CLI
  `update-relational-database-parameters`, not the TF resource.
- S3 backend native locking (`use_lockfile = true`, Terraform ≥ 1.10) replaces the DynamoDB lock
  table; requires bucket versioning.
- GitHub→AWS OIDC via `aws-actions/configure-aws-credentials` (v6) + IAM role with a tightly-scoped
  `sub` trust condition; no long-lived keys.
- SSM `aws_ssm_parameter` data source `.value` is sensitive in plan output but persists to state in
  plaintext → encrypted S3 state is the compensating control.

---

## Key Technical Decisions

- **DB engine version:** Pin a Lightsail Postgres **15+** blueprint so `rds.force_ssl=1` is the
  default — TLS enforced server-side with no manual parameter/reboot step (and avoids the "cannot
  modify default parameter group" bug). Client still connects with `sslmode=require`. Exact
  `blueprint_id`/`bundle_id` verified at build via `aws lightsail get-relational-database-blueprints`
  / `-bundles` (values change; don't hardcode blindly).
- **Image delivery:** Use `aws lightsail push-container-image` → Lightsail's own registry (not
  private ECR). Fewer resources (no ECR repo or puller role), and the slow-uplink problem is solved
  equally by running the push in CI. (Corrects an earlier assumption that private ECR was
  unsupported — it is supported, just not chosen.)
- **Deploy ordering resolves the OAuth URL dependency:** `aws_lightsail_container_service` exposes its
  public `url` at service creation, before any deployment version. Sequence: create both services →
  read URLs → register OAuth clients against those URLs → write ids/secrets to SSM → create the
  deployment versions that boot with real auth. No bootstrap deadlock.
- **lik-mcp health check:** point the public-endpoint health check at path `/mcp` with default
  `success_codes = 200-499` (a 401 from the auth layer counts as "alive"), since lik-mcp exposes no
  unauthenticated health route. lik-ui health check → `/healthz`.
- **Secret source of truth:** secrets are populated into SSM out-of-band (runbook/script:
  `aws ssm put-parameter --type SecureString`), and Terraform reads them via `aws_ssm_parameter` data
  sources — keeping values out of git and tfvars. The **DB master password** is the one exception: it
  is Terraform-generated (`random_password`, charset excluding `/ " @` per Lightsail rules) and
  written to SSM, so it lands in encrypted state.
- **State backend:** S3 with `use_lockfile = true` (no DynamoDB), `encrypt = true`, bucket versioning
  on. State is encrypted because SSM secret values land in it in plaintext.
- **SSM naming scheme:** `/ik-arch/prod/<service>/<VAR_NAME>` (e.g.
  `/ik-arch/prod/lik-ui/LIK_UI_SESSION_SECRET`). Resolves origin Q3.
- **TF ↔ runbook split (origin Q1):** Terraform owns every AWS resource. The runbook owns: CI image
  build+push, OAuth console registration, schema initialization, and (only if a <15 engine is ever
  used) the `rds.force_ssl` CLI step.

---

## Open Questions

### Resolved During Planning

- Q1 (TF vs runbook split): resolved — see Key Technical Decisions.
- Q2 (schema-init ownership): runbook step — lik-mcp via `scripts/init_db.py` run as the DB master
  user (needed for `pg_trgm` and role creation), lik-ui via `psql -f lik-ui/db/init.sql`. Neither app
  self-migrates.
- Q3 (SSM naming): `/ik-arch/prod/<service>/<VAR_NAME>`.
- Q4 (health check + logging): lik-ui `/healthz`; lik-mcp `/mcp` + `success_codes 200-499`. Container
  logs via Lightsail's built-in capture (`aws lightsail get-container-log`); no extra logging infra.

### Deferred to Implementation

- Exact `blueprint_id` / `bundle_id` for the Postgres instance — verified via CLI at build time
  (values are retired/added over time).
- Exact Lightsail container-service `power`/`scale` sizing — start smallest (`nano`/`micro`,
  `scale = 1`) and adjust if needed; not a plan-time decision.
- Full auto-deploy escalation (origin N2/Q5): GitHub OIDC role gains deploy+SSM+state scope; CI runs
  `terraform apply` threading the pushed image ref. ~half-to-full day; deferred.
- Whether `LIK_UI_HTTP_ALLOWED_HOSTS` should be wired into lik-ui middleware for parity — app-code
  change, out of this plan's scope (N5); noted for the app maintainers.

---

## Output Structure

    infra/                              # new top-level Terraform root (name TBD at build)
      backend.tf                        # S3 backend, use_lockfile
      providers.tf                      # aws provider, region us-east-1
      variables.tf                      # image refs, service sizing, SSM prefix
      database.tf                       # aws_lightsail_database + random_password + SSM write
      ssm.tf                            # aws_ssm_parameter data sources (secret reads)
      lik_mcp.tf                        # container service + deployment version
      lik_ui.tf                         # container service + deployment version
      iam_github_oidc.tf                # OIDC provider + CI role + scoped policy
      outputs.tf                        # service URLs, DB endpoint
      README.md                         # maintainer docs (or docs/ below)
    .github/workflows/
      deploy-images.yml                 # build + push to Lightsail registry (OIDC auth)
    docs/
      deploy-runbook.md                 # deploy sequence, OAuth registration, schema init, migration

The tree is a scope declaration, not a constraint; the implementer may adjust layout.

---

## Implementation Units

Grouped into four phases. Units are dependency-ordered; U-IDs are stable.

### Phase 1 — Terraform foundation

- U1. **Terraform root + S3 state backend**

**Goal:** Establish the Terraform root module, the `us-east-1` AWS provider, and an encrypted,
versioned S3 state backend with native locking.

**Requirements:** R1, R2

**Dependencies:** None

**Files:**
- Create: `infra/backend.tf`, `infra/providers.tf`, `infra/variables.tf`, `infra/outputs.tf`
- Create: `infra/README.md` (stub; filled in U9)

**Approach:**
- `required_version >= 1.10`; S3 backend with `bucket`, `key = "ik-arch/terraform.tfstate"`,
  `region = us-east-1`, `encrypt = true`, `use_lockfile = true`. No DynamoDB.
- The state bucket itself must exist before `init` (chicken-and-egg): document a one-time bootstrap
  (create bucket + enable versioning + block public access) in the runbook, or a minimal separate
  bootstrap config. Prefer the documented one-time manual bucket creation to keep the root clean.
- Provider pinned; region fixed to `us-east-1`.

**Patterns to follow:** Standard HashiCorp S3 backend guidance; no repo precedent (greenfield).

**Test scenarios:**
- Test expectation: none — IaC scaffolding with no behavioral logic. Verified by `terraform init`
  succeeding against the backend and `terraform validate` passing.

**Verification:** `terraform init` connects to the S3 backend and acquires a lockfile; `terraform
validate` passes; state bucket has versioning enabled.

---

### Phase 2 — Data and secrets

- U2. **Lightsail Postgres (empty, public mode, TLS-enforced)**

**Goal:** Create the new empty managed Postgres in `us-east-1` with a generated master password
stored in SSM, public mode on, and a 15+ engine so TLS is enforced by default.

**Requirements:** R2, R4, R9

**Dependencies:** U1

**Files:**
- Create: `infra/database.tf`
- Modify: `infra/outputs.tf` (export `master_endpoint_address`/`_port`)

**Approach:**
- `aws_lightsail_database` with a Postgres 15+ `blueprint_id` (verified via CLI at build),
  `publicly_accessible = true`, `skip_final_snapshot` per policy, backups enabled.
- `random_password` with a charset excluding `/ " @`; write the value to
  `/ik-arch/prod/shared/DB_MASTER_PASSWORD` via `aws_ssm_parameter` (SecureString).
- Export endpoint host/port as outputs for the container env wiring in U6.
- No `rds.force_ssl` CLI step needed on 15+ (default `1`); note the CLI fallback in the runbook only
  for the <15 contingency.

**Patterns to follow:** Terraform AWS provider `aws_lightsail_database` docs; `random_password` +
`aws_ssm_parameter` pairing.

**Test scenarios:**
- Integration: after apply, a `psql` connection with `sslmode=require` using the SSM-stored password
  succeeds; a `sslmode=disable` connection is rejected (confirms server-side TLS enforcement).
- Edge case: confirm the generated password contains none of `/ " @`.

**Verification:** DB reachable over its public endpoint with TLS required; master password retrievable
only from SSM; DB is empty (no schema yet).

---

- U3. **SSM secret parameters + Terraform read wiring**

**Goal:** Define the SSM parameter naming scheme and the data-source reads for every secret/config
value the two services need, so container env vars can be sourced without secrets in git.

**Requirements:** R4, R7

**Dependencies:** U1 (values for OAuth params are populated in U5)

**Files:**
- Create: `infra/ssm.tf` (data sources)
- Modify: `infra/variables.tf` (SSM prefix variable)

**Approach:**
- Naming: `/ik-arch/prod/<service>/<VAR_NAME>`. Enumerate all params from the Secret Inventory
  (origin doc) — lik-mcp: `LIK_OAUTH_CLIENT_ID`, `LIK_RESOURCE_SERVER_URL`; lik-ui: `SESSION_SECRET`,
  `APP_OAUTH_CLIENT_ID/SECRET`, `LIKMCP_*`, `GDRIVEMCP_*`, `GITHUB_*`, `ANTHROPIC_API_KEY`,
  `AGENTS_CONFIG`; shared: `DB_MASTER_PASSWORD`.
- Terraform **reads** via `aws_ssm_parameter` data sources; it does not author secret values (except
  the DB password from U2). Population is a runbook step (put-parameter), so `terraform plan` will
  error clearly if a required parameter is missing — an intentional gate.
- Document which params are non-secret-but-environment-specific (client ids, resource URLs, agents
  config) vs. true secrets, though all are stored uniformly as SecureString for simplicity.

**Patterns to follow:** `aws_ssm_parameter` data source; sensitive-value handling.

**Test scenarios:**
- Error path: `terraform plan` with a missing required SSM parameter fails with a clear "parameter
  not found" error (gate works).
- Happy path: with all params populated, `terraform plan` resolves every data source and shows no
  secret values in output (redacted as sensitive).

**Verification:** All required env values resolve from SSM at plan time; no secret literal appears in
any `.tf` file or plan output.

---

### Phase 3 — Compute (services, OAuth, deployments)

- U4. **Lightsail Container Services (service-level only)**

**Goal:** Create both container services so their stable public HTTPS URLs exist and can anchor OAuth
registration — before any container is deployed.

**Requirements:** R2, R3

**Dependencies:** U1

**Files:**
- Create: `infra/lik_mcp.tf` (service resource), `infra/lik_ui.tf` (service resource)
- Modify: `infra/outputs.tf` (export both service `url`s)

**Approach:**
- `aws_lightsail_container_service` per app, smallest `power`, `scale = 1`. No
  `deployment_version` yet (that's U6).
- Export both `url` attributes; these feed OAuth registration (U5) and the env wiring (U6).

**Patterns to follow:** `aws_lightsail_container_service` docs.

**Test scenarios:**
- Test expectation: none behavioral — resource creation. Verified by both services reaching `READY`
  with a resolvable HTTPS `url` (returns TLS even with no deployment).

**Verification:** `terraform output` shows two stable HTTPS URLs; both services exist in `READY`/
active state with no deployment.

---

- U5. **OAuth client registration under Nava org + SSM population**

**Goal:** Create the production OAuth clients under Nava org ownership using the U4 service URLs, and
populate SSM with the resulting ids/secrets and the derived resource/callback URLs.

**Requirements:** R7, R4, R3

**Dependencies:** U4 (needs the public URLs)

**Files:**
- Modify: `docs/deploy-runbook.md` (per-provider registration steps + SSM put-parameter commands)

**Approach:**
- This is an external + runbook unit (no Terraform resources — providers are Google/GitHub consoles).
- Derive the exact redirect/callback URIs from the URLs: lik-ui `{APP_BASE_URL}/auth/callback` and
  `{APP_BASE_URL}/connections/callback`; lik-mcp `LIK_RESOURCE_SERVER_URL = {mcp-url}/mcp`.
- Honor the cross-service equality constraints: `LIK_UI_LIKMCP_CLIENT_ID` == lik-mcp
  `LIK_OAUTH_CLIENT_ID`; `LIK_UI_LIKMCP_RESOURCE_URL` == lik-mcp `LIK_RESOURCE_SERVER_URL`.
- Create under Nava org: Google Cloud project/clients (app-login + lik-mcp + gdrive), GitHub OAuth
  app (and any others the README notes, e.g. Slack). New clients, not transfers.
- Populate every corresponding `/ik-arch/prod/<service>/<VAR>` SSM param via `put-parameter`.

**Execution note:** Documentation/runbook + manual console work; no code. The committable artifact is
the runbook section and the parameter checklist.

**Test scenarios:**
- Test expectation: none — external registration. Correctness verified end-to-end in U6/U7 (login and
  a data-source connect succeed).

**Verification:** Every SSM parameter in the inventory is present; redirect URIs on each provider
match the derived callback URLs exactly.

---

- U6. **Container deployment versions (env from SSM, health checks, public endpoints)**

**Goal:** Deploy both containers with full prod env sourced from SSM + DB endpoint + service URLs, so
each boots under real auth and serves over HTTPS.

**Requirements:** R3, R4, R5, R9

**Dependencies:** U2, U3, U4, U5

**Files:**
- Modify: `infra/lik_mcp.tf`, `infra/lik_ui.tf` (add `aws_lightsail_container_service_deployment_version`)
- Modify: `infra/variables.tf` (image-ref variables for each service)

**Approach:**
- `container.image` = the pushed Lightsail ref `:<service>.<label>.<N>` passed via `-var` (from CI,
  U8). For the first apply, a placeholder public image may be used to prove the service, then
  re-applied with the real ref.
- `environment` map wires: DB host/port (from U2 outputs), `*_DB_PASSWORD` + all OAuth/session/
  anthropic/agents values (from U3 SSM data sources), `*_DB_SSLMODE=require`, `*_ENV=prod`,
  `LIK_RESOURCE_SERVER_URL` / `LIK_UI_APP_BASE_URL` (from U4 URLs), and `LIK_HTTP_ALLOWED_HOSTS`
  including the public hostname (lik-mcp — this is an enforced guard).
- `public_endpoint`: lik-mcp → container port 8000, health `path=/mcp`, `success_codes=200-499`;
  lik-ui → port 8001, health `path=/healthz`.
- Set `LIK_UI_APP_BASE_URL` to the public HTTPS URL (OAuth callbacks + `https_only` cookie depend on
  it).

**Patterns to follow:** `aws_lightsail_container_service_deployment_version` docs; the Dockerfiles'
runtime expectations (ports, `0.0.0.0` bind).

**Test scenarios:**
- Integration: after apply, lik-ui `/healthz` returns 200 over HTTPS; lik-mcp `/mcp` responds (401
  unauthenticated is expected and healthy).
- Integration: a full Google login on lik-ui succeeds (proves `SESSION_SECRET`, app-login client,
  `APP_BASE_URL` callback are correct).
- Error path: intentionally omitting one prod-required env var causes the container to fail its
  fail-closed guard at boot (confirms env wiring is load-bearing) — a throwaway check, not committed.
- Edge case: `LIK_HTTP_ALLOWED_HOSTS` missing the public host → lik-mcp rejects requests (confirms the
  host is included).

**Verification:** Both services serve over HTTPS under `prod`; login works; health checks pass; no
plaintext secret in the deployment config outside SSM/state.

---

### Phase 4 — Schema init, CI, documentation

- U7. **Schema initialization against the empty DB**

**Goal:** Initialize both services' schemas in the fresh DB over TLS, as a documented, repeatable
runbook step.

**Requirements:** R2, R5

**Dependencies:** U2 (DB exists), U6 (or run standalone once DB + password are available)

**Files:**
- Modify: `docs/deploy-runbook.md` (schema-init procedure)

**Approach:**
- lik-mcp: run `lik-mcp/scripts/init_db.py` pointed at the new DB with `LIK_DB_*` env (incl.
  `sslmode=require`), executed **as the DB master user** so `CREATE EXTENSION pg_trgm` and role
  creation succeed.
- lik-ui: `psql "host=… sslmode=require" -f lik-ui/db/init.sql`.
- Both scripts are idempotent (`IF NOT EXISTS`), so re-running is safe.

**Execution note:** Runbook procedure; run once at initial deploy. Document the master-user
requirement for lik-mcp explicitly (pg_trgm privilege).

**Test scenarios:**
- Integration: after running both, the expected tables exist (`catalog`, `confirmations` in the mcp
  DB; `users`, `user_vaults`, `sessions`, `dcr_registrations` in the ui DB) and `pg_trgm` is present.
- Edge case: re-running the init is a no-op (idempotency holds).

**Verification:** Both services can read/write their tables; a smoke query on each succeeds.

---

- U8. **GitHub Actions build+push workflow + OIDC IAM role**

**Goal:** CI builds each image and pushes it to the Lightsail registry using GitHub→AWS OIDC (no
long-lived keys), so the large upload runs off the maintainer's uplink. `terraform apply` stays local.

**Requirements:** R8, R4

**Dependencies:** U1 (state/role live in TF); U4 (services must exist to push to)

**Files:**
- Create: `.github/workflows/deploy-images.yml`
- Create: `infra/iam_github_oidc.tf` (OIDC provider + role + push-scoped policy)

**Approach:**
- IAM: OIDC provider for `token.actions.githubusercontent.com`; role trust scoped by `sub` to this
  repo + branch (`repo:<org>/<repo>:ref:refs/heads/main`), `aud = sts.amazonaws.com`. Push-only
  policy: `lightsail:PushContainerImage`, `RegisterContainerImage`, `GetContainerImages`,
  `GetContainerServices` (Lightsail is coarse, `Resource: "*"` — compensate with tight trust).
- Workflow: `permissions: id-token: write, contents: read`; `configure-aws-credentials@v6`; install
  `lightsailctl` on the runner; `docker build` + `aws lightsail push-container-image` per service;
  echo the returned `:svc.label.N` ref to the job summary for the maintainer to pass to
  `terraform apply -var`.
- Trigger: `workflow_dispatch` (+ optionally push to main) — build+push only, no deploy.

**Patterns to follow:** `aws-actions/configure-aws-credentials` OIDC docs; least-privilege trust
policy shape from research.

**Test scenarios:**
- Integration: a `workflow_dispatch` run authenticates via OIDC (no stored AWS keys), builds both
  images, pushes them, and prints two `:svc.label.N` refs.
- Error path: a run from a non-`main` ref (or another repo) is denied role assumption (confirms trust
  scoping).

**Verification:** CI produces pushed image refs consumable by `terraform apply`; no AWS secret keys
stored in GitHub; assume-role denied outside the scoped `sub`.

---

- U9. **Maintainer documentation**

**Goal:** Produce the reference docs a future maintainer needs to operate, deploy, and rebuild the
system without tribal knowledge.

**Requirements:** R5, R6

**Dependencies:** U1–U8 (documents the whole system)

**Files:**
- Create/Modify: `infra/README.md`, `docs/deploy-runbook.md`

**Approach:** Cover:
- Architecture + resource inventory (services, DB, SSM tree, IAM role, state bucket) in `us-east-1`.
- **Deploy sequence** (the load-bearing runbook): bootstrap state bucket → `apply` DB + services →
  read URLs → register OAuth clients (U5) → populate SSM → CI build+push → `apply` deployment
  versions with image refs → schema init (U7) → verify login/health.
- Secret inventory + `put-parameter` commands per parameter.
- **Custom-domain migration** procedure (attach domain + cert, update `*_RESOURCE_URL`/`APP_BASE_URL`
  + OAuth redirect URIs, re-apply).
- **Prominent warning:** do NOT `terraform destroy` a container service in normal operation — its
  default URL hash rotates and breaks every OAuth registration keyed to it.
- Log access (`aws lightsail get-container-log`) and the auto-deploy escalation pointer (Q5).

**Test scenarios:**
- Test expectation: none — documentation. Verified by a reviewer confirming the deploy sequence is
  followable start-to-finish and the resource inventory matches `terraform state list`.

**Verification:** A maintainer unfamiliar with the setup can follow the runbook to deploy and to
rebuild; the "don't destroy" and custom-domain caveats are present.

---

## System-Wide Impact

- **Interaction graph:** lik-ui depends on lik-mcp's public URL and OAuth client id (equality
  constraints). Changing either service's URL (e.g. destroy/recreate, or custom-domain migration)
  requires re-registering OAuth clients and updating SSM + redeploying.
- **Error propagation:** prod fail-closed guards mean a missing/incorrect secret surfaces as a
  container boot failure, not a silent runtime error — fast, visible feedback.
- **State lifecycle risks:** SSM secret values persist to Terraform state in plaintext → encrypted S3
  state + tight IAM is the control. Losing/rotating the DB master password requires updating SSM and
  redeploying.
- **API surface parity:** none — no app code changes.
- **Integration coverage:** login flow, data-source connect flow, and DB TLS enforcement are only
  proven end-to-end (U6/U7 integration scenarios), not by unit tests.
- **Unchanged invariants:** no application code changes (N5); the `us-east-2` DB and all its resources
  are untouched (N1a).

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| DB internet-exposed (public mode, no IP allowlist) | Accepted for internal low-traffic tool; TLS enforced (`force_ssl` on 15+, `sslmode=require`); strong generated password in SSM. Escalate to VPC+RDS only if a private-DB requirement appears (origin Rejected-Alternative). |
| Secrets land in Terraform state in plaintext | Encrypted S3 state (`encrypt=true`), versioned bucket, OIDC/IAM-scoped access; no tfvars secrets. |
| `pg_trgm`/role creation fails on non-master user | Run `init_db.py` as the DB master user; documented in U7. |
| Lightsail IAM is coarse (`Resource:"*"`) | Compensate with tightly-scoped OIDC trust (repo + branch `sub`); push-only policy for CI. |
| Destroying a container service rotates its URL → breaks OAuth | Prominent runbook warning (U9); URL-stability tracked as the top operational hazard. |
| `blueprint_id`/`bundle_id` values retired over time | Verify via `get-relational-database-blueprints`/`-bundles` at build; don't hardcode (deferred to implementation). |
| lik-ui `ALLOWED_HOSTS` currently unenforced | Set it for forward-compat; rely on `APP_BASE_URL` + `https_only` cookie today; app-side middleware wiring flagged to maintainers (out of scope). |
| State bucket bootstrap chicken-and-egg | One-time documented manual bucket creation (versioning + block-public) before first `init`. |

---

## Documentation / Operational Notes

- All maintainer docs are a first-class deliverable (U9), not an afterthought.
- Rollout is single-shot to a single `prod` environment; no blue/green.
- Monitoring: Lightsail container logs via CLI; no external observability stack in scope.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-15-01-aws-terraform-production-deploy-requirements.md](docs/brainstorms/2026-07-15-01-aws-terraform-production-deploy-requirements.md)
- Related code: `lik-mcp/settings.py`, `lik-mcp/__main__.py`, `lik-mcp/scripts/init_db.py`,
  `lik-mcp/db/init.sql`, `lik-ui/settings.py`, `lik-ui/app.py`, `lik-ui/db/init.sql`, both Dockerfiles.
- Related plan: [docs/plans/2026-07-06-001-feat-lik-ui-managed-agent-app-plan.md](docs/plans/2026-07-06-001-feat-lik-ui-managed-agent-app-plan.md)
- External: Terraform AWS provider (`aws_lightsail_container_service`,
  `aws_lightsail_container_service_deployment_version`, `aws_lightsail_database`, `aws_ssm_parameter`);
  GitHub OIDC for AWS (`aws-actions/configure-aws-credentials`); Terraform S3 backend native locking.
