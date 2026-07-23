---
title: "feat: lik-ui workspace initialization script"
type: feat
status: active
date: 2026-07-23
---

# feat: lik-ui workspace initialization script

## Summary

Add a Python script (`lik-ui/scripts/init_workspace.py`, run via `uv run`) that provisions the Managed-Agents
resources a fresh `lik-ui` Claude Workspace needs, using **only** a `lik-ui`-scoped API key. It creates a Knowledge
Search **agent** and an **environment** from definitions **hardcoded into the script** — snapshotted once from the
existing source agent/environment — with the LLM model (and a few other fields) overridable. It then prints the exact
`LIK_UI_*` lines to paste into [infra/ssm-secrets.example](infra/ssm-secrets.example) for
[infra/set-ssm-secrets.sh](infra/set-ssm-secrets.sh). The script has **no runtime dependency on the `Default`
workspace or the source resource IDs**. The API key stays a one-time Console step the script consumes as input —
everything else is automated.

---

## Problem Frame

A new, empty `lik-ui` Claude Workspace has been created for LIK. Standing it up today means clicking through the
Anthropic Console to recreate the Knowledge Search agent and its environment, then hand-assembling
`LIK_UI_AGENTS_CONFIG` — error-prone and undocumented. The goal is to reduce that to the smallest possible manual
footprint and produce copy-paste-ready SSM values.

The script must be **self-contained and independent of the `Default` workspace**: the source agent/environment
happen to live in `Default` today, but the init script must not read from `Default` or reference the source IDs at
run time. Instead, their definitions are captured once (at authoring/implementation time) and baked into the script
as literal constants, so running the script needs nothing but a `lik-ui` API key.

**The hard boundary:** Anthropic's Admin API does **not** support creating API keys — they can only be minted in the
Console (verified: Admin API FAQ, and `anthropic` 0.116.0 exposes no `api_keys`/`workspaces`/`admin`/`organizations`
resource). "Eliminate all manual setup" is therefore impossible; "reduce it to one Console click (create the key) plus
running one script" is the achievable target this plan commits to.

---

## Requirements

- R1. Create a Knowledge Search agent in the `lik-ui` workspace from an agent definition (model, system prompt, tools,
  MCP servers, skills) **hardcoded in the script**.
- R2. Let the operator override agent parameters — at minimum the LLM model — via flags, without editing the script.
- R3. Create an environment in the `lik-ui` workspace from an environment config **hardcoded in the script**.
- R4. Print the `LIK_UI_ANTHROPIC_API_KEY` and `LIK_UI_AGENTS_CONFIG` lines with real values, formatted to paste
  straight into `infra/ssm-secrets.example`.
- R5. Require only a single `lik-ui`-scoped API key at run time; **no reference to the source resource IDs and no read
  from the `Default` workspace** during execution.
- R6. Minimize manual Console work: the only unavoidable manual step is creating the API key; everything else is driven
  by the script.
- R7. Fail clearly and early on the known hazards (duplicate environment name; hardcoded custom skills that don't exist
  in `lik-ui`) rather than producing a silently broken agent.

---

## Scope Boundaries

- Not creating the Claude Workspace itself (already created) — the SDK cannot create workspaces anyway.
- Not creating or rotating the Anthropic API key (Console-only; see Problem Frame).
- Not reading from the `Default` workspace at run time — source definitions are captured once and hardcoded.
- Not writing to SSM or running Terraform — the script only *prints* values; `set-ssm-secrets.sh` and `tf.sh` remain
  the deploy path.
- Not registering OAuth clients or per-source MCP credentials (owned by [docs/oauth.md](docs/oauth.md)); the created
  agent only *declares* MCP server URLs, exactly as the snapshot does.
- Not modifying the running app, its `Settings`, or the DB.

### Deferred to Follow-Up Work

- Recreating any **custom** (non-Anthropic) Managed-Agents skills referenced by the hardcoded agent definition into
  the `lik-ui` workspace: separate effort if the snapshot (U2) shows the source agent uses them (see Open Questions).

---

## Context & Research

### Relevant Code and Patterns

- [lik-ui/scripts/smoke.py](lik-ui/scripts/smoke.py) — the convention to mirror: a stage-based Python script under
  `lik-ui/scripts/`, run with `uv run python scripts/smoke.py <stage>`, loading `lik_ui.settings.Settings`, taking the
  credential from `LIK_UI_ANTHROPIC_API_KEY`, printing structural (never secret-leaking) output. Its `surface` stage
  introspects `beta.{sessions,vaults,agents}`; its `agent` stage already does `beta.agents.retrieve(agent_id)` and
  prints the definition — the exact call the one-time capture step (U2) reuses.
- [lik-ui/src/lik_ui/agents.py](lik-ui/src/lik_ui/agents.py) — `AnthropicAgentsClient` shows how to read an agent:
  `client.beta.agents.retrieve(agent_id)` → `.model.id`, `.system`, `.mcp_servers`, `.skills`, `.tools` (with
  `mcp_toolset` / `default_config.permission_policy`). The `describe()` helper is lossy (drops `tools` structure) — the
  capture step must snapshot the **raw** object so hardcoded `tools` are complete.
- [lik-ui/src/lik_ui/settings.py](lik-ui/src/lik_ui/settings.py) — `LIK_UI_`-prefixed config; `agents_config` parsed
  as comma-separated `agent_id:environment_id` pairs. The printed `LIK_UI_AGENTS_CONFIG` must match this
  `<agent_id>:<environment_id>` shape.
- [infra/ssm-secrets.example](infra/ssm-secrets.example) lines 21, 23 — the two target lines:
  `$P/lik-ui/LIK_UI_ANTHROPIC_API_KEY=sk-ant-…` and `$P/lik-ui/LIK_UI_AGENTS_CONFIG=agent_…:env_…`.

### External References

- Admin API — [platform.claude.com/docs/en/manage-claude/admin-api](https://platform.claude.com/docs/en/manage-claude/admin-api):
  API keys support **list** and **update** only; **create is Console-only**. Service accounts / WIF exist but produce
  federated (keyless) auth, not a pasteable `sk-ant-…` string, so they don't satisfy R4.
- `anthropic` 0.116.0 (installed) — `client.beta.agents.create(model, name, description, mcp_servers, metadata,
  multiagent, skills, system, tools, …)` and `client.beta.environments.create(name, config, description, metadata,
  scope, …)` confirmed present; `.retrieve` on both (used only by the one-time capture step).
- Managed-Agents field limits (Managed Agents API reference): agent `name` 1–256 chars; **environment `name` must be
  unique — duplicate returns 409**. `tools` max 128, `skills` max 20, `mcp_servers` max 20.

---

## Key Technical Decisions

- **API key is an input, not an output.** The script reads the target key from `--target-key` / `LIK_UI_ANTHROPIC_API_KEY`
  and echoes it back in the printed SSM block. It never tries to create one (Console-only by Anthropic design; a
  service-account/WIF path would not yield the `sk-ant-…` string SSM expects).
- **Hardcoded definitions, single credential.** The agent and environment definitions are Python constants in the
  script, snapshotted once from the source resources. At run time the script needs only the `lik-ui` key and creates
  both resources in that workspace. Rationale: makes the script independent of the `Default` workspace and removes all
  cross-workspace credential complexity (per the requirement to not reference the source IDs at run time).
- **Capture is a throwaway one-liner, not committed code — the source IDs never appear in the script at all.** The
  author retrieves the raw definitions once via an ad-hoc `uv run python -c …` (or `smoke.py`'s existing `agent`
  stage) against a `Default`-workspace credential, and pastes the result into the script as constants. The plan/commit
  documents the one-liner; nothing referencing the source IDs is committed. Rationale: honors "don't refer to the
  agent/env IDs in the script" in the strictest form.
- **Model override is a first-class flag; other overrides are a small extensible set.** `--model` (the named
  requirement; defaults to the hardcoded snapshot's model), `--agent-name`, `--env-name`. Keep the surface minimal and
  store-agnostic.
- **Distinct env name required, print-only side effects.** Because env names must be unique, the hardcoded default env
  name is `lik-ui`-specific and `--env-name` overrides; a 409 is surfaced as a clear "pick a different --env-name"
  error. The script writes nothing to SSM/Terraform.
- **Lives in `lik-ui/scripts/`, not `infra/`.** It's a Python SDK program sharing `lik-ui`'s `anthropic` dependency and
  `Settings`; `infra/` is Terraform/bash. Mirrors `smoke.py`.

---

## Open Questions

### Resolved During Planning

- *Can the script create the API key?* No — Console-only (Admin API FAQ; SDK has no such resource). Resolved by making
  the key an input (R6 boundary).
- *Cross-workspace read of source templates?* Eliminated — definitions are hardcoded from a one-time snapshot; the
  create path uses only the `lik-ui` key (R5).
- *Where should the script live?* `lik-ui/scripts/init_workspace.py`, mirroring `smoke.py`.
- *Snapshot the raw object or `describe()`?* Raw retrieve — `describe()` drops `tools`.

### Deferred to Implementation

- **Custom skills in the snapshot.** If the captured agent has `skills` of `type: "custom"` (workspace-scoped `skill_…`
  IDs), those won't exist in `lik-ui` and `agents.create` will fail or reference a missing skill. The capture step must
  surface this; the create path must drop customs with a loud warning (or error under `--strict-skills`) pointing at
  the deferred skill-recreation work. Anthropic pre-built skills (`type: "anthropic"`, e.g. `xlsx`) hardcode cleanly.
- **Exact `environment.config` shape** (networking type, packages) — taken verbatim from the captured source env; do
  not invent fields.
- **Snapshot freshness** — the hardcoded definitions can drift from the source over time; acceptable for a bootstrap
  script. Re-running the capture one-liner regenerates the constants when the source changes.

---

## Implementation Units

- U1. **Script scaffold, credential & argument handling**

**Goal:** A runnable `init_workspace.py` that parses arguments, resolves the single `lik-ui` credential, and builds one
Anthropic client, following `smoke.py`'s structure and no-secret output conventions.

**Requirements:** R2, R5, R6

**Dependencies:** None

**Files:**
- Create: `lik-ui/scripts/init_workspace.py`
- Test: `lik-ui/tests/test_init_workspace.py`

**Approach:**
- `argparse` surface: `--model` (default: hardcoded snapshot model), `--agent-name`, `--env-name`, `--target-key`,
  `--dry-run`.
- Credential resolves from `--target-key`, else `LIK_UI_ANTHROPIC_API_KEY` (mirroring `smoke.py`). Never print key
  values — only a redacted hint (like the Admin API's `partial_key_hint`).
- `smoke.py`-style surface preflight: assert `beta.agents.create` and `beta.environments.create` exist before doing
  anything, so SDK drift fails fast and offline.

**Patterns to follow:** `lik-ui/scripts/smoke.py` (stage layout, `_hr`, credential-from-env, no-secret output).

**Test scenarios:**
- Happy path: full arg list → config object with defaults applied for omitted flags; `--model` override captured.
- Edge: neither `--target-key` nor env var set → clear error naming the env var.
- Edge: credential hint output redacts all but a short prefix/suffix (assert the full key never appears in output).

**Verification:** `uv run python scripts/init_workspace.py --help` lists the flags; a `--dry-run` with a fake key
reaches the preflight and reports SDK surface OK with no create calls.

---

- U2. **Hardcoded definitions + skill handling**

**Goal:** Embed the source agent/env definitions as module constants (captured out-of-band via a throwaway one-liner)
and provide the skill-partition helper the create path needs.

**Requirements:** R1, R3, R5, R7

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/scripts/init_workspace.py`
- Test: `lik-ui/tests/test_init_workspace.py`

**Approach:**
- Capture once, out-of-band (not committed as a script mode): with a `Default`-workspace credential, dump the raw
  objects — e.g.
  `LIK_UI_ANTHROPIC_API_KEY=<default-ws key> uv run python -c "import anthropic; c=anthropic.Anthropic(); print(c.beta.agents.retrieve('<id>').model_dump_json(indent=2)); print(c.beta.environments.retrieve('<id>').model_dump_json(indent=2))"`
  (or `smoke.py`'s `agent` stage). Capture `model`, `system`, `mcp_servers`, full `tools` (preserving `mcp_toolset` +
  `default_config.permission_policy`), `skills`, `description`, and env `config`.
- Paste the result into the script as module-level constants `AGENT_DEFINITION` / `ENV_DEFINITION`. Add a brief
  provenance note in the docstring (workspace + capture date). No source IDs anywhere in the script.
- `partition_skills(defn)`: separate `type == "anthropic"` from `type == "custom"`; the create path drops customs with
  a warning (or errors under `--strict-skills`).

**Test scenarios:**
- Happy path: hardcoded `AGENT_DEFINITION`/`ENV_DEFINITION` load as plain dicts with the expected keys.
- Error path: definition with a `type: "custom"` skill → `partition_skills` isolates it; default drops with a warning;
  `--strict-skills` raises naming the skill IDs and the deferred follow-up.
- Edge: definition with no system/skills/mcp_servers → the payload builder (U3) omits/empties those keys without error.

---

- U3. **Create resources and emit SSM output**

**Goal:** Build create payloads from the hardcoded definitions + overrides, create env then agent with the single
`lik-ui` client, and print the paste-ready SSM block; guard the known failures.

**Requirements:** R1, R3, R4, R7

**Dependencies:** U1, U2

**Files:**
- Modify: `lik-ui/scripts/init_workspace.py`
- Test: `lik-ui/tests/test_init_workspace.py`

**Approach:**
- `build_agent_payload(AGENT_DEFINITION, *, model, name)` and `build_env_payload(ENV_DEFINITION, *, name)`: apply
  overrides (model default = snapshot model) on top of the constants; drop custom skills per U2.
- Create env first (env-name 409 is the likeliest early failure — fail before creating an orphan agent), then the
  agent. On env 409, print "environment name already exists — pass a different `--env-name`" and exit non-zero.
- Output block, print-only, matching `infra/ssm-secrets.example` exactly:
  `$P/lik-ui/LIK_UI_ANTHROPIC_API_KEY=<target key>` and
  `$P/lik-ui/LIK_UI_AGENTS_CONFIG=<new_agent_id>:<new_env_id>`. If no target key was supplied (e.g. `--dry-run`
  preview), print a placeholder for the key line plus a reminder that the key is a Console step.
- `--dry-run`: build + print payloads and the would-be SSM block; create nothing.

**Execution note:** Live-API creation is verified by hand (smoke-style); unit tests drive SSM-formatting and
error-branching against a fake client.

**Test scenarios:**
- Happy path (fake client): create returns `agent_new`/`env_new` → printed block has
  `LIK_UI_AGENTS_CONFIG=agent_new:env_new` on one line, no trailing spaces/quotes (so `set-ssm-secrets.sh` parses it).
- Happy path: API-key line uses the supplied target key verbatim; `--model` override lands in the agent payload.
- Error path: env create raises 409 → exits non-zero with the "pick a different --env-name" message and does **not**
  call agent create.
- Edge: `--dry-run` → no create calls on the fake client; SSM block shows placeholder key + derived IDs.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Hardcoded custom skills absent in `lik-ui` | Detect in capture (U2); drop-with-warning by default, `--strict-skills` to hard-fail; recreation deferred. |
| Environment-name uniqueness 409 on re-run | `lik-ui`-specific default name + `--env-name` override; 409 handled with a clear message (U3). |
| Hardcoded definitions drift from the source over time | Acceptable for a bootstrap script; re-run the capture one-liner to regenerate the constants (documented in U2). |
| SDK method/field drift (`beta.agents`/`environments`) | `smoke.py`-style surface preflight fails fast and offline (U1). |
| Operator expects the script to mint the API key | Problem Frame + printed Console reminder set the expectation explicitly. |
| Re-running creates duplicate agents (agent names aren't unique) | `--dry-run` to preview; env-name 409 is the natural stop; document that re-runs create fresh resources. |

---

## Sources & References

- API-key creation limitation: [Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api),
  [List API Keys](https://platform.claude.com/docs/en/api/admin-api/apikeys/list-api-keys)
- SSM target: [infra/ssm-secrets.example](infra/ssm-secrets.example),
  [infra/set-ssm-secrets.sh](infra/set-ssm-secrets.sh)
- Script convention & SDK usage: [lik-ui/scripts/smoke.py](lik-ui/scripts/smoke.py),
  [lik-ui/src/lik_ui/agents.py](lik-ui/src/lik_ui/agents.py),
  [lik-ui/src/lik_ui/settings.py](lik-ui/src/lik_ui/settings.py)
- Managed Agents SDK (`anthropic` 0.116.0): `client.beta.agents.{retrieve,create}`,
  `client.beta.environments.{retrieve,create}`
