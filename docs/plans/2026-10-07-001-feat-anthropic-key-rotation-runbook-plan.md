---
title: "feat: Add an Anthropic API key rotation runbook"
type: feat
status: completed
date: 2026-10-07
---

# feat: Add an Anthropic API key rotation runbook

## Summary

Add a "Rotating the Anthropic API key" section to `docs/deploy-runbook.md`. The section takes a
maintainer from "the key stopped working" (or "the key leaked") to "every consumer uses the new
key". No app code changes. The `Settings` page gets no key override.

---

## Problem Frame

One Anthropic API key, stored at `/ik-arch/prod/shared/ANTHROPIC_API_KEY`, serves every consumer:

- **lik-ui container**: Terraform copies the SSM value into the container's environment
  (`infra/lik_ui.tf`). The container reads it once at startup (`lik-ui/src/lik_ui/__main__.py`).
- **GitHub workflows**: `deploy-skills.yml`, `deploy-agents.yml`, `prune-sessions.yml`, and
  `scheduled-runs.yml` fetch it from SSM at run time.

When the key is revoked, expired, or leaked, every chat fails and every workflow fails. No
document lists the rotation steps. The closest text is a one-line comment in the runbook's
"Populate SSM secrets" step (`then redeploy so the container picks it up: ./tf.sh apply`).

A `Settings`-page override was considered and rejected. `Settings` holds per-user data, the app
has no admin role, and the workflows would not see a database override.

---

## Requirements

- R1. A maintainer can rotate the key by following one runbook section, without reading code.
- R2. The runbook covers every consumer: the lik-ui container, the four SSM-reading workflows, and
  maintainers' local copies of the key.
- R3. The runbook checks the new key before it reaches prod, and checks prod after the rotation.
- R4. The runbook states that the new key must belong to the same Claude workspace, and routes a
  cross-workspace change to `lik-ui/scripts/init_workspace.py`.
- R5. The Terraform step cannot silently deploy a different container image than the one running.
- R6. The new key never appears on a command line, in shell history, in a world-readable file, in
  saved Terraform output, or in a Claude session.
- R7. A leaked key stays valid for as short a time as possible.

---

## Scope Boundaries

- No `Settings`-page key override, per-user key, or admin role.
- No change to how lik-ui reads the key (it stays env-at-startup via Terraform).
- No automation of the rotation itself.
- No repair of `lik-ui/scripts/smoke.py`. Its `agent` and `session` stages read `Settings`
  attributes that no longer exist, so the runbook does not use that script.

### Deferred to Follow-Up Work

- lik-ui reads the key from SSM at startup, so rotation = update SSM + restart, with no Terraform
  apply: separate plan, only if rotation becomes frequent.
- Repair or remove the broken `smoke.py` stages: separate change.
- Make `infra/set-ssm-secrets.sh` exit non-zero when any `put-parameter` fails: separate change.

---

## Context & Research

### Relevant Code and Patterns

- `docs/deploy-runbook.md`: "3. Populate SSM secrets" shows the single-secret update form of
  `infra/set-ssm-secrets.sh`. "Routine redeploy (new image)" shows the plan-review-then-apply style
  to mirror.
- `infra/set-ssm-secrets.sh`: writes `NAME=value` lines from a file, keeping the value off the
  `aws` command line. When a write fails, the script prints `FAILED: <name>` but still exits 0.
- `infra/tf.sh`: for `apply` only, it injects the custom-domain URLs and the `LIK_MCP_IMAGE` /
  `LIK_UI_IMAGE` refs. The images default to the latest *pushed* ref. Every other subcommand,
  including `plan`, passes through with no injected variables. That means a bare `./tf.sh plan`
  plans to destroy both deployments.
- `.github/workflows/deploy-images.yml` (the `apply` job): reads each service's deployed image ref
  with `aws lightsail get-container-services --query
  "containerServices[0].currentDeployment.containers.\"<name>\".image"`. The runbook reuses this
  query to pin images.
- `infra/ssm.tf` (`shared_ssm_params`) and `infra/lik_ui.tf` (`LIK_UI_ANTHROPIC_API_KEY`): the one
  path from SSM to the container.
- `lik-ui/src/lik_ui/agents.py` (`build_agents_client`, `resolve_agent_options`): resolves every
  roster name in `agents.toml` to an id, using the configured key. The call fails loudly when the
  key is invalid or the workspace lacks a roster agent. `lik-ui/scripts/run_scheduled.py` runs the
  same call at startup.
- `.github/workflows/scheduled-runs.yml`: calls `resolve_agent_options` before scanning, so a
  dispatch proves the workflows read a working key. A dispatch also runs any schedules that are due
  at that moment. It joins the `lik-prod-mutations` concurrency group, and a failed run opens a
  "scheduled-runs cron failed" issue.
- `lik-ui/scripts/init_workspace.py`: bootstraps a new workspace (deploys skills, environments,
  agents) and prints the SSM line. This is the cross-workspace path.

### Institutional Learnings

- None in `docs/solutions/` cover key rotation.

---

## Key Technical Decisions

- **Put the section in `docs/deploy-runbook.md`, after "Routine redeploy"**: operators already go
  to that file for prod changes. A separate file would split the SSM and Terraform steps from
  the steps they mirror.
- **Same-workspace key as the default path**: sessions, vaults, and agents belong to one Claude
  workspace. A same-workspace key keeps every existing session and credential working. A
  different-workspace key orphans them, so that case routes to `init_workspace.py`.
- **Check the new key with `resolve_agent_options`, not `smoke.py`**: the roster-resolution call
  proves both properties step 3 needs (the key authenticates, and every roster name exists in this
  workspace). The call needs no code change.
- **Redeploy with a pinned `./tf.sh apply` without `-auto-approve`, never `./tf.sh plan`**: `apply`
  is the only `tf.sh` subcommand that injects the image and domain variables. Without
  `-auto-approve`, Terraform prints the plan built from those exact inputs and waits for `yes`.
  This gives the review step with no extra command, and it satisfies R5.
- **No CI redeploy path**: `deploy-images.yml` always builds and deploys a new image from the
  dispatched commit, so that path cannot satisfy R5.
- **Two orderings, keyed on the trigger**: for an expired or revoked key, the old key is already
  dead, so the runbook verifies first and revokes last. For a leaked key, the runbook revokes the
  old key right after creating the new one, and accepts downtime until the redeploy finishes (R7).
- **The human enters the key at a hidden prompt in their own terminal**: the value goes from
  `read -rs` into a shell variable, then into a `mktemp` + `chmod 600` file. Both the step 3 check
  and step 4 read the variable. The file is deleted and the variable unset at the end (R6).

---

## Open Questions

### Resolved During Planning

- Do the workflows need a change? No. They fetch the key from SSM on every run, so they pick up
  the new key on their next run.
- Can `deploy-images.yml` replace the local Terraform step? No. See Key Technical Decisions.

### Deferred to Implementation

- **Error text**: what an invalid key looks like in the lik-ui chat page and in a workflow log
  (likely an `authentication_error` 401). Capture it by running the step 3 check with a bogus key,
  then quote it in the runbook's "Symptoms" line.
- **Expiry**: whether Console-issued keys expire on a date, or only get revoked. The runbook
  should cover both without claiming either.
- **Plan redaction**: whether the pinned `./tf.sh apply` prints the container's
  `LIK_UI_ANTHROPIC_API_KEY` as `(sensitive value)`. The SSM data source marks its value
  sensitive, so the value is likely redacted `(likely)`. Check this with the current key during
  U1 verification, and state the observed behavior in the runbook.

---

## Implementation Units

- U1. **Rotation section in the deploy runbook**

**Goal:** One section a maintainer follows end to end.

**Requirements:** R1, R2, R3, R4, R5, R6, R7

**Dependencies:** None

**Files:**
- Modify: `docs/deploy-runbook.md`

**Approach:** The section opens with the trigger choice, then holds these steps in order:
1. **Symptoms and trigger**: the error text from the deferred question, as seen in chat and in
   workflow logs. The maintainer picks the branch: *expired or revoked* or *leaked*.
2. **Create**: a new key in the Anthropic Console, in the same workspace as the current key.
   A different workspace routes to `init_workspace.py`. On the *leaked* branch, revoke the old key
   in the Console now and note the exposure window for step 8.
3. **Check the new key**: in the maintainer's own terminal, `read -rs` the key into a variable,
   export it as `LIK_UI_ANTHROPIC_API_KEY` with `LIK_UI_ENV=prod`, and run the roster-resolution
   check from `lik-ui/`. Exporting matters because `Settings` falls back to `lik-ui/.env` when the
   variable is unset. A wrong-workspace or invalid key fails here, before SSM changes.
4. **Write SSM**: write `/ik-arch/prod/shared/ANTHROPIC_API_KEY=<variable>` into a `mktemp` +
   `chmod 600` file and run `set-ssm-secrets.sh` on it. Then delete the file and unset the variable.
   Confirm the write with `aws ssm get-parameter --query Parameter.Version`. The version must be
   one higher than before, because the script exits 0 even when a write fails.
5. **Redeploy lik-ui**: read both deployed image refs with the `deploy-images.yml` query. Run
   `LIK_MCP_IMAGE=<ref> LIK_UI_IMAGE=<ref> ./tf.sh apply` without `-auto-approve`. Answer `yes` only
   when the plan reads `Plan: 1 to add, 0 to change, 1 to destroy.` for the lik-ui deployment. Do not
   use `-out`. Do not paste plan or apply output into a PR, an issue, or a Claude session.
6. **Verify**: check that `/healthz` returns ok. Check that the lik-ui `currentDeployment` is the new
   one, because Lightsail keeps the old deployment (old key) running when the new one fails its
   health check. Send one chat message in the app. Dispatch `scheduled-runs.yml` once. Warn the
   reader that the dispatch runs any due schedules and can queue behind `lik-prod-mutations`.
7. **Update local copies**: replace the old key in `lik-ui/.env` and in any shell profile that
   holds it.
8. **Revoke and review**: on the *expired or revoked* branch, revoke the old key in the Console
   once step 6 passes. On the *leaked* branch, the old key is already revoked. Review its usage in
   the Console for the exposure window instead.

The section also states that no Claude session may receive, echo, or write the key. The human
runs steps 3 and 4 in their own terminal.

**Patterns to follow:** the code-block and "If the plan is anything else" style of "Routine
redeploy (new image)". The `mktemp` file pattern already in the runbook's SSM step.

**Test expectation:** none, because this is a documentation-only change.

**Verification:**
- The read-only parts run cleanly against prod with the *current* key. Step 3's check resolves
  every roster agent. Step 5's pinned `./tf.sh apply` (answered `no`) reports `No changes.` and
  shows how the key value renders in the plan.
- Running step 3's check with a bogus key prints the error text that the Symptoms line quotes.
- Every command in the section names the full path, profile, and region, so the section runs
  without consulting another file.

- U2. **Pointer from the repo CLAUDE.md**

**Goal:** A Claude session diagnosing a failing key finds the runbook, and keeps its hands off the
key.

**Requirements:** R1, R6

**Dependencies:** U1

**Files:**
- Modify: `CLAUDE.md` (the "Production environment" section's AWS bullet, which already names
  the key's SSM path)

**Approach:** Add one clause that points to the runbook section by its heading and says the human
enters the new key in their own terminal.

**Test expectation:** none, because this is a documentation-only change.

**Verification:** The repo CLAUDE.md names the runbook section heading exactly as U1 wrote it.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| The apply deploys a newer pushed image along with the key change. | Step 5 pins both images to the deployed refs, and the maintainer answers `yes` only to a lik-ui-only replacement. |
| A different-workspace key orphans every session, vault, and agent. | Step 2 requires the same workspace. Step 3's roster check fails on a wrong-workspace key before SSM changes. |
| The new key leaks through shell history, a temp file, Terraform output, or a Claude session. | `read -rs` into a variable, then a `chmod 600` temp file that is deleted afterwards. No `-out`, no pasted plan output, no key in a session. |
| An SSM write fails silently and the redeploy ships the old key. | Step 4 confirms that the parameter version went up. |
| The new deployment fails health checks, and the old key keeps serving. | Step 6 confirms the current deployment before step 8 revokes anything. |
| A leaked key stays usable during the rotation. | The *leaked* branch revokes it in step 2 and accepts downtime until step 5 finishes. |
| A dispatch in step 6 runs real scheduled work. | Step 6 warns the reader. The runs are the same ones the cron would start. |

---

## Sources & References

- Related code: `infra/ssm.tf`, `infra/lik_ui.tf`, `infra/tf.sh`, `infra/set-ssm-secrets.sh`,
  `lik-ui/src/lik_ui/agents.py`, `lik-ui/scripts/init_workspace.py`,
  `.github/workflows/deploy-images.yml`, `.github/workflows/scheduled-runs.yml`
- Related PRs: #76 (points the key references at the shared SSM path)
