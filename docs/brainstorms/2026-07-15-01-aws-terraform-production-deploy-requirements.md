---
date: 2026-07-15
topic: aws-terraform-production-deploy
---

# Production Deployment to AWS via Terraform

## Summary

Move the two services (`lik-mcp` and `lik-ui`) from the temporary onrender.com test deployment to a
production deployment on AWS, with all AWS resources created, configured, and maintained through
Terraform. Both services run as containers on **AWS Lightsail Container Service** backed by a
**Terraform-created Lightsail Postgres** (staying on Lightsail rather than RDS — cheaper at this
scale). **All production resources live in `us-east-1`**; the new DB **starts empty** (schema
initialized, no data). The existing `us-east-2` Lightsail DB is **left completely untouched** — no
migration, no config changes. Secrets live in **SSM Parameter Store** and are read by Terraform at
apply time. Public URLs start as the
**Lightsail-provided HTTPS URLs**, with a documented path to a custom domain later. Deployment is a
**documented manual runbook** (build image → push to Lightsail → `terraform apply`). Reference
documentation for future maintainers is a first-class deliverable.

This brainstorm is an infrastructure/architecture decision, so it intentionally records
implementation-level choices (services, state backend, secret store) — that is the subject of the
work, not a leak from planning.

---

## Problem Frame

The code has been validated on a throwaway onrender.com deployment. It now needs a durable,
reproducible production home on AWS that a future maintainer can understand, change, and rebuild from
declarative configuration rather than clicked-together console state. The hard part is not the
containers — both apps are small, stateless Python HTTP services. The risk surface is:

1. **`lik-ui` depends on a pile of secrets and stable public URLs.** It needs a session secret, an
   Anthropic API key, an app-login OIDC client, and pre-configured OAuth client ID/secret pairs for
   each data source (`lik-mcp`, Google Drive, GitHub). Several of these are **keyed to exact public
   URLs** — e.g. `LIK_UI_LIKMCP_RESOURCE_URL` must equal `lik-mcp`'s `LIK_RESOURCE_SERVER_URL`. URL
   stability and secret hygiene are the core of the job.
2. **Reproducibility and handoff.** The deployment must be describable in Terraform and a runbook so
   that a maintainer who has never seen it can operate and rebuild it.

---

## Goals

- G1. All AWS resources for production — including the Lightsail Postgres database — are created and
  maintained through Terraform, with remote state (S3) so the configuration is the source of truth.
- G1a. All production resources reside in `us-east-1`. The new Lightsail DB starts empty with its
  schema initialized; the `us-east-2` DB is not touched.
- G2. Both `lik-mcp` and `lik-ui` run in production over HTTPS with real Google auth enforced
  (`LIK_ENV=prod` / `LIK_UI_ENV=prod`).
- G3. Secrets never live in git or plaintext Terraform files; SSM Parameter Store is the source of
  truth, injected into containers at deploy time.
- G4. A maintainer can deploy a new image and roll config forward by following a written runbook,
  with no undocumented manual console steps.
- G5. Reference documentation exists for future maintainers: architecture, resource inventory,
  runbook, secret inventory, and the custom-domain migration path.
- G6. Production runs on **new OAuth client registrations created under Nava org ownership** (not the
  current personally-owned clients), with the new client ids/secrets stored in SSM. The plan carries
  the per-provider creation instructions.

## Non-Goals

- N1. Moving to RDS or any non-Lightsail managed DB (decision: stay on Lightsail Postgres for cost).
  A fresh Lightsail DB *is* created in `us-east-1` via Terraform, but switching DB *engine/service*
  is not.
- N1a. **No data migration** and **no changes to any `us-east-2` resource.** The new DB starts empty;
  the existing DB is left exactly as-is.
- N2. **Full auto-deploy** (Terraform apply run inside CI, so a merge rolls the deployment
  hands-free). Deferred. The in-scope CI (D6) does build+push only; `terraform apply` stays a local
  maintainer step. Escalation path and effort are noted in Open Questions for the plan to weigh.
- N3. Multiple environments (staging/dev). Single `prod` environment for now.
- N4. Autoscaling / multi-node / high-availability topology. Smallest viable size for internal,
  low traffic.
- N5. Application code changes or new features.

---

## Decisions

- D0. **Region:** All production resources in `us-east-1`. The existing `us-east-2` DB is **not
  touched** — no migration, no reconfiguration, not even referenced by the new stack.
- D1. **Compute:** AWS Lightsail Container Service, one service per app (`lik-mcp`, `lik-ui`). Built-in
  per-service HTTPS and TLS, fixed low monthly cost.
- D2. **Database:** Create a new, **empty** Lightsail Postgres in `us-east-1` **via Terraform**.
  Container services reach it over its **public endpoint with enforced TLS** — not a private network
  (see the network finding under Dependencies / Assumptions / Risks). D2a: DB in public mode,
  `sslmode=require`, password generated and stored in SSM.
- D2b. **Schema initialization:** The empty DB is initialized with each service's schema (the apps
  already ship `db/init.sql`) as a documented runbook step before first serve. No data is imported.
- D3. **Public URLs:** Start with the Lightsail-provided HTTPS URLs (`https://<svc>.<hash>.<region>.cs.amazonaws.com`).
  Register/configure OAuth clients against these. Document the migration to a custom domain as a
  follow-up (see Custom-Domain Migration below).
- D4. **Secrets:** SSM Parameter Store (SecureString) is the source of truth. Terraform reads the
  parameters at apply time and sets them as container environment variables in the Lightsail
  deployment. (Lightsail containers have no native secret-injection, so env-var injection is
  expected; keeping the store outside git is what matters.)
- D5. **Terraform state:** Remote state in S3.
- D6. **Deploy flow:** A **minimal GitHub Actions workflow builds the image and pushes it to the
  Lightsail registry** (`push-container-image`), so the bandwidth-heavy upload runs from the CI
  runner rather than a maintainer's machine (chosen because the maintainer uplink is slow). The
  maintainer then runs `terraform apply` **locally** to roll the new deployment. Rationale: the
  laptop only pushes git commits; CI handles the large image upload. Full auto-deploy (Terraform
  apply in CI) is deferred — see N2.
- D7. **Environment:** Single `prod` environment; `LIK_ENV=prod` and `LIK_UI_ENV=prod` so stub auth is
  off and real Google OAuth is enforced.
- D8. **OAuth registrations:** Create fresh clients under Nava org ownership for production rather
  than reusing/transferring the personal ones. These are external (Google Cloud, GitHub, and any
  others the README notes such as Slack), created via each provider's console — **not** Terraform.
  Their ids/secrets land in SSM (D4). The plan must include step-by-step per-provider creation
  instructions and the list of exact redirect/callback URLs each needs (derived from the deployed
  service URLs, so this happens after the Lightsail URLs are known).

---

## Rejected Alternative: Lightsail Instances (for a private DB)

Container Services cannot reach a Lightsail managed database over its private endpoint, so the DB
must run in public mode (see the network finding under Dependencies / Assumptions / Risks). Lightsail
**Instances** *can* reach the DB privately, which raised the question of using them instead. We chose
to stay on Container Service and accept a public-mode DB.

**Why Container Service wins here:**
- **Managed TLS + HTTPS URL** per service out of the box — critical because our public URLs anchor
  OAuth registrations. Instances would require running our own reverse proxy + Let's Encrypt (cert
  renewal to own) or adding a Lightsail Load Balancer (~+$18/mo) for managed certs.
- **Managed container lifecycle** — health checks, rolling deploys, restarts. Instances mean we own
  OS patching, container supervision (systemd/compose), and updates.
- **Reproducible from Terraform** — the container deployment is declarative. Instance app-state lives
  in cloud-init/manual steps and drifts, weakening the "rebuild from Terraform" goal (S4).
- **Simpler deploy** — `push-container-image` + `terraform apply` vs. SSH pull/restart.
- **Cost** — Container Service is ~$7–10/mo per service; instances add a load balancer (~$18/mo) to
  match the managed-TLS convenience.

**What we give up (the cost of this decision):**
- The DB runs in **public mode** — internet-reachable on its Postgres port, with **no IP
  allowlist/firewall** (a Lightsail managed-DB limitation). It is gated only by enforced TLS
  (`sslmode=require` + `rds.force_ssl`) and a strong, SSM-stored, generated password.

**Why the residual risk is acceptable:** internal, low-traffic tool; TLS enforced end to end; strong
generated credentials never in git. If a hard requirement for a private DB ever emerges (e.g. a
compliance mandate), the correct response is **not** Lightsail Instances but the VPC posture
(ECS/Fargate + RDS with security groups) — Instances would be operationally heavier and still weaker
than a real VPC. This decision is revisited only if that requirement appears.

---

## Secret Inventory (source of truth: SSM Parameter Store)

Captured here so planning does not have to rediscover it. Names below are illustrative, not final.

**Shared / infrastructure**
- Lightsail Postgres password — generated at DB creation and written to SSM (Terraform sets it as the
  master password and reads it back into container env). Connection host/port/db name are non-secret
  and point at the new `us-east-1` DB.

**`lik-mcp`**
- `LIK_OAUTH_CLIENT_ID` — Google OAuth client id (token audience). Non-secret but environment-specific.
- `LIK_RESOURCE_SERVER_URL` — this service's public URL + `/mcp`. Must match `lik-ui`'s reference.

**`lik-ui`**
- `LIK_UI_SESSION_SECRET` — signs the session cookie.
- `LIK_UI_ANTHROPIC_API_KEY` — Anthropic / Managed Agents key.
- `LIK_UI_APP_OAUTH_CLIENT_ID` / `..._SECRET` — app-login Google OIDC client.
- `LIK_UI_LIKMCP_CLIENT_ID` / `..._SECRET` / `..._RESOURCE_URL` — data connection to `lik-mcp`;
  `RESOURCE_URL` must equal `lik-mcp`'s `LIK_RESOURCE_SERVER_URL`.
- `LIK_UI_GDRIVEMCP_*` and `LIK_UI_GITHUB_*` — data connections for Google Drive and GitHub, each
  keyed to the corresponding MCP server URL.
- `LIK_UI_AGENTS_CONFIG` — agent/environment id pairs (non-secret, environment-specific).

---

## Custom-Domain Migration (documented follow-up)

Because production starts on the Lightsail default URL, this path must be written down:

- The Lightsail default URL contains a per-service hash. It is stable while the service exists but
  **changes if the container service is destroyed and recreated**, which would invalidate every OAuth
  registration keyed to it.
- Migration steps to document: attach a custom domain + Lightsail-managed cert to each service,
  update `LIK_RESOURCE_SERVER_URL` / `LIK_UI_*_RESOURCE_URL` and the OAuth client registrations to the
  new URLs, then apply.

---

## Success Criteria

- S1. From a clean checkout, a maintainer can `terraform apply` and reach both services over HTTPS
  with real Google login working end-to-end.
- S2. No secret value appears in git, in `*.tf` files, or in committed tfvars.
- S3. Deploying a new image version is a documented, repeatable sequence with no console-only steps.
- S4. Tearing down and rebuilding non-container resources from Terraform reproduces the same working
  system (with the documented caveat that recreating a container service rotates its default URL).
- S5. The maintainer docs (D5/G5) let someone unfamiliar operate the deployment without tribal
  knowledge.

---

## Dependencies / Assumptions / Risks

- **OAuth org ownership (now in scope — G6/D8):** The current clients are personally owned. Rather
  than transfer them, production uses **new** clients created under Nava org ownership. Sequencing
  dependency: several registrations need the deployed service URLs as their redirect/callback URIs,
  so client creation happens after the Lightsail URLs exist and before real login is exercised. A
  later custom-domain migration means updating these redirect URIs again (tie into the Custom-Domain
  Migration section).
- **URL-stability risk:** Do not `terraform destroy` a Lightsail container service in normal
  operation — its default URL hash rotates and breaks OAuth. Runbook must state this prominently.
- **Assumption:** One AWS account and region; the operator has credentials with rights to manage
  Lightsail, SSM, and S3.
- **Assumption:** Traffic is low and internal; smallest container size and a single node per service
  are sufficient.
- **Network finding (confirmed by architecture, not yet against the live account):** Lightsail
  Container Services **cannot** reach a Lightsail managed database over its *private* endpoint —
  container services don't join the Lightsail private network the way instances do. The DB must run
  in **public mode** and be reached over its public endpoint with enforced TLS. Lightsail managed
  DBs have **no IP allowlist/firewall**, so public mode means internet-reachable, gated only by TLS
  + credentials. Decision (D2a): enable/keep public mode + enforce `sslmode=require` (tighten the
  code's `prefer` default for prod) + treat the DB password as a first-class SSM secret. Because the
  new DB is Terraform-created, public mode is simply set at creation — no live-account confirmation
  needed. If internet-exposure of the DB is unacceptable, the only alternative is the VPC posture
  (ECS/EC2 + RDS), which was declined.
- **Terraform provider caveat:** Lightsail resource coverage in the AWS provider is thinner than for
  VPC/ECS/RDS; some steps (e.g. pushing the container image) may remain CLI actions in the runbook
  rather than Terraform resources.

---

## Open Questions for Planning

- Q1. Exact Terraform resource layout and which actions stay in the runbook vs. Terraform (notably
  image push and the container deployment roll).
- Q2. How the empty DB's schema gets initialized in the runbook (run each service's `db/init.sql`
  against the new endpoint) and whether Terraform or the runbook owns that step.
- Q3. SSM parameter naming/pathing scheme and how Terraform maps them to each service's env vars.
- Q4. Health-check and logging setup for each Lightsail container service.
- Q5. Escalation from build+push (D6) to full auto-deploy (N2), if/when desired. Roughly a
  half-to-full day, dominated by: (a) GitHub OIDC → scoped IAM role granting deploy + SSM-read + S3
  state/lock access; (b) running `terraform apply` in CI, including threading the pushed Lightsail
  image ref (`:service.label.N`) into the deployment resource; (c) trigger choice (merge vs. tag) and
  optional PR-plan/merge-apply gating. Note the security tradeoff: CI would then hold standing deploy
  + secret-read permissions (larger blast radius than push-only).
