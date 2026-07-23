---
title: "refactor: Move lik-ui agent roster from LIK_UI_AGENTS_CONFIG to a checked-in config file"
type: refactor
status: active
date: 2026-07-23
origin: docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md
---

# refactor: Move lik-ui agent roster from `LIK_UI_AGENTS_CONFIG` to a checked-in config file

## Summary

Replace the comma-jammed `LIK_UI_AGENTS_CONFIG` environment variable with a version-controlled TOML file
(`[[agents]]` blocks) that lik-ui loads at startup. Reading uses stdlib `tomllib` (no new dependency);
`init_workspace.py` appends a new agent block to the source-tree file instead of printing an SSM line to
paste; and the SSM param + Terraform wiring for the roster are removed. Downstream consumers keep receiving
the same `list[AgentOption]`, so runtime behavior is unchanged — only the source of the roster moves.

---

## Problem Frame

The roster is one growing, hand-edited env var of opaque `agent_id:environment_id` pairs living in a
secrets store (SSM); editing it as more agents are added is awkward and error-prone. The pain is editing
ergonomics, not size limits or runtime dynamism (see origin: `docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md`).

---

## Requirements

- R1. The roster lives in a checked-in, human-readable config file; each entry carries at least
  `agent_id` and `environment_id`.
- R2. lik-ui loads the file at startup and exposes the same `list[AgentOption]` today's app consumes
  (`app_auth.py`, `agents.py`, `chat.py` unchanged). The label is still fetched live via the SDK, not stored.
- R3. `scripts/init_workspace.py` appends a new agent's block to the config file directly, replacing the
  "print an SSM line to paste" step.
- R4. `LIK_UI_AGENTS_CONFIG` is removed from the secrets surface (SSM declaration, container-env injection,
  secrets template, startup guard). The prod fail-closed guard instead validates the roster is non-empty.
- R5. Local/dev config and docs are updated to match (`.env.example`, `docker-compose*.yml`, deploy runbook).
- R6. The config file ships inside the installed package so it exists in the `pip install .` container.
- R7. No agent config remains in SSM; `LIK_UI_ANTHROPIC_API_KEY` and other genuine secrets are untouched.

**Origin acceptance criteria:** a maintainer adds/removes an agent by editing a readable block in a PR;
`init_workspace.py` adds an agent end-to-end with no manual SSM paste; app behaves identically at runtime.

---

## Scope Boundaries

- No admin UI or non-engineer-facing roster management.
- No database-backed agent registry.
- No per-request or hot reload — restart-to-change is accepted; the running process reads the file once at boot.
- No per-agent SSM parameters (origin Approach C, rejected).
- Not touching the `LIK_UI_ANTHROPIC_API_KEY` SSM flow — it stays a secret in SSM.

---

## Context & Research

### Relevant Code and Patterns

- `lik-ui/src/lik_ui/settings.py:103` — `agents_config: str` field and `agents` property (`:109-117`) that
  splits the string into `AgentOption`s. `AgentOption` (`:14-24`). Prod guard `require_production_config`
  (`:131-151`) currently lists `LIK_UI_AGENTS_CONFIG` at `:143`.
- `lik-ui/src/lik_ui/settings.py:105-107` — `allowed_hosts` property is the existing "parse a config value
  into a list" pattern to mirror in shape (property returning a parsed list).
- `lik-ui/scripts/init_workspace.py:209-216` — `format_ssm_block` emits both the API-key SSM line and the
  agents SSM line; `main` prints it at `:264-265` (dry-run) and `:289-290` (real run).
- `lik-ui/pyproject.toml:33-34` — `[tool.setuptools.package-data]` already ships `templates/*.html` and
  `static/*`; the config file must be added here (same reason: non-editable `pip install .` omits non-`.py`
  files). Comment at `:31-32` documents exactly this pitfall.
- `lik-ui/Dockerfile` — `COPY src ./src` then `pip install .`; runtime is the installed package, not source.
- `infra/ssm.tf:35` (in `ui_ssm_params`) and `infra/ssm.tf:44-47` (the `data` block); `infra/lik_ui.tf:83`
  (container-env injection); `infra/ssm-secrets.example:23` (paste template).
- `lik-ui/tests/test_settings.py:21-39` — existing agents-string tests; `:42-46` prod-guard test.
- `lik-ui/tests/test_init_workspace.py:151-163,217-222` — `format_ssm_block` and dry-run tests.

### Institutional Learnings

- No `docs/solutions/` entries were found relevant to this config change.

### External References

- None needed. `tomllib` is stdlib as of Python 3.11 (repo is 3.14); setuptools package-data is already used.

---

## Key Technical Decisions

- **Format: TOML with `[[agents]]` array-of-tables.** Rationale: (1) read with stdlib `tomllib` — zero new
  runtime dependency, unlike YAML (PyYAML); (2) comments are first-class, unlike JSON; (3) each agent is a
  self-contained block, so `init_workspace.py` appends by **concatenating a text block** rather than
  parse-and-rewrite — existing entries, ordering, and comments are never reflowed or mangled.
- **Two resolution contexts, one file.** Runtime (`settings.py`) reads the file **packaged with the
  installed module** (resolve relative to the module, e.g. via `importlib.resources` / module dir). The init
  script appends to the **source-tree** file (resolve relative to the repo, e.g. from the script's own
  location). This matches the real workflow: init writes source → dev commits → image rebuild ships it.
- **Configurable path with a package default.** Add an `agents_config_path` setting defaulting to the
  packaged file, overridable (env/constructor) so tests can point at a temp file. Replaces the
  `agents_config` string field.
- **Prod guard checks emptiness, not a string.** `require_production_config` validates the parsed roster is
  non-empty (file present + ≥1 agent) instead of checking a non-empty env var; keeps fail-closed behavior.
- **Local/test now read the same checked-in file** rather than an empty/`.env` value — local dev gets the
  real roster for free; tests override the path for custom/empty rosters.

---

## Open Questions

### Resolved During Planning

- File format → TOML `[[agents]]` (see Key Technical Decisions).
- File location → inside the package (`src/lik_ui/`), shipped via package-data, so it exists in the container.
- Repo visibility (origin open item) → treated as private / labels optional; IDs are non-sensitive per origin.
  If the repo were public and hiding org structure mattered, the fallback is origin Approach A — out of scope here.
- Prod guard on empty roster → hard-fail outside local/test (mirrors current behavior for the other required
  values); local/test may run with an empty roster.

### Deferred to Implementation

- Exact file-resolution helper (`importlib.resources.files` vs module-dir `Path`) — pick whichever the
  installed-package layout makes cleanest; both satisfy R6.
- Whether to keep an optional `label`/`notes` field in the TOML schema for readability, or omit it to avoid
  org-structure disclosure — decide at implementation; the runtime label still comes from the SDK regardless.

---

## Implementation Units

- U1. **Config file + settings loading**

**Goal:** Introduce the TOML roster file and make `Settings` load agents from it, replacing the
`agents_config` string.

**Requirements:** R1, R2, R7

**Dependencies:** None

**Files:**
- Create: `lik-ui/src/lik_ui/agents.toml` (seeded with the current production agent as one `[[agents]]` block)
- Modify: `lik-ui/src/lik_ui/settings.py`
- Test: `lik-ui/tests/test_settings.py`

**Approach:**
- Define the TOML schema: a top-level `[[agents]]` array where each block has `agent_id` and
  `environment_id` (optional `label`/`notes` per Deferred question). Include a header comment explaining the
  file and that labels come from the SDK.
- Replace `agents_config: str` with `agents_config_path` (default = packaged `agents.toml`, resolved relative
  to the module so it works from the installed package). Rewrite the `agents` property to read the file with
  `tomllib`, iterate `[[agents]]`, and build `AgentOption`s. Skip entries missing `agent_id`.
- Update `require_production_config` to check `not self.agents` instead of the `agents_config` string; keep
  the same error shape (name the roster file in the message).
- Seed `agents.toml` with the current roster (the Knowledge Search agent id/env from the existing SSM value).

**Patterns to follow:** `allowed_hosts` property shape (`settings.py:105-107`); `AgentOption` (`:14-24`).

**Test scenarios:**
- Happy path: a temp TOML with two `[[agents]]` blocks → `settings.agents` returns two `AgentOption`s with
  the right ids/envs, in file order. Covers R2.
- Happy path: the shipped `agents.toml` parses and yields ≥1 agent (guards the seeded file's validity). Covers R1.
- Edge: empty file / no `[[agents]]` → `agents == []`.
- Edge: a block missing `agent_id` is skipped (mirrors old empty-`agent_id` behavior).
- Error path: `env="prod"` with an empty roster → `require_production_config()` raises naming the roster. Covers R4.
- `env="local"`/`test` with empty roster → no raise.

**Verification:** `uv run pytest tests/test_settings.py` passes; app still boots with the seeded roster.

---

- U2. **Ship the config file in the installed package**

**Goal:** Ensure `agents.toml` exists at runtime in the `pip install .` container.

**Requirements:** R6

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/pyproject.toml` (add the file to `[tool.setuptools.package-data]`)

**Approach:**
- Add `agents.toml` to the `lik_ui` package-data globs alongside `templates/*.html` and `static/*`.
- Confirm the runtime resolution in U1 finds the packaged file (not a source-relative path) when installed.

**Patterns to follow:** existing `[tool.setuptools.package-data]` entry (`pyproject.toml:33-34`).

**Test expectation:** none (packaging config) — verified by build, not unit test.

**Verification:** build the wheel and confirm `agents.toml` is inside it (e.g. inspect
`python -m build` output / `pip install .` into a temp env and check the installed package dir); or
`docker build` + a one-off container run that boots and lists the seeded roster.

---

- U3. **`init_workspace.py` appends the agent block to the config file**

**Goal:** Replace the "print `LIK_UI_AGENTS_CONFIG` SSM line" step with a direct append to the source-tree
`agents.toml`; keep printing the API-key SSM line.

**Requirements:** R3

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/scripts/init_workspace.py`
- Test: `lik-ui/tests/test_init_workspace.py`

**Approach:**
- Add a helper that formats one `[[agents]]` block from `(agent_id, env_id)` and appends it to the
  source-tree `agents.toml` (resolve the path relative to the script's own location, not the installed
  package). Text append — do not parse-and-rewrite.
- Shrink `format_ssm_block` to emit only the `LIK_UI_ANTHROPIC_API_KEY` SSM line (the API key stays a
  secret). Update `main`: on real run, append the block and print a confirmation + the API-key SSM line; on
  `--dry-run`, print the block that *would* be appended plus the API-key line, and write nothing.
- Update the module docstring (it currently describes pasting both lines into `ssm-secrets.example`).

**Patterns to follow:** existing `format_ssm_block` text-building style (`init_workspace.py:209-216`);
`--dry-run` guard (`:259-266`).

**Test scenarios:**
- Happy path: append helper on a temp file containing one block → file now has two `[[agents]]` blocks,
  original block byte-for-byte intact, new block parses via `tomllib` to the expected id/env. Covers R3.
- Happy path: `format_ssm_block` returns only the API-key line (no `LIK_UI_AGENTS_CONFIG`).
- Edge: append to a file that ends without a trailing newline → blocks stay separated (valid TOML).
- Integration: `main(["--dry-run"])` prints the would-be block and does **not** modify the target file
  (assert mtime/content unchanged), and still creates nothing.

**Verification:** `uv run pytest tests/test_init_workspace.py` passes; a manual `--dry-run` shows the block.

---

- U4. **Remove `LIK_UI_AGENTS_CONFIG` from infra**

**Goal:** Drop the roster from SSM and Terraform; keep the API-key param.

**Requirements:** R4, R7

**Dependencies:** U1 (file is the new source of truth)

**Files:**
- Modify: `infra/ssm.tf` (remove `"LIK_UI_AGENTS_CONFIG"` from `ui_ssm_params`, `:35`)
- Modify: `infra/lik_ui.tf` (remove the `LIK_UI_AGENTS_CONFIG` container-env line, `:83`)
- Modify: `infra/ssm-secrets.example` (remove the `LIK_UI_AGENTS_CONFIG` template line, `:23`)

**Approach:**
- Delete the three references. Leave `LIK_UI_ANTHROPIC_API_KEY` (ssm.tf:34, lik_ui.tf:82) untouched.
- Operational note: the existing SSM parameter `${ssm_prefix}/lik-ui/LIK_UI_AGENTS_CONFIG` becomes orphaned;
  it can be deleted out-of-band after apply (call out in the runbook — U5). Terraform no longer reads it, so
  it won't error, but it lingers until manually removed.

**Patterns to follow:** the other entries in `ui_ssm_params` / the container-env map.

**Test expectation:** none (infra config).

**Verification:** `terraform validate` (or `plan`) succeeds and shows only the removal of the
`LIK_UI_AGENTS_CONFIG` env var on the container deployment, no other diff.

---

- U5. **Update local/dev config and docs**

**Goal:** Bring dev config and docs in line with the file-based roster.

**Requirements:** R5

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/.env.example` (remove the `LIK_UI_AGENTS_CONFIG` example; note the roster is in
  `src/lik_ui/agents.toml`)
- Modify: `lik-ui/docker-compose.override.yml` (remove the stale, unused `LIK_UI_DEFAULT_AGENT_LABEL` /
  `LIK_UI_DEFAULT_AGENT_ID` / `LIK_UI_DEFAULT_ENVIRONMENT_ID` lines, `:25-27`)
- Modify: `lik-ui/docker-compose.yml` (add a one-line comment that the roster ships in the image; no var needed)
- Modify: `docs/deploy-runbook.md` (update the restart-to-change note near `:413`; add the orphaned-SSM-param
  cleanup note from U4; update the "Populate SSM" section to drop `LIK_UI_AGENTS_CONFIG`)

**Approach:**
- Docs describe: agents are edited in `src/lik_ui/agents.toml` via PR; a new agent requires a rebuild/deploy
  (restart-to-change, accepted); `init_workspace.py` appends the block for you.

**Patterns to follow:** existing comment style in `.env.example` and the compose files.

**Test expectation:** none (config/docs) — no behavioral change.

**Verification:** `docker compose config` parses; `.env.example` has no `LIK_UI_AGENTS_CONFIG`; runbook reads
consistently with the file-based flow.

---

## System-Wide Impact

- **Interaction graph:** `settings.agents` is consumed by `app_auth.py:182`, `agents.py:109`, `chat.py:304`.
  Contract (`list[AgentOption]`) is preserved, so these are untouched — verify by boot + agent-picker render.
- **API surface parity:** none — no HTTP/API surface changes.
- **State lifecycle risks:** the roster is read at boot; changing the file mid-process has no effect (by
  design). `init_workspace.py` appends to the source file, not the running container's copy.
- **Unchanged invariants:** `AgentOption` shape, the SDK-fetched label, and the `LIK_UI_ANTHROPIC_API_KEY`
  SSM secret flow are all explicitly unchanged.
- **Integration coverage:** U1's "shipped `agents.toml` parses to ≥1 agent" test plus the U2 build/boot check
  together prove the packaged file is found at runtime — the failure mode unit tests alone would miss.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Config file omitted from the installed wheel → empty roster in prod, and the prod guard hard-fails the boot | U2 adds it to `package-data`; U1 test asserts the shipped file parses; U2 verifies via build/boot. The fail-closed guard turns a silent-empty into a loud startup error. |
| `init_workspace.py` corrupts existing entries when adding one | Text-append of a self-contained `[[agents]]` block (no parse-rewrite); U3 test asserts the original block is byte-for-byte intact. |
| Orphaned SSM param lingers after infra change | U4/U5 note it for out-of-band deletion; harmless (no longer read). |
| Seeded roster in `agents.toml` drifts from the live SSM value at cutover | U1 seeds from the current `LIK_UI_AGENTS_CONFIG` value; confirm the id/env match before removing the SSM param (U4). |

---

## Documentation / Operational Notes

- Deploy runbook: adding an agent is now edit-`agents.toml` → PR → rebuild/deploy; drop the
  `LIK_UI_AGENTS_CONFIG` populate-SSM step; note the one-time orphaned-param cleanup.
- Rollout ordering: land the file + code (U1–U3) and confirm the container boots with the seeded roster
  before removing the SSM param and Terraform wiring (U4), so there's no window with an empty roster.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md](docs/brainstorms/2026-07-23-agents-config-as-checked-in-file-requirements.md)
- Related code: `lik-ui/src/lik_ui/settings.py`, `lik-ui/scripts/init_workspace.py`, `infra/ssm.tf`, `infra/lik_ui.tf`
- Related plan: [docs/plans/2026-07-23-002-feat-lik-ui-workspace-init-script-plan.md](docs/plans/2026-07-23-002-feat-lik-ui-workspace-init-script-plan.md)
