"""One-time bootstrap: attach skills to a Managed Agent, pinned to `version: "latest"`.

Run this **once per new skill**, not on every deploy. Once an agent references a skill at `latest`,
new versions published by ``deploy_skills.py`` are picked up automatically on the agent's next
session — the recurring deploy path never touches the agent. See
docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md.

Dry-run by default (prints the planned change without mutating). Pass ``--apply`` to write.

    ANTHROPIC_API_KEY=sk-ant-... LIK_AGENT_ID=agent_01... \
        uv run python attach_skills_to_agent.py --skill all            # dry run
    ANTHROPIC_API_KEY=sk-ant-... LIK_AGENT_ID=agent_01... \
        uv run python attach_skills_to_agent.py --skill all --apply    # write
"""

from __future__ import annotations

import argparse
import os
import sys

import deploy_skills as ds


def resolve_skill_ids(client, skill_names: list[str]) -> dict[str, str]:
    """Map each skill name to its platform skill_id. Errors if any skill isn't on the platform yet
    (deploy it with deploy_skills.py first)."""
    resolved: dict[str, str] = {}
    for name in skill_names:
        skill_id = ds.find_existing_skill_id(client, name)
        if skill_id is None:
            raise ValueError(f"skill '{name}' not found on the platform — deploy it first")
        resolved[name] = skill_id
    return resolved


def merge_skills(existing, target_ids: list[str]) -> list[dict]:
    """Return the agent's skills list with each target skill_id pinned to `latest`.

    Existing entries (including unrelated Anthropic skills) are preserved; an existing entry for a
    target skill_id is replaced with a `latest` pin. Order: preserved existing entries first (minus
    replaced targets), then the targets. Deterministic so the idempotence check is exact.
    """
    target_set = set(target_ids)
    merged: list[dict] = []
    for skill in existing or []:
        sid = getattr(skill, "skill_id", None) if not isinstance(skill, dict) else skill.get("skill_id")
        if sid in target_set:
            continue  # will be re-added below as a latest pin
        stype = getattr(skill, "type", None) if not isinstance(skill, dict) else skill.get("type")
        sver = getattr(skill, "version", None) if not isinstance(skill, dict) else skill.get("version")
        entry = {"type": stype, "skill_id": sid}
        if sver is not None:
            entry["version"] = str(sver)
        merged.append(entry)
    for sid in target_ids:
        merged.append({"type": "custom", "skill_id": sid, "version": "latest"})
    return merged


def _current_skills_as_dicts(agent) -> list[dict]:
    """Normalize the agent's current skills to comparable dicts (for the idempotence check)."""
    out: list[dict] = []
    for skill in getattr(agent, "skills", None) or []:
        entry = {"type": getattr(skill, "type", None), "skill_id": getattr(skill, "skill_id", None)}
        ver = getattr(skill, "version", None)
        if ver is not None:
            entry["version"] = str(ver)
        out.append(entry)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Attach skills to a Managed Agent at 'latest'")
    parser.add_argument("--skill", default="all", help="'all' or a single skill directory name")
    parser.add_argument("--agent-id", default=os.environ.get("LIK_AGENT_ID"), help="target agent id")
    parser.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    args = parser.parse_args(argv)

    if not args.agent_id:
        raise SystemExit("agent id required (--agent-id or LIK_AGENT_ID)")

    skill_names = [ds.read_skill_name(d) for d in ds.select_skill_dirs(args.skill)]
    client = ds.build_client()

    ids = resolve_skill_ids(client, skill_names)
    agent = client.beta.agents.retrieve(args.agent_id)
    current = _current_skills_as_dicts(agent)
    merged = merge_skills(getattr(agent, "skills", None), list(ids.values()))

    print(f"agent {args.agent_id} (version {getattr(agent, 'version', '?')})")
    print(f"  skills now:     {current}")
    print(f"  skills planned: {merged}")

    if merged == current:
        print("already attached — no change needed")
        return 0

    if not args.apply:
        print("dry run — re-run with --apply to write")
        return 0

    # Re-send the agent's other fields so the new version doesn't drop them, in case the platform
    # treats omitted fields as cleared rather than inherited.
    kwargs = {"version": getattr(agent, "version"), "skills": merged}
    if getattr(agent, "name", None) is not None:
        kwargs["name"] = agent.name
    model = getattr(agent, "model", None)
    if model is not None:
        kwargs["model"] = getattr(model, "id", model)
    if getattr(agent, "system", None) is not None:
        kwargs["system"] = agent.system
    for field in ("tools", "mcp_servers"):
        val = getattr(agent, field, None)
        if val:
            kwargs[field] = [t.model_dump(mode="json", exclude_none=True) for t in val]

    client.beta.agents.update(args.agent_id, **kwargs)
    updated = client.beta.agents.retrieve(args.agent_id)
    print(f"applied — skills now: {_current_skills_as_dicts(updated)}")
    print("verify the agent's tools/mcp_servers are intact in the Console.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
