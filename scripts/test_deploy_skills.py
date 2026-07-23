"""Tests for the skill deploy script.

These fake the Anthropic SDK client (mirroring lik-ui/tests/test_agents.py) so the deploy logic —
skill-id resolution, create-vs-version, upload packaging, and the two platform upload guards — is
exercised without the SDK or any network access.
"""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

import deploy_skills as ds


# --- fakes -------------------------------------------------------------------------------------


class FakeSkills:
    """Records create / versions.create calls and answers list() from a seeded set."""

    def __init__(self, existing=None):
        # existing: list of (skill_id, display_title)
        self._existing = [SimpleNamespace(id=i, display_title=t) for i, t in (existing or [])]
        self.create_calls = []
        self.version_calls = []
        self.versions = SimpleNamespace(create=self._version_create)

    def list(self):
        return list(self._existing)

    def create(self, *, files, display_title):
        self.create_calls.append({"files": files, "display_title": display_title})
        return SimpleNamespace(id="skill_new", latest_version=111)

    def _version_create(self, skill_id, *, files):
        self.version_calls.append({"skill_id": skill_id, "files": files})
        return SimpleNamespace(version=222)


class FakeClient:
    def __init__(self, existing=None):
        self.beta = SimpleNamespace(skills=FakeSkills(existing))


def make_skill(tmp_path: Path, name: str, dirname: str | None = None, extra: dict | None = None) -> Path:
    """Create a skill directory with a SKILL.md and optional extra files. Returns the dir path."""
    d = tmp_path / (dirname or name)
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n# {name}\n", encoding="utf-8")
    for rel, content in (extra or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


def arcnames(calls_files) -> list[str]:
    return [f[0] for f in calls_files]


# --- read_skill_name / validate ----------------------------------------------------------------


def test_read_skill_name(tmp_path):
    d = make_skill(tmp_path, "lik-demo")
    assert ds.read_skill_name(d) == "lik-demo"


def test_read_skill_name_missing_frontmatter(tmp_path):
    d = tmp_path / "lik-demo"
    d.mkdir()
    (d / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ds.read_skill_name(d)


def test_read_skill_name_missing_file(tmp_path):
    d = tmp_path / "lik-demo"
    d.mkdir()
    with pytest.raises(ValueError):
        ds.read_skill_name(d)


def test_validate_dir_name_mismatch(tmp_path):
    d = make_skill(tmp_path, "lik-demo", dirname="wrong-dir")
    with pytest.raises(ValueError):
        ds.validate_dir_name(d, "lik-demo")


# --- build_arcnames (upload packaging guards) --------------------------------------------------


def test_arcnames_nest_under_name_folder(tmp_path):
    d = make_skill(tmp_path, "lik-demo", extra={"reference.md": "detail", "nested/more.md": "x"})
    names = [a for a, _ in ds.build_arcnames(d, "lik-demo")]
    assert names == [
        "lik-demo/SKILL.md",
        "lik-demo/nested/more.md",
        "lik-demo/reference.md",
    ]


# --- deploy_skill: create vs version -----------------------------------------------------------


def test_deploy_new_skill_calls_create(tmp_path):
    d = make_skill(tmp_path, "lik-demo", extra={"reference.md": "detail"})
    client = FakeClient(existing=[])
    result = ds.deploy_skill(client, d)

    assert result.action == "created"
    assert result.skill_id == "skill_new"
    assert client.beta.skills.create_calls[0]["display_title"] == "lik-demo"
    assert client.beta.skills.version_calls == []
    assert arcnames(client.beta.skills.create_calls[0]["files"]) == [
        "lik-demo/SKILL.md",
        "lik-demo/reference.md",
    ]


def test_deploy_existing_skill_calls_version(tmp_path):
    d = make_skill(tmp_path, "lik-demo")
    client = FakeClient(existing=[("skill_abc", "lik-demo")])
    result = ds.deploy_skill(client, d)

    assert result.action == "versioned"
    assert result.skill_id == "skill_abc"
    assert client.beta.skills.create_calls == []
    assert client.beta.skills.version_calls[0]["skill_id"] == "skill_abc"


def test_deploy_ignores_unrelated_existing_skills(tmp_path):
    d = make_skill(tmp_path, "lik-demo")
    client = FakeClient(existing=[("xlsx_id", "xlsx"), ("other", "lik-other")])
    result = ds.deploy_skill(client, d)
    assert result.action == "created"  # no display_title match -> create


def test_deploy_rejects_name_dir_mismatch(tmp_path):
    d = make_skill(tmp_path, "lik-demo", dirname="wrong-dir")
    client = FakeClient(existing=[])
    with pytest.raises(ValueError):
        ds.deploy_skill(client, d)
    assert client.beta.skills.create_calls == []


# --- select_skill_dirs -------------------------------------------------------------------------


def test_select_all(tmp_path, monkeypatch):
    make_skill(tmp_path, "lik-a")
    make_skill(tmp_path, "lik-b")
    monkeypatch.setattr(ds, "SKILLS_ROOT", tmp_path)
    dirs = ds.select_skill_dirs("all")
    assert [d.name for d in dirs] == ["lik-a", "lik-b"]


def test_select_named(tmp_path, monkeypatch):
    make_skill(tmp_path, "lik-a")
    make_skill(tmp_path, "lik-b")
    monkeypatch.setattr(ds, "SKILLS_ROOT", tmp_path)
    dirs = ds.select_skill_dirs("lik-b")
    assert [d.name for d in dirs] == ["lik-b"]


def test_select_unknown_raises(tmp_path, monkeypatch):
    make_skill(tmp_path, "lik-a")
    monkeypatch.setattr(ds, "SKILLS_ROOT", tmp_path)
    with pytest.raises(ValueError):
        ds.select_skill_dirs("nope")
