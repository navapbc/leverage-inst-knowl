"""Deploy agent + environment specs under `claude_platform/` to Claude Managed Agents.

GitHub is the source of truth for agent *definitions* the same way it is for skills (see
docs/plans/2026-07-24-001-feat-agent-spec-deploy-pipeline-plan.md). Each agent is a raw
platform-format YAML under `claude_platform/agents/`; each environment is a raw-format YAML under
`claude_platform/environments/`. This script resolves each resource **by name** (create if absent,
else update in place) and, for agents, translates a skill *name* into its platform `skill_id` before
the SDK call — so no ids live in the repo.

Run from the repo root (deploy skills first so referenced skills exist — the CI workflow does this):

    ANTHROPIC_API_KEY=sk-ant-... uv run --project scripts python scripts/deploy_agents.py --agent all

`--agent` accepts `all` (every spec under `claude_platform/agents/`) or a single agent spec name
(the filename stem). Environments are always synced (all specs under `claude_platform/environments/`),
so an agent's environment exists regardless of which agent is selected. `--dry-run` prints the planned
actions (still queries the platform to decide create-vs-update) without mutating.

Skill-name resolution reuses `deploy_skills.find_existing_skill_id`, so the two scripts agree on how a
name maps to a platform id. The Anthropic SDK is imported lazily (via `deploy_skills.build_client`) so
the pure helpers below stay importable and unit-testable without the dependency.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

import deploy_skills as ds

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = REPO_ROOT / "claude_platform" / "agents"
ENVIRONMENTS_ROOT = REPO_ROOT / "claude_platform" / "environments"


@dataclass
class DeployResult:
    kind: str  # "agent" | "environment"
    name: str
    resource_id: str
    version: str | None
    action: str  # "created" | "updated" | "would-create" | "would-update"


# --- spec loading + selection ------------------------------------------------------------------


def read_spec(path: Path) -> dict:
    """Parse a raw-format spec file; require a mapping carrying a non-empty ``name``."""
    if not path.is_file():
        raise ValueError(f"spec not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError(f"{path}: spec must be a mapping with a 'name'")
    return data


def select_agent_specs(selection: str) -> list[Path]:
    """Resolve ``--agent`` to spec files. ``all`` → every ``*.yaml`` under the agents root; any other
    value must name an existing spec by its filename stem."""
    if not AGENTS_ROOT.is_dir():
        raise ValueError(f"agents root not found: {AGENTS_ROOT}")
    if selection == "all":
        return sorted(AGENTS_ROOT.glob("*.yaml"))
    target = AGENTS_ROOT / f"{selection}.yaml"
    if not target.is_file():
        available = ", ".join(sorted(p.stem for p in AGENTS_ROOT.glob("*.yaml")))
        raise ValueError(f"unknown agent '{selection}'; available: {available}")
    return [target]


def select_environment_specs() -> list[Path]:
    """Every environment spec under the environments root (empty list if the dir is absent)."""
    if not ENVIRONMENTS_ROOT.is_dir():
        return []
    return sorted(ENVIRONMENTS_ROOT.glob("*.yaml"))


# --- by-name resolution ------------------------------------------------------------------------


def _match_by_name(items: list, name: str):
    """Return the single platform item whose ``name`` equals ``name``, or None. Ambiguity (two
    resources sharing a name) is an error — by-name deploy would otherwise pick one arbitrarily."""
    matches = [it for it in items if getattr(it, "name", None) == name]
    if len(matches) > 1:
        raise ValueError(f"ambiguous name {name!r}: {len(matches)} platform resources match")
    return matches[0] if matches else None


def find_existing_agent(client, name: str):
    return _match_by_name(list(client.beta.agents.list()), name)


def find_existing_environment(client, name: str):
    return _match_by_name(list(client.beta.environments.list()), name)


def resolve_skills(client, skills_spec) -> list[dict]:
    """Translate a spec's by-name ``skills`` list into platform skill refs pinned to ``latest``.

    Each entry must be ``{name: <skill dir name>}``. Errors if a referenced skill isn't on the
    platform yet — deploy it first with deploy_skills.py (the CI workflow runs that step first)."""
    resolved: list[dict] = []
    for entry in skills_spec or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not name:
            raise ValueError(f"skill entry must reference a skill by name: {entry!r}")
        skill_id = ds.find_existing_skill_id(client, name)
        if skill_id is None:
            raise ValueError(
                f"skill '{name}' not found on the platform — deploy it first with deploy_skills.py"
            )
        resolved.append({"type": "custom", "skill_id": skill_id, "version": "latest"})
    return resolved


# --- deploy ------------------------------------------------------------------------------------


def deploy_environment(client, spec_path: Path, *, apply: bool = True) -> DeployResult:
    """Create the environment if absent, else update it in place. Matched by ``name``."""
    spec = read_spec(spec_path)
    name = spec["name"]
    existing = find_existing_environment(client, name)
    if not apply:
        return DeployResult(
            "environment", name, getattr(existing, "id", "<new>"), None,
            "would-update" if existing else "would-create",
        )
    if existing:
        client.beta.environments.update(existing.id, **spec)
        return DeployResult("environment", name, existing.id, None, "updated")
    env = client.beta.environments.create(**spec)
    return DeployResult("environment", name, env.id, None, "created")


def deploy_agent(client, spec_path: Path, *, apply: bool = True) -> DeployResult:
    """Create the agent if absent, else update it (new version). Matched by ``name``; ``skills`` are
    resolved from names to platform ids before the call. On update, the full spec is re-sent with the
    agent's current version so the new version does not drop fields."""
    spec = read_spec(spec_path)
    name = spec["name"]
    payload = {**spec, "skills": resolve_skills(client, spec.get("skills"))}
    existing = find_existing_agent(client, name)
    if not apply:
        return DeployResult(
            "agent", name, getattr(existing, "id", "<new>"), None,
            "would-update" if existing else "would-create",
        )
    if existing:
        current = client.beta.agents.retrieve(existing.id)
        resp = client.beta.agents.update(existing.id, version=getattr(current, "version", None), **payload)
        return DeployResult("agent", name, existing.id, str(getattr(resp, "version", "?")), "updated")
    resp = client.beta.agents.create(**payload)
    return DeployResult("agent", name, resp.id, str(getattr(resp, "version", "?")), "created")


# --- CLI ---------------------------------------------------------------------------------------


def _emit_summary(results: list[DeployResult]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("### Agents & environments deployed\n\n")
        for r in results:
            ver = f" @ version `{r.version}`" if r.version else ""
            fh.write(f"- {r.action} {r.kind} `{r.name}` — `{r.resource_id}`{ver}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy agents + environments to Claude Managed Agents")
    parser.add_argument(
        "--agent",
        default="all",
        help="'all' or a single agent spec name (filename stem) under claude_platform/agents/",
    )
    parser.add_argument("--dry-run", action="store_true", help="print planned actions; mutate nothing")
    args = parser.parse_args(argv)

    agent_specs = select_agent_specs(args.agent)
    env_specs = select_environment_specs()
    client = ds.build_client()

    apply = not args.dry_run
    results: list[DeployResult] = []
    # Environments first (always all) so an agent's environment exists before/when it's deployed.
    for path in env_specs:
        results.append(deploy_environment(client, path, apply=apply))
    for path in agent_specs:
        results.append(deploy_agent(client, path, apply=apply))

    for r in results:
        ver = f" @ version {r.version}" if r.version else ""
        print(f"{r.action} {r.kind}: {r.name} -> {r.resource_id}{ver}")
    _emit_summary(results)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        raise SystemExit(f"error: {exc}")
