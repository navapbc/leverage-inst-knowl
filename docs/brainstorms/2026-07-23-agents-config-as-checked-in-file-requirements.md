# Requirements: Move the agent roster from `LIK_UI_AGENTS_CONFIG` to a checked-in config file

**Date:** 2026-07-23
**Status:** Ready for planning
**Scope:** Standard (technical/config-loading change)

## Problem

The lik-ui agent roster is stored in a single environment variable, `LIK_UI_AGENTS_CONFIG`, as a
comma-jammed list of `agent_id:environment_id` pairs, provisioned in AWS SSM → Terraform → the ECS
container env and parsed once at boot (`lik-ui/src/lik_ui/settings.py:102-110`). As more agents are
added, this one string becomes **awkward and error-prone to read and edit by hand** — the confirmed
driving pain. Length limits and runtime dynamism are explicitly *not* the problem.

## Decisions (confirmed)

- **Driving pain:** editing ergonomics of a growing config, not dynamism and not size limits.
- **Restart-to-add is acceptable.** A new agent appearing after a redeploy is fine; no hot reload needed.
- **Agent/environment IDs are treated as non-sensitive identifiers.** They grant no capability without
  the separate, SSM-resident `LIK_UI_ANTHROPIC_API_KEY`, which remains the security boundary. Storing
  non-secrets in a secrets store is the thing being corrected.
- **Chosen approach:** move the roster to a **version-controlled config file in the repo**, one readable
  block per agent, reviewed via PR and tracked in git history. The app loads it at startup.

## Requirements

1. The roster lives in a checked-in config file (format — YAML/JSON/TOML — is the planner's to finalize).
   Each entry is human-readable and carries at minimum `agent_id` and `environment_id`; an optional
   friendly label/notes field is allowed but should be omitted if org-structure disclosure is a concern.
2. lik-ui loads this file at startup and exposes the same parsed `list[AgentOption]` the app already
   consumes (`app_auth.py`, `agents.py`, `chat.py` are unchanged downstream). The human-readable agent
   label continues to be fetched live from the agent definition via the SDK, not stored in the file.
3. `lik-ui/scripts/init_workspace.py` **appends the new agent's block to the config file directly**,
   replacing today's "print an SSM line to paste manually" step (`format_ssm_block`,
   `init_workspace.py:164-171`).
4. Remove `LIK_UI_AGENTS_CONFIG` from the secrets surface: the SSM param declaration (`infra/ssm.tf:35`,
   `infra/ssm.tf:44-47`), the container-env injection (`infra/lik_ui.tf:83`), the secrets template
   (`infra/ssm-secrets.example:23`), and the startup guard entry (`settings.py:136`) should no longer
   reference it. The prod fail-closed guard should instead validate the config file is present/non-empty.
5. Update local/dev config to match: `.env.example`, `docker-compose.yml`, and the stale
   `docker-compose.override.yml` block (which currently sets unused `LIK_UI_DEFAULT_AGENT_*` vars and runs
   with an effectively empty agent list — fix this as part of the change).
6. Update tests that assert the old string format (`tests/test_init_workspace.py:155,163,221`) and the
   deploy runbook note about restart-to-change (`docs/deploy-runbook.md:413`).

## Success criteria

- A maintainer can add or remove an agent by editing a readable file block and opening a PR; the diff
  clearly shows what changed and git history records who/when.
- `init_workspace.py` adds a new agent end-to-end without any manual copy-paste into SSM.
- The app behaves identically at runtime (same agent picker, same connections/chat resolution); only the
  source of the roster changed.
- No agent config remains in SSM; `LIK_UI_ANTHROPIC_API_KEY` and other genuine secrets are untouched.

## Out of scope (deferred)

- Admin UI or non-engineer-facing roster management.
- Database-backed agent registry.
- Per-request or hot reload of the roster (restart-to-change is accepted).
- Per-agent SSM parameters under a path prefix (Approach C — more infra plumbing, no PR review).

## Assumptions / open items for planning

- **Config file format and location** within `lik-ui/` — planner to finalize.
- **Repo visibility:** analysis assumes `ik-arch` is private (or that labels are omitted). If the repo is
  public *and* hiding org structure matters, revisit keeping IDs in SSM with a readable multi-line format
  (Approach A) instead.
- Whether the prod startup guard should hard-fail on an empty roster file or allow an empty roster in
  non-prod (mirror current `require_production_config` behavior).

## Approaches considered

- **A — Readable multi-line format in the same SSM param.** Smallest change; keeps IDs in SSM. Rejected as
  primary because it improves readability but not reviewability/history, and keeps non-secrets in a
  secrets store. Retained as the fallback if IDs must stay in SSM.
- **B — Checked-in config file (chosen).** Readable, diffable, PR-reviewed, git-versioned; lets the init
  script append directly. Valid because IDs are non-sensitive.
- **C — One SSM param per agent under a prefix.** Solves the string problem but adds Terraform
  prefix-enumeration plumbing and still lacks PR review; more cost than B for less benefit.
