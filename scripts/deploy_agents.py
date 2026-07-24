"""Deploy agent + environment specs under `claude_platform/` to Claude Managed Agents.

GitHub is the source of truth for agent *definitions* the same way it is for skills (see
docs/plans/2026-07-24-001-feat-agent-spec-deploy-pipeline-plan.md). Each agent is a raw
platform-format YAML under `claude_platform/agents/`; each environment is a raw-format YAML under
`claude_platform/environments/`. This script resolves each resource **by name** (create if absent,
else update in place). An agent references its skills *by name*; this script deploys exactly those
skills first (via `deploy_skills.deploy_skill` — create or new version) and attaches them at
`latest`, so no ids live in the repo and only the skills an agent actually uses are published.

Run from the repo root:

    ANTHROPIC_API_KEY=sk-ant-... uv run --project scripts python scripts/deploy_agents.py --agent all

`--agent` accepts `all` (every spec under `claude_platform/agents/`) or a single agent spec name
(the filename stem). Environments are always synced (all specs under `claude_platform/environments/`),
so an agent's environment exists regardless of which agent is selected. `--dry-run` prints the planned
actions (still queries the platform to decide create-vs-update) without publishing anything.

Skill deployment reuses `deploy_skills.deploy_skill` / `select_skill_dirs`, so agents and the
standalone skill deploy agree on packaging and id resolution. The Anthropic SDK is imported lazily
(via `deploy_skills.build_client`) so the pure helpers below stay importable and unit-testable.
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
    """Every environment spec under the environments root (empty list if the dir is absent).

    Intentionally returns *all* environments, unscoped by ``--agent``. Unlike skills — which an agent
    spec references by name, so deploy can publish exactly the ones it uses — the agent↔environment
    pairing is not in the agent spec; it lives only in lik-ui's roster (``agents.toml``), which this
    script deliberately does not read. Syncing all environment specs keeps this script decoupled from
    the roster while guaranteeing any agent's environment exists. Environments are few and rarely
    change, so the over-sync is cheap."""
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


def resolve_skills(client, skills_spec, *, deploy: bool = True) -> list[dict]:
    """Translate a spec's by-name ``skills`` list into platform skill refs pinned to ``latest``.

    Each entry must be ``{name: <skill dir name>}``. When ``deploy`` is true (a real run), the
    referenced skill is published first — ``deploy_skills.deploy_skill`` creates it or adds a new
    version — and its resulting id is used, so deploying an agent also deploys exactly the skills it
    references (and nothing else). Errors if a referenced skill has no directory under
    ``claude_platform/skills/``. When ``deploy`` is false (dry run), nothing is published: the id is
    resolved from the platform if the skill already exists, else shown as a placeholder."""
    resolved: list[dict] = []
    for entry in skills_spec or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not name:
            raise ValueError(f"skill entry must reference a skill by name: {entry!r}")
        if deploy:
            skill_dir = ds.select_skill_dirs(name)[0]  # validates the skill exists in the repo
            skill_id = ds.deploy_skill(client, skill_dir).skill_id
        else:
            skill_id = ds.find_existing_skill_id(client, name) or "<will-be-created>"
        resolved.append({"type": "custom", "skill_id": skill_id, "version": "latest"})
    return resolved


# --- deploy ------------------------------------------------------------------------------------


def _as_plain_dict(resource) -> dict:
    """Normalize a platform resource (SDK pydantic model, dict, or a test SimpleNamespace) to a plain
    dict for comparison. Keeps null/empty values (no exclude_none) so 'field is absent' and 'field is
    set' compare correctly."""
    if hasattr(resource, "model_dump"):
        return resource.model_dump(mode="json")
    if isinstance(resource, dict):
        return dict(resource)
    return {k: v for k, v in vars(resource).items() if not k.startswith("_")}


def _spec_matches_current(spec: dict, current) -> bool:
    """True when every field the spec declares already matches the current platform resource.

    A recursive *subset* match: fields the platform adds beyond what the spec declares (e.g. a
    `packages` block the spec omits) are ignored, so platform-side defaults don't read as changes.
    A missing field on the current side is treated as ``None`` so ``description: null`` matches an
    absent description. Lists are compared exactly. This is what lets a no-op re-deploy report
    "unchanged" instead of a misleading "updated"."""
    cur = _as_plain_dict(current)

    def subset(desired, actual) -> bool:
        if isinstance(desired, dict):
            if not isinstance(actual, dict):
                return False
            return all(subset(v, actual.get(k)) for k, v in desired.items())
        if isinstance(desired, list):
            return list(desired) == list(actual or [])
        return desired == actual

    return subset(spec, cur)


def deploy_environment(client, spec_path: Path, *, apply: bool = True) -> DeployResult:
    """Create the environment if absent; if present, update it only when a field the spec declares
    actually differs from the current platform state — otherwise report ``unchanged`` and skip the
    call, so a no-op re-deploy doesn't claim it changed something. Matched by ``name``."""
    spec = read_spec(spec_path)
    name = spec["name"]
    existing = find_existing_environment(client, name)

    if existing is None:
        if not apply:
            return DeployResult("environment", name, "<new>", None, "would-create")
        env = client.beta.environments.create(**spec)
        return DeployResult("environment", name, env.id, None, "created")

    # Present already — only touch it if the spec's declared fields don't already match.
    current = client.beta.environments.retrieve(existing.id)
    if _spec_matches_current(spec, current):
        return DeployResult("environment", name, existing.id, None, "unchanged")
    if not apply:
        return DeployResult("environment", name, existing.id, None, "would-update")
    client.beta.environments.update(existing.id, **spec)
    return DeployResult("environment", name, existing.id, None, "updated")


def deploy_agent(client, spec_path: Path, *, apply: bool = True) -> DeployResult:
    """Create the agent if absent, else update it (new version). Matched by ``name``; ``skills`` are
    resolved from names to platform ids before the call. On update, the full spec is re-sent with the
    agent's current version so the new version does not drop fields."""
    spec = read_spec(spec_path)
    name = spec["name"]
    # Deploy exactly the skills this agent references (create/version), then attach at latest.
    # In a dry run nothing is published.
    payload = {**spec, "skills": resolve_skills(client, spec.get("skills"), deploy=apply)}
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
    # Environments first, and intentionally ALL of them (not scoped to --agent or agents.toml) — see
    # select_environment_specs — so whichever environment an agent is paired with in lik-ui's roster
    # already exists on the platform.
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
