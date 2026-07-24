"""One-shot bootstrap for a lik-ui Claude Workspace.

Deploys the repo's skill, environment, and agent specs to whatever workspace a target API key
belongs to, then prints the ``LIK_UI_ANTHROPIC_API_KEY`` line to paste into a copy of
``infra/ssm-secrets.example`` (consumed by ``infra/set-ssm-secrets.sh``) plus the deploy steps.

GitHub is the single source of truth for the definitions (see
docs/plans/2026-07-24-001-feat-agent-spec-deploy-pipeline-plan.md): skills live under
``claude_platform/skills/`` and agents/environments under ``claude_platform/agents`` and
``claude_platform/environments`` as the platform's raw export YAML. This script does not define any
agent inline — it runs the same deploy code the CI workflow uses (``scripts/deploy_skills.py`` then
``scripts/deploy_agents.py``), just pointed at a target-workspace key instead of the CI secret.
Skills are deployed first so an agent's by-name skill references resolve.

The roster (``src/lik_ui/agents.toml``) references agents by *name*, so it is stable across
workspaces — re-initializing into a new workspace needs no id rewrite here.

The API key itself is NOT created here: Anthropic does not expose programmatic API-key creation
(Console-only, by design), so create it by hand in the Console for the target workspace and hand it to
this script. Which workspace the deploy lands in is determined by that key. Nothing here logs the key;
it prints only a redacted hint plus the API-key SSM line.

Usage:
  LIK_UI_ANTHROPIC_API_KEY=sk-ant-... uv run python scripts/init_workspace.py
  uv run python scripts/init_workspace.py --dry-run
  uv run python scripts/init_workspace.py --target-key sk-ant-...
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# The repo-root scripts/ dir holding the deploy tooling this script orchestrates. Resolved from this
# file (lik-ui/scripts/init_workspace.py -> parents[2] is the repo root).
REPO_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

SSM_PREFIX = "$P/lik-ui"

# Deploy steps that pick up the new values, printed after the SSM block. The agent roster is committed
# by name in agents.toml and is workspace-stable, so there is no per-run id edit. Steps 2-3 run from
# infra/ (see infra/ssm-secrets.example's header for the $P path-prefix substitution). Step 4 repoints
# the CI secret used by BOTH deploy-skills.yml and deploy-agents.yml at this workspace, or they would
# publish to the old one. Step 5 rebuilds+redeploys the app image via CI.
NEXT_STEPS = (
    "1. Ensure the agent is listed by name in src/lik_ui/agents.toml (add a [[agents]] block if new),\n"
    "   then commit + merge it.\n"
    "2. Copy infra/ssm-secrets.example to a temp file and set its LIK_UI_ANTHROPIC_API_KEY\n"
    "   line to the one above.\n"
    "3. From infra/:  ./set-ssm-secrets.sh COPY_OF_ssm-secrets.example\n"
    "4. Update the GitHub prod-environment secret so skill/agent deploys (deploy-skills.yml,\n"
    "   deploy-agents.yml) target this workspace:  gh secret set ANTHROPIC_API_KEY --env prod\n"
    "   (paste the same key).\n"
    "5. Run the \"Build and deploy images\" GitHub Action for lik-ui\n"
    "   (gh workflow run deploy-images.yml -f service=lik-ui). It rebuilds the image and redeploys."
)


def _hr(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def redact(key: str | None) -> str:
    """A logging-safe hint for an API key — never the full value."""
    if not key:
        return "(none)"
    return f"{key[:10]}…{key[-4:]}" if len(key) > 16 else "sk-ant-…"


def resolve_target_key(cli_key: str | None) -> str | None:
    """The target workspace key: ``--target-key`` wins, else ``LIK_UI_ANTHROPIC_API_KEY`` (with .env
    support via Settings, mirroring smoke.py). Returns None when unset."""
    if cli_key:
        return cli_key
    from lik_ui.settings import Settings  # lazy: keeps the module importable without config

    return Settings().anthropic_api_key or None


def format_ssm_block(api_key: str | None, prefix: str = SSM_PREFIX) -> str:
    """The API-key line to paste into a copy of infra/ssm-secrets.example. No quotes, no trailing
    space — set-ssm-secrets.sh takes the value as everything after the first '='. The agent roster is
    not an SSM value; it lives (by name) in agents.toml."""
    key_value = api_key or "sk-ant-…  # create in the Console for the target workspace"
    return f"{prefix}/LIK_UI_ANTHROPIC_API_KEY={key_value}"


def run_deploy(script: str, args: list[str], api_key: str) -> None:
    """Run a repo-root deploy script in its own uv project, with the target key in the environment.

    Kept as a subprocess (not an import) so the deploy runs in scripts/'s own environment and this
    bootstrap stays a thin orchestrator over the same code CI uses."""
    cmd = ["uv", "run", "--project", str(REPO_SCRIPTS), "python", str(REPO_SCRIPTS / script), *args]
    env = {**os.environ, "ANTHROPIC_API_KEY": api_key}
    subprocess.run(cmd, env=env, check=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bootstrap a lik-ui Claude Workspace (deploy skills + agents).")
    p.add_argument("--target-key", help="target workspace API key (else LIK_UI_ANTHROPIC_API_KEY).")
    p.add_argument("--dry-run", action="store_true", help="print the plan and the would-be SSM block; deploy nothing.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    target_key = resolve_target_key(args.target_key)

    _hr("plan")
    print("deploy order: skills (deploy_skills.py --skill all) -> environments + agents "
          "(deploy_agents.py --agent all)")
    print(f"target key: {redact(target_key)}")

    if args.dry_run:
        _hr("dry run — nothing deployed")
        _hr("paste into a copy of infra/ssm-secrets.example")
        print(format_ssm_block(target_key))
        _hr("then deploy")
        print(NEXT_STEPS)
        return 0

    if not target_key:
        raise SystemExit("no API key: pass --target-key or set LIK_UI_ANTHROPIC_API_KEY (target workspace key).")

    print(f"\ndeploying to the workspace of key {redact(target_key)} …")
    # Skills first so agents' by-name skill references resolve, then environments + agents.
    run_deploy("deploy_skills.py", ["--skill", "all"], target_key)
    run_deploy("deploy_agents.py", ["--agent", "all"], target_key)

    _hr("paste into a copy of infra/ssm-secrets.example")
    print(format_ssm_block(target_key))
    _hr("then deploy")
    print(NEXT_STEPS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
