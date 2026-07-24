"""Unit tests for scripts/init_workspace.py.

init_workspace is a thin orchestrator: it runs the repo-root deploy scripts (deploy_skills.py then
deploy_agents.py) against a target-workspace key and prints the SSM key line + next steps. The actual
deploy logic is tested in scripts/test_deploy_skills.py and scripts/test_deploy_agents.py; here we
cover key resolution, SSM formatting, the offline dry run, and that a real run shells out in the right
order with the key in the environment (subprocess is faked — no network).
"""

from types import SimpleNamespace

import pytest

from scripts import init_workspace as iw


@pytest.fixture(autouse=True)
def clean():
    """Override conftest's DB-backed autouse fixture — these tests never touch Postgres."""
    yield


# --- format_ssm_block -------------------------------------------------------------------


def test_ssm_block_is_api_key_only_no_trailing_space():
    block = iw.format_ssm_block("sk-ant-realkey")
    lines = block.split("\n")
    assert lines == ["$P/lik-ui/LIK_UI_ANTHROPIC_API_KEY=sk-ant-realkey"]
    assert "LIK_UI_AGENTS_CONFIG" not in block  # the roster is no longer an SSM value
    for line in lines:
        assert line == line.rstrip()  # set-ssm-secrets.sh takes value verbatim; no trailing space


def test_ssm_block_placeholder_when_no_key():
    block = iw.format_ssm_block(None)
    assert "LIK_UI_ANTHROPIC_API_KEY=sk-ant-…" in block
    assert "LIK_UI_AGENTS_CONFIG" not in block


# --- redact -----------------------------------------------------------------------------


def test_redact_never_reveals_full_key():
    key = "sk-ant-api03-abcdefghijklmnop-qrstuvwxyz"
    hint = iw.redact(key)
    assert key not in hint
    assert hint.startswith("sk-ant-api")
    assert iw.redact(None) == "(none)"
    assert iw.redact("short") == "sk-ant-…"


# --- resolve_target_key -----------------------------------------------------------------


def test_resolve_key_cli_wins():
    assert iw.resolve_target_key("sk-ant-cli") == "sk-ant-cli"


def test_resolve_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("LIK_UI_ANTHROPIC_API_KEY", "sk-ant-fromenv")
    assert iw.resolve_target_key(None) == "sk-ant-fromenv"


# --- main: dry run (offline) ------------------------------------------------------------


def test_main_dry_run_prints_block_and_deploys_nothing(capsys, monkeypatch):
    monkeypatch.delenv("LIK_UI_ANTHROPIC_API_KEY", raising=False)  # deterministic placeholder key line
    calls = []
    monkeypatch.setattr(iw, "run_deploy", lambda *a, **k: calls.append(a))

    rc = iw.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "LIK_UI_ANTHROPIC_API_KEY" in out
    assert "LIK_UI_AGENTS_CONFIG" not in out  # roster is no longer an SSM value
    assert calls == []  # dry run deploys nothing


def test_main_dry_run_appends_deploy_instructions(capsys, monkeypatch):
    monkeypatch.delenv("LIK_UI_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(iw, "run_deploy", lambda *a, **k: None)
    iw.main(["--dry-run"])
    out = capsys.readouterr().out
    assert "./set-ssm-secrets.sh COPY_OF_ssm-secrets.example" in out
    assert "gh secret set ANTHROPIC_API_KEY --env prod" in out  # repoint the shared CI deploy key
    assert "deploy-images.yml" in out  # rebuild+redeploy via the GitHub Action


# --- main: real run ---------------------------------------------------------------------


def test_main_requires_key(monkeypatch):
    monkeypatch.delenv("LIK_UI_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="no API key"):
        iw.main([])  # not a dry run, no key -> refuse


def test_main_deploys_skills_then_agents_with_key(monkeypatch):
    monkeypatch.delenv("LIK_UI_ANTHROPIC_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(iw, "run_deploy", lambda script, args, key: calls.append((script, args, key)))

    rc = iw.main(["--target-key", "sk-ant-target"])
    assert rc == 0
    assert calls == [
        ("deploy_skills.py", ["--skill", "all"], "sk-ant-target"),
        ("deploy_agents.py", ["--agent", "all"], "sk-ant-target"),
    ]


def test_run_deploy_passes_key_in_env_and_uses_repo_scripts(monkeypatch):
    recorded = {}

    def fake_run(cmd, env, check):
        recorded["cmd"] = cmd
        recorded["env"] = env
        recorded["check"] = check
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(iw.subprocess, "run", fake_run)
    iw.run_deploy("deploy_agents.py", ["--agent", "all"], "sk-ant-xyz")

    assert recorded["check"] is True
    assert recorded["env"]["ANTHROPIC_API_KEY"] == "sk-ant-xyz"
    assert str(iw.REPO_SCRIPTS / "deploy_agents.py") in recorded["cmd"]
    assert recorded["cmd"][:2] == ["uv", "run"]
