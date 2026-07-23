"""Deploy skill directories under `.claude/skills/` to Claude Managed Agents.

GitHub is the source of truth for skill instructions (see
docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md). This script packages a
skill directory and publishes it to the Managed Agents platform as a new *version* via the Anthropic
SDK. Versions are immutable, so "deploy" always means "add a version"; agents that pin the skill to
`latest` pick it up on their next session.

Run from the repo root:

    ANTHROPIC_API_KEY=sk-ant-... uv run --project scripts python scripts/deploy_skills.py --skill all

`--skill` accepts `all` (every directory under `.claude/skills/`) or a single skill name.

Two upload rules the platform enforces (both surface as opaque 400s if violated), so this script
guards them before uploading:
  1. Every file must be nested under one top-level folder — arcnames are `<name>/<relpath>`.
  2. That folder name must equal the `name:` in SKILL.md. We assert `name == dir.name` and fail fast.

The Anthropic SDK is imported lazily inside ``build_client`` so the pure helpers below remain
importable (and unit-testable) without the dependency installed.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Repo-relative location of the skill directories. Resolved from this file so the script works
# regardless of the caller's cwd.
SKILLS_ROOT = Path(__file__).resolve().parent.parent / ".claude" / "skills"

_CONTENT_TYPES = {".md": "text/markdown"}


@dataclass
class DeployResult:
    name: str
    skill_id: str
    version: str
    action: str  # "created" | "versioned"


def read_skill_name(skill_dir: Path) -> str:
    """Return the ``name:`` from a skill directory's SKILL.md frontmatter.

    Raises ValueError if SKILL.md is missing or has no parseable ``name:`` in its leading
    ``---``-delimited frontmatter block.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"{skill_dir}: no SKILL.md")
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{skill_md}: missing YAML frontmatter")
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"{skill_md}: no 'name:' in frontmatter")


def validate_dir_name(skill_dir: Path, name: str) -> None:
    """Guard the platform rule that the top-level folder name must equal the skill name.

    Compared case-insensitively because the platform lowercases the skill name.
    """
    if name.lower() != skill_dir.name.lower():
        raise ValueError(
            f"{skill_dir}: SKILL.md name '{name}' must match the directory name "
            f"'{skill_dir.name}' (the platform rejects a mismatch with a 400)"
        )


def build_arcnames(skill_dir: Path, name: str) -> list[tuple[str, Path]]:
    """Map every file under ``skill_dir`` to its upload arcname ``<name>/<relpath>``.

    Nesting under a single top-level folder is the platform's other upload rule. Returns
    (arcname, path) pairs sorted by arcname for deterministic uploads.
    """
    pairs: list[tuple[str, Path]] = []
    for path in sorted(skill_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(skill_dir).as_posix()
            pairs.append((f"{name}/{rel}", path))
    return pairs


def to_upload_files(pairs: list[tuple[str, Path]]) -> list[tuple[str, object, str]]:
    """Convert (arcname, path) pairs to the SDK's (arcname, fileobj, content_type) tuples."""
    files: list[tuple[str, object, str]] = []
    for arcname, path in pairs:
        content_type = _CONTENT_TYPES.get(path.suffix, "text/plain")
        files.append((arcname, path.open("rb"), content_type))
    return files


def find_existing_skill_id(client, name: str) -> str | None:
    """Return the platform skill_id whose display_title equals ``name``, or None.

    We set ``display_title == name`` on create, so matching on display_title recovers the id for
    subsequent version uploads without storing any id state in the repo. (If a future SDK exposes a
    different stable field on list items, switch the match here.)
    """
    for skill in client.beta.skills.list():
        if getattr(skill, "display_title", None) == name:
            return skill.id
    return None


def deploy_skill(client, skill_dir: Path) -> DeployResult:
    """Publish one skill directory as a new version (or create it if it doesn't exist yet)."""
    name = read_skill_name(skill_dir)
    validate_dir_name(skill_dir, name)
    pairs = build_arcnames(skill_dir, name)

    skill_id = find_existing_skill_id(client, name)
    if skill_id is None:
        resp = client.beta.skills.create(files=to_upload_files(pairs), display_title=name)
        return DeployResult(name, resp.id, str(resp.latest_version), "created")

    resp = client.beta.skills.versions.create(skill_id, files=to_upload_files(pairs))
    return DeployResult(name, skill_id, str(resp.version), "versioned")


def select_skill_dirs(selection: str) -> list[Path]:
    """Resolve the ``--skill`` selection to skill directories.

    ``all`` returns every directory under ``.claude/skills/``; any other value must name an existing
    directory.
    """
    if not SKILLS_ROOT.is_dir():
        raise ValueError(f"skills root not found: {SKILLS_ROOT}")
    if selection == "all":
        return sorted(d for d in SKILLS_ROOT.iterdir() if d.is_dir())
    target = SKILLS_ROOT / selection
    if not target.is_dir():
        available = ", ".join(sorted(d.name for d in SKILLS_ROOT.iterdir() if d.is_dir()))
        raise ValueError(f"unknown skill '{selection}'; available: {available}")
    return [target]


def build_client():
    """Construct the Anthropic client from ANTHROPIC_API_KEY (imported lazily)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy skills to Claude Managed Agents")
    parser.add_argument(
        "--skill",
        default="all",
        help="'all' or a single skill directory name under .claude/skills/",
    )
    args = parser.parse_args(argv)

    skill_dirs = select_skill_dirs(args.skill)
    client = build_client()

    results = [deploy_skill(client, skill_dir) for skill_dir in skill_dirs]
    for r in results:
        print(f"{r.action}: {r.name} -> {r.skill_id} @ version {r.version}")

    # Emit a GitHub step summary when running in Actions.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("### Skills deployed\n\n")
            for r in results:
                fh.write(f"- `{r.name}` — {r.action}, `{r.skill_id}` @ version `{r.version}`\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
