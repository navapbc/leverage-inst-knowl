import textwrap

import pytest
from fastapi.testclient import TestClient

from lik_ui.app import build_app
from lik_ui.settings import Settings


def test_env_prefix_and_list_property(monkeypatch):
    monkeypatch.setenv("LIK_UI_HTTP_ALLOWED_HOSTS", "localhost, 127.0.0.1 , example.com")
    monkeypatch.setenv("LIK_UI_DB_HOST", "dbhost")
    s = Settings()
    assert s.db_host == "dbhost"
    assert s.allowed_hosts == ["localhost", "127.0.0.1", "example.com"]


def test_conninfo_builds_libpq_string():
    s = Settings(db_host="h", db_port=5555, db_name="likuidb_test", db_user="u", db_password="p")
    assert "host=h port=5555 dbname=likuidb_test user=u password=p" in s.conninfo


def _roster(tmp_path, body: str):
    """Write a roster TOML to a temp file and return its path."""
    path = tmp_path / "agents.toml"
    path.write_text(textwrap.dedent(body))
    return path


def test_shipped_roster_parses_to_at_least_one_agent():
    # The default packaged agents.toml must be valid and non-empty (guards the seeded file).
    roster = Settings(env="test").agent_roster
    assert len(roster) >= 1
    assert all(e.agent_name and e.environment_name for e in roster)


def test_shipped_roster_agents_reference_declared_sections():
    # Guards against a section rename/typo leaving an agent pointing at an undeclared section —
    # which would silently drop it into the default group as non-management (unhidden).
    s = Settings(env="test")
    declared = {sec.name for sec in s.agent_sections}
    for entry in s.agent_roster:
        assert entry.section == "" or entry.section in declared, (
            f"{entry.agent_name!r} references undeclared section {entry.section!r}"
        )


def test_shipped_roster_hides_catalog_registration_as_management():
    # The Catalog Registration Agent writes to the shared Catalog, so it must live in a
    # management (hidden-by-default) section.
    s = Settings(env="test")
    catalog = next(e for e in s.agent_roster if e.agent_name == "Catalog Registration Agent")
    assert catalog.is_management is True


def test_agent_roster_lists_configured_agents_in_file_order(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Agent X"
        environment = "Env X"

        [[agents]]
        agent = "Agent Y"
        environment = "Env Y"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(e.agent_name, e.environment_name) for e in s.agent_roster] == [
        ("Agent X", "Env X"),
        ("Agent Y", "Env Y"),
    ]


def test_agent_roster_uses_default_environment_when_omitted(tmp_path):
    path = _roster(
        tmp_path,
        """
        default_environment = "Env Default"

        [[agents]]
        agent = "Agent A"

        [[agents]]
        agent = "Agent B"
        environment = "Env Special"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(e.agent_name, e.environment_name) for e in s.agent_roster] == [
        ("Agent A", "Env Default"),  # inherits the top-level default
        ("Agent B", "Env Special"),  # own environment overrides the default
    ]


def test_agent_roster_environment_empty_when_no_default_and_none_set(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Agent A"
        """,
    )
    assert Settings(env="test", agents_config_path=path).agent_roster[0].environment_name == ""


def test_agent_roster_empty_when_file_has_no_entries(tmp_path):
    assert Settings(env="test", agents_config_path=_roster(tmp_path, "")).agent_roster == []


def test_agent_roster_empty_when_file_missing(tmp_path):
    assert Settings(env="test", agents_config_path=tmp_path / "nope.toml").agent_roster == []


def test_agent_roster_skips_entry_missing_agent_name(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        environment = "Env Orphan"

        [[agents]]
        agent = "Agent OK"
        environment = "Env OK"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    assert [(e.agent_name, e.environment_name) for e in s.agent_roster] == [("Agent OK", "Env OK")]


def test_agent_roster_resolves_section_and_management_flag(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[sections]]
        name = "Knowledge"

        [[sections]]
        name = "Management"
        management = true

        [[agents]]
        agent = "Searcher"
        section = "Knowledge"

        [[agents]]
        agent = "Registrar"
        section = "Management"
        """,
    )
    s = Settings(env="test", agents_config_path=path)
    by_name = {e.agent_name: e for e in s.agent_roster}
    assert by_name["Searcher"].section == "Knowledge"
    assert by_name["Searcher"].is_management is False
    assert by_name["Registrar"].section == "Management"
    assert by_name["Registrar"].is_management is True


def test_agent_roster_parses_user_prompt(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        user_prompt = "Ask me anything about projects."
        """,
    )
    entry = Settings(env="test", agents_config_path=path).agent_roster[0]
    assert entry.user_prompt == "Ask me anything about projects."


def test_agent_roster_user_prompt_defaults_empty_when_omitted(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        """,
    )
    assert Settings(env="test", agents_config_path=path).agent_roster[0].user_prompt == ""


def test_agent_roster_user_prompt_strips_whitespace(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        user_prompt = "   "
        """,
    )
    assert Settings(env="test", agents_config_path=path).agent_roster[0].user_prompt == ""


def test_shipped_roster_agents_all_carry_a_user_prompt():
    # Each shipped agent should invite the user with a concise prompt above the transcript.
    for entry in Settings(env="test").agent_roster:
        assert entry.user_prompt, f"{entry.agent_name!r} is missing a user_prompt"


def test_agent_roster_parses_session_title_prefix(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        session_title_prefix = "Search"
        """,
    )
    entry = Settings(env="test", agents_config_path=path).agent_roster[0]
    assert entry.session_title_prefix == "Search"


def test_agent_roster_session_title_prefix_defaults_empty_when_omitted(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        """,
    )
    assert Settings(env="test", agents_config_path=path).agent_roster[0].session_title_prefix == ""


def test_agent_roster_session_title_prefix_strips_whitespace(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        session_title_prefix = "   "
        """,
    )
    assert Settings(env="test", agents_config_path=path).agent_roster[0].session_title_prefix == ""


def test_shipped_roster_agents_all_carry_a_session_title_prefix():
    # Each shipped agent should carry a short prefix so session titles stay scannable.
    for entry in Settings(env="test").agent_roster:
        assert entry.session_title_prefix, f"{entry.agent_name!r} is missing a session_title_prefix"


def test_agent_roster_parses_scheduling_fields(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Catalog Registration Agent"
        schedulable = true
        max_runtime = 900
        auto_approve = [
            { server = "lik-mcp", tool = "register_catalog_entry" },
            { server = "lik-mcp", tool = "list_catalog_entries" },
        ]
        """,
    )
    entry = Settings(env="test", agents_config_path=path).agent_roster[0]
    assert entry.schedulable is True
    assert entry.max_runtime == 900
    assert [(t.server, t.tool) for t in entry.auto_approve] == [
        ("lik-mcp", "register_catalog_entry"),
        ("lik-mcp", "list_catalog_entries"),
    ]


def test_agent_roster_scheduling_fields_default_safely_when_omitted(tmp_path):
    from lik_ui.settings import DEFAULT_MAX_RUNTIME_SECONDS

    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        """,
    )
    entry = Settings(env="test", agents_config_path=path).agent_roster[0]
    # Not schedulable by default — an agent must be explicitly marked unattended-safe.
    assert entry.schedulable is False
    assert entry.auto_approve == []
    assert entry.max_runtime == DEFAULT_MAX_RUNTIME_SECONDS


def test_agent_roster_auto_approve_skips_entries_missing_tool(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Searcher"
        auto_approve = [
            { server = "lik-mcp", tool = "register_catalog_entry" },
            { server = "lik-mcp" },
        ]
        """,
    )
    entry = Settings(env="test", agents_config_path=path).agent_roster[0]
    assert [(t.server, t.tool) for t in entry.auto_approve] == [("lik-mcp", "register_catalog_entry")]


def test_agent_sections_preserve_declaration_order(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[sections]]
        name = "Management"
        management = true

        [[sections]]
        name = "Knowledge"
        """,
    )
    sections = Settings(env="test", agents_config_path=path).agent_sections
    assert [(s.name, s.is_management) for s in sections] == [("Management", True), ("Knowledge", False)]


def test_agent_without_section_falls_into_default_group(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[sections]]
        name = "Knowledge"

        [[agents]]
        agent = "Loner"
        """,
    )
    entry = Settings(env="test", agents_config_path=path).agent_roster[0]
    assert entry.section == ""
    assert entry.is_management is False


def test_agent_referencing_undeclared_section_is_not_management(tmp_path):
    path = _roster(
        tmp_path,
        """
        [[agents]]
        agent = "Orphan"
        section = "Nowhere"
        """,
    )
    entry = Settings(env="test", agents_config_path=path).agent_roster[0]
    assert entry.section == "Nowhere"
    assert entry.is_management is False  # undeclared section -> default, non-management


def test_require_production_config_raises_when_unconfigured():
    s = Settings(env="prod")  # missing session secret, oauth, api key
    with pytest.raises(RuntimeError) as exc:
        s.require_production_config()
    assert "LIK_UI_SESSION_SECRET" in str(exc.value)


def test_require_production_config_raises_on_empty_roster(tmp_path):
    # All secrets present, but the roster file is empty -> fail closed, naming the roster.
    s = Settings(
        env="prod",
        session_secret="s",
        app_oauth_client_id="id",
        app_oauth_client_secret="secret",
        anthropic_api_key="sk-ant-x",
        agents_config_path=_roster(tmp_path, ""),
    )
    with pytest.raises(RuntimeError) as exc:
        s.require_production_config()
    assert "roster" in str(exc.value)


def test_require_production_config_passes_when_stub():
    Settings(env="local").require_production_config()  # no raise


def test_app_boots_and_healthz_ok():
    app = build_app(Settings(env="test"))
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
