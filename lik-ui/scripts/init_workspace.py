"""One-shot initializer for the ``lik-ui`` Claude Workspace.

Creates the Knowledge Search **agent** and its **environment** in the ``lik-ui`` workspace
from the definitions hardcoded below, then appends the new agent to the checked-in roster
``src/lik_ui/agents.toml`` (commit it and redeploy to offer the agent) and prints the
``LIK_UI_ANTHROPIC_API_KEY`` line to paste into a copy of ``infra/ssm-secrets.example`` (consumed by
``infra/set-ssm-secrets.sh``). It needs only a ``lik-ui``-scoped API key and has no runtime
dependency on the org ``Default`` workspace or on any source resource IDs — the source
definitions are baked in as constants.

The API key itself is NOT created here: Anthropic does not expose programmatic API-key
creation (Console-only, by design), so create it by hand in the Console for the ``lik-ui``
workspace and hand it to this script. Which workspace the created resources land in is
determined by that key, not by the definitions.

Usage:
  LIK_UI_ANTHROPIC_API_KEY=sk-ant-... uv run python scripts/init_workspace.py
  uv run python scripts/init_workspace.py --model claude-opus-4-8 --dry-run
  uv run python scripts/init_workspace.py --target-key sk-ant-... --env-name lik-ui

If desired before running the above to refresh the hardcoded definitions (run against the
workspace that currently owns the source agent+env — the org ``Default`` workspace):

  LIK_UI_ANTHROPIC_API_KEY=<default-ws key> uv run python -c "import anthropic; \
    c=anthropic.Anthropic(); \
    print(c.beta.agents.retrieve('<source_agent_id>').model_dump_json(indent=2)); \
    print(c.beta.environments.retrieve('<source_env_id>').model_dump_json(indent=2))"

Paste the two JSON objects into ``AGENT_DEFINITION`` / ``ENV_DEFINITION`` below (keep only
the create-relevant keys — see the field lists), then flip ``DEFINITIONS_CAPTURED`` to True.
Nothing here logs the API key; it prints only a redacted hint plus the API-key SSM line.
"""

import argparse
import sys
from pathlib import Path

import anthropic

# The checked-in roster this script appends to. Resolved against the script's own location
# (the source tree), NOT the installed package: the flow is append here -> commit -> redeploy.
AGENTS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "src" / "lik_ui" / "agents.toml"

# --- Hardcoded source definitions -------------------------------------------------------
# Snapshotted from the LIK Knowledge Search agent and its environment (see the capture
# one-liner in the module docstring; captured 2026-07-23 from the org Default workspace).
# These make the script self-contained: it recreates the resources in whatever workspace
# the API key belongs to, without reading the source.
#
# When the source agent/env change, re-run the capture one-liner and re-paste below.
# The create path refuses to run while DEFINITIONS_CAPTURED is False (a guard for the
# uncaptured placeholder state) so it can never create a hollow agent.
DEFINITIONS_CAPTURED = True

# Agent create fields (anthropic 0.116 beta.agents.create): name, model, system,
# mcp_servers, tools (preserve `mcp_toolset` entries + `default_config.permission_policy`),
# skills, description. `model` may be a bare string or {"id": ..., "speed": ...}.
AGENT_DEFINITION: dict = {
    "name": "Knowledge Search Agent",
    "model": {"id": "claude-sonnet-5", "speed": "standard"},
    "system": (
        "You are a knowledge search agent that answers user questions by querying across "
        "Confluence, Google Drive, Slack, and GitHub via their connected tools. Given a "
        "question, decide which source(s) are most likely to have the answer, search them, "
        "and synthesize a clear, concise response. Always cite where information came from "
        '(e.g. "per Confluence page X", "per #channel in Slack", "per GitHub issue #123", '
        '"per Drive file Y") including links when available. If multiple sources have '
        "relevant or conflicting information, note the discrepancy. If nothing relevant is "
        "found, say so plainly rather than guessing. Ask a clarifying question only if the "
        "request is too ambiguous to search effectively. Do not take destructive actions "
        "(e.g. editing or deleting content) — you are read-focused unless explicitly asked "
        "to post/write something and the tool supports it."
    ),
    "mcp_servers": [
        {"type": "url", "name": "atlassian", "url": "https://mcp.atlassian.com/v1/mcp"},
        {"type": "url", "name": "google-drive-drivemcp", "url": "https://drivemcp.googleapis.com/mcp/v1"},
        {"type": "url", "name": "slack", "url": "https://mcp.slack.com/mcp"},
        {"type": "url", "name": "github", "url": "https://api.githubcopilot.com/mcp"},
    ],
    "tools": [
        {
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
            "configs": [],
        },
        *[
            {
                "type": "mcp_toolset",
                "mcp_server_name": name,
                "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
                "configs": [
                    {"name": name, "enabled": True, "permission_policy": {"type": "always_allow"}}
                ],
            }
            for name in ("atlassian", "google-drive-drivemcp", "slack", "github")
        ],
    ],
    "skills": [],
    "description": "Answers questions by searching across Confluence, Google Drive, Slack, and GitHub.",
}

# Environment create fields (beta.environments.create): name (must be unique in the
# workspace), config (copied verbatim from the source — networking is `limited` with
# `allow_mcp_servers` so the agent can reach its declared MCP servers), description.
ENV_DEFINITION: dict = {
    "name": "lik-ui",
    "config": {
        "type": "cloud",
        "networking": {
            "type": "limited",
            "allow_mcp_servers": True,
            "allow_package_managers": False,
            "allowed_hosts": [],
        },
        "packages": {"type": "packages", "apt": [], "cargo": [], "gem": [], "go": [], "npm": [], "pip": []},
    },
    "description": None,
}

SSM_PREFIX = "$P/lik-ui"

# Deploy steps that pick up the new values, printed after the SSM block. The agent roster
# is committed in agents.toml (above); only the API key goes through SSM. Steps 2-3 run from
# infra/ (see infra/ssm-secrets.example's header for the $P path-prefix substitution); the
# roster is baked into the image at build time, so step 4 rebuilds+redeploys via CI.
NEXT_STEPS = (
    "1. Commit + merge the updated src/lik_ui/agents.toml (the new roster entry above).\n"
    "2. Copy infra/ssm-secrets.example to a temp file and set its LIK_UI_ANTHROPIC_API_KEY\n"
    "   line to the one above.\n"
    "3. From infra/:  ./set-ssm-secrets.sh COPY_OF_ssm-secrets.example\n"
    "4. Run the \"Build and deploy images\" GitHub Action for lik-ui\n"
    "   (gh workflow run deploy-images.yml -f service=lik-ui). It rebuilds the image with the\n"
    "   updated agents.toml and redeploys the app."
)


class EnvNameConflict(Exception):
    """The environment name already exists in the workspace (create returned 409)."""


def _hr(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def redact(key: str | None) -> str:
    """A logging-safe hint for an API key — never the full value."""
    if not key:
        return "(none)"
    return f"{key[:10]}…{key[-4:]}" if len(key) > 16 else "sk-ant-…"


def resolve_target_key(cli_key: str | None) -> str | None:
    """The lik-ui key: ``--target-key`` wins, else ``LIK_UI_ANTHROPIC_API_KEY`` (with .env
    support via Settings, mirroring smoke.py). Returns None when unset."""
    if cli_key:
        return cli_key
    from lik_ui.settings import Settings  # lazy: keeps the module importable without config

    return Settings().anthropic_api_key or None


def _skill_type(skill: dict) -> str | None:
    return skill.get("type") if isinstance(skill, dict) else getattr(skill, "type", None)


def partition_skills(defn: dict) -> tuple[list, list]:
    """Split a definition's skills into (anthropic_prebuilt, custom). Custom skills are
    workspace-scoped ``skill_...`` IDs that will not exist in a fresh workspace, so the
    create path drops them (or errors under --strict-skills)."""
    skills = defn.get("skills") or []
    anthropic_skills = [s for s in skills if _skill_type(s) == "anthropic"]
    custom_skills = [s for s in skills if _skill_type(s) == "custom"]
    return anthropic_skills, custom_skills


def build_agent_payload(
    defn: dict, *, model: str | None = None, name: str | None = None, strict_skills: bool = False
) -> tuple[dict, list]:
    """Create-shaped kwargs for beta.agents.create, plus the list of dropped custom skills.

    Overrides win over the snapshot; omitted optional fields are left out entirely so the
    API applies its own defaults rather than receiving explicit nulls/empties."""
    anthropic_skills, custom_skills = partition_skills(defn)
    if custom_skills and strict_skills:
        ids = ", ".join(str(_skill_id(s)) for s in custom_skills)
        raise ValueError(
            f"agent references custom skills not present in the target workspace: {ids}. "
            "Recreate them there first, or drop --strict-skills to skip them."
        )

    payload: dict = {
        "name": name or defn["name"],
        "model": model or defn["model"],
    }
    for key in ("system", "mcp_servers", "tools", "description"):
        value = defn.get(key)
        if value:
            payload[key] = value
    if anthropic_skills:
        payload["skills"] = anthropic_skills
    return payload, custom_skills


def build_env_payload(defn: dict, *, name: str | None = None) -> dict:
    """Create-shaped kwargs for beta.environments.create."""
    payload: dict = {"name": name or defn["name"], "config": defn["config"]}
    if defn.get("description"):
        payload["description"] = defn["description"]
    return payload


def _skill_id(skill: dict):
    return skill.get("skill_id") if isinstance(skill, dict) else getattr(skill, "skill_id", None)


def create_resources(client, agent_payload: dict, env_payload: dict) -> tuple[str, str]:
    """Create the environment first (its unique-name 409 is the likeliest early failure —
    fail before creating an orphan agent), then the agent. Returns (agent_id, env_id)."""
    try:
        env = client.beta.environments.create(**env_payload)
    except Exception as exc:  # noqa: BLE001 - re-raised, narrowed below
        conflict = getattr(anthropic, "ConflictError", ())
        if getattr(exc, "status_code", None) == 409 or isinstance(exc, conflict):
            raise EnvNameConflict(env_payload["name"]) from exc
        raise
    agent = client.beta.agents.create(**agent_payload)
    return agent.id, env.id


def format_ssm_block(api_key: str | None, prefix: str = SSM_PREFIX) -> str:
    """The API-key line to paste into a copy of infra/ssm-secrets.example. No quotes, no trailing
    space — set-ssm-secrets.sh takes the value as everything after the first '='. The agent
    roster is no longer an SSM value; it lives in agents.toml (see append_agent_to_config)."""
    key_value = api_key or "sk-ant-…  # create in the Console for the lik-ui workspace"
    return f"{prefix}/LIK_UI_ANTHROPIC_API_KEY={key_value}"


def format_agent_block(agent_id: str, env_id: str) -> str:
    """One ``[[agents]]`` TOML block for the roster file."""
    return f'[[agents]]\nagent_id = "{agent_id}"\nenvironment_id = "{env_id}"\n'


def append_agent_to_config(agent_id: str, env_id: str, path: Path = AGENTS_CONFIG_PATH) -> Path:
    """Append a ``[[agents]]`` block to the roster file, separated from existing content by
    one blank line. Text append, not parse-and-rewrite, so existing entries and comments are
    left untouched. Returns the written path."""
    block = format_agent_block(agent_id, env_id)
    existing = path.read_text() if path.is_file() else ""
    prefix = existing.rstrip("\n") + "\n\n" if existing.strip() else ""
    path.write_text(prefix + block)
    return path


def preflight(client) -> None:
    """Fail fast (and offline) if the installed SDK lacks the beta surface we call."""
    for path in ("agents", "environments"):
        ns = getattr(client.beta, path, None)
        if ns is None or not hasattr(ns, "create"):
            raise SystemExit(f"anthropic SDK missing beta.{path}.create — upgrade the SDK")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize the lik-ui Claude Workspace (agent + environment).")
    p.add_argument("--model", help="Override the agent's LLM model (default: the snapshot's model).")
    p.add_argument("--agent-name", help="Override the created agent's name.")
    p.add_argument("--env-name", help="Override the created environment's name (must be unique).")
    p.add_argument("--target-key", help="lik-ui API key (else LIK_UI_ANTHROPIC_API_KEY).")
    p.add_argument("--strict-skills", action="store_true", help="Error (don't drop) on custom skills.")
    p.add_argument("--dry-run", action="store_true", help="Print payloads and the would-be SSM block; create nothing.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    agent_payload, dropped = build_agent_payload(
        AGENT_DEFINITION, model=args.model, name=args.agent_name, strict_skills=args.strict_skills
    )
    env_payload = build_env_payload(ENV_DEFINITION, name=args.env_name)

    if dropped:
        ids = ", ".join(str(_skill_id(s)) for s in dropped)
        print(f"[warn] dropping {len(dropped)} custom skill(s) not in the target workspace: {ids}")
        print("       recreate them in lik-ui and re-add, or use --strict-skills to hard-fail.")

    _hr("payloads")
    print(f"agent: name={agent_payload['name']!r} model={agent_payload['model']!r} "
          f"tools={len(agent_payload.get('tools', []))} mcp_servers={len(agent_payload.get('mcp_servers', []))} "
          f"skills={len(agent_payload.get('skills', []))}")
    print(f"environment: name={env_payload['name']!r}")

    target_key = resolve_target_key(args.target_key)

    if args.dry_run:
        _hr("dry run — nothing created")
        if not DEFINITIONS_CAPTURED:
            print("[note] definitions are still PLACEHOLDER (DEFINITIONS_CAPTURED=False).")
        print(f"target key: {redact(target_key)}")
        _hr(f"would append to {AGENTS_CONFIG_PATH}")
        print(format_agent_block("agent_<new>", "env_<new>"), end="")
        _hr("paste into a copy of infra/ssm-secrets.example")
        print(format_ssm_block(target_key))
        _hr("then deploy")
        print(NEXT_STEPS)
        return 0

    if not DEFINITIONS_CAPTURED:
        raise SystemExit(
            "AGENT_DEFINITION/ENV_DEFINITION are placeholders. Capture them (see the module "
            "docstring), flip DEFINITIONS_CAPTURED=True, then re-run. Use --dry-run to preview."
        )
    if not target_key:
        raise SystemExit("no API key: pass --target-key or set LIK_UI_ANTHROPIC_API_KEY (lik-ui workspace key).")

    client = anthropic.Anthropic(api_key=target_key)
    preflight(client)

    print(f"\ncreating in the workspace of key {redact(target_key)} …")
    try:
        agent_id, env_id = create_resources(client, agent_payload, env_payload)
    except EnvNameConflict as exc:
        raise SystemExit(
            f"environment name {str(exc)!r} already exists in this workspace — "
            "pass a different --env-name."
        )
    print(f"created agent {agent_id} and environment {env_id}")

    append_agent_to_config(agent_id, env_id)
    _hr(f"appended to {AGENTS_CONFIG_PATH}")
    print(format_agent_block(agent_id, env_id), end="")
    print("commit this file and redeploy to offer the new agent.")

    _hr("paste into a copy of infra/ssm-secrets.example")
    print(format_ssm_block(target_key))
    _hr("then deploy")
    print(NEXT_STEPS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
