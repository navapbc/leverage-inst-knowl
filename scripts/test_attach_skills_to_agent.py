"""Tests for the agent-attach bootstrap. Fakes the Anthropic client — no network, no key."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import attach_skills_to_agent as attach
import deploy_skills as ds


class FakeAgents:
    def __init__(self, agent):
        self._agent = agent
        self.update_calls = []

    def retrieve(self, agent_id):
        return self._agent

    def update(self, agent_id, **kwargs):
        self.update_calls.append({"agent_id": agent_id, **kwargs})
        # reflect the new skills so the post-update retrieve/print is coherent
        self._agent = SimpleNamespace(
            **{**vars(self._agent), "skills": [SimpleNamespace(**s) for s in kwargs["skills"]]}
        )
        return self._agent


class FakeClient:
    def __init__(self, agent, skills_list):
        self.beta = SimpleNamespace(
            agents=FakeAgents(agent),
            skills=SimpleNamespace(list=lambda: [SimpleNamespace(id=i, display_title=t) for i, t in skills_list]),
        )


def _skill(type_, skill_id, version=None):
    return SimpleNamespace(type=type_, skill_id=skill_id, version=version)


# --- merge_skills ------------------------------------------------------------------------------


def test_merge_into_empty():
    assert attach.merge_skills([], ["a", "b"]) == [
        {"type": "custom", "skill_id": "a", "version": "latest"},
        {"type": "custom", "skill_id": "b", "version": "latest"},
    ]


def test_merge_preserves_unrelated_skills():
    existing = [_skill("anthropic", "xlsx")]
    assert attach.merge_skills(existing, ["a"]) == [
        {"type": "anthropic", "skill_id": "xlsx"},
        {"type": "custom", "skill_id": "a", "version": "latest"},
    ]


def test_merge_replaces_pinned_target_with_latest():
    existing = [_skill("custom", "a", "1784730000000000")]
    assert attach.merge_skills(existing, ["a"]) == [
        {"type": "custom", "skill_id": "a", "version": "latest"},
    ]


def test_merge_is_idempotent_against_current():
    # After merging, re-normalizing the current agent skills must equal the merge (no diff).
    existing = [_skill("custom", "a", "latest")]
    merged = attach.merge_skills(existing, ["a"])
    agent = SimpleNamespace(skills=[SimpleNamespace(**s) for s in merged])
    assert attach._current_skills_as_dicts(agent) == merged


# --- resolve_skill_ids -------------------------------------------------------------------------


def test_resolve_skill_ids_errors_when_missing():
    client = FakeClient(agent=SimpleNamespace(), skills_list=[("id_a", "lik-a")])
    with pytest.raises(ValueError):
        attach.resolve_skill_ids(client, ["lik-a", "lik-missing"])


# --- main (dry-run vs apply) -------------------------------------------------------------------


def _wire(monkeypatch, tmp_path, client):
    """Point ds at a fake client and a temp skills root with one skill dir 'lik-a'."""
    d = tmp_path / "lik-a"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: lik-a\ndescription: x\n---\n# a\n", encoding="utf-8")
    monkeypatch.setattr(ds, "SKILLS_ROOT", tmp_path)
    monkeypatch.setattr(ds, "build_client", lambda: client)


def test_main_dry_run_does_not_update(tmp_path, monkeypatch):
    agent = SimpleNamespace(version=7, name="A", model=SimpleNamespace(id="claude-opus-4-8"),
                            system="sys", skills=[], tools=[], mcp_servers=[])
    client = FakeClient(agent, skills_list=[("id_a", "lik-a")])
    _wire(monkeypatch, tmp_path, client)

    rc = attach.main(["--skill", "lik-a", "--agent-id", "agent_1"])
    assert rc == 0
    assert client.beta.agents.update_calls == []  # dry run


def test_main_apply_updates_pinned_latest_preserving_fields(tmp_path, monkeypatch):
    agent = SimpleNamespace(version=7, name="A", model=SimpleNamespace(id="claude-opus-4-8"),
                            system="sys", skills=[], tools=[], mcp_servers=[])
    client = FakeClient(agent, skills_list=[("id_a", "lik-a")])
    _wire(monkeypatch, tmp_path, client)

    rc = attach.main(["--skill", "lik-a", "--agent-id", "agent_1", "--apply"])
    assert rc == 0
    call = client.beta.agents.update_calls[0]
    assert call["version"] == 7
    assert call["name"] == "A"
    assert call["model"] == "claude-opus-4-8"
    assert call["skills"] == [{"type": "custom", "skill_id": "id_a", "version": "latest"}]


def test_main_apply_idempotent_when_already_attached(tmp_path, monkeypatch):
    agent = SimpleNamespace(version=7, name="A", model=SimpleNamespace(id="claude-opus-4-8"),
                            system=None, skills=[_skill("custom", "id_a", "latest")], tools=[], mcp_servers=[])
    client = FakeClient(agent, skills_list=[("id_a", "lik-a")])
    _wire(monkeypatch, tmp_path, client)

    rc = attach.main(["--skill", "lik-a", "--agent-id", "agent_1", "--apply"])
    assert rc == 0
    assert client.beta.agents.update_calls == []  # already attached -> no write
