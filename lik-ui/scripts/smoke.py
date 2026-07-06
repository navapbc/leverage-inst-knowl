"""End-to-end smoke checks for lik-ui against the REAL Anthropic Managed Agents API.

Unit tests use fakes; this script exercises the parts fakes can't verify — the actual
SDK method signatures and the live session event shapes that chat.py assumes. It does NOT
cover the browser OAuth legs (Google/Atlassian consent); run those by hand per SMOKE.md.

Stages (each independent; later stages need more setup):

  1. config      — Settings load + fail-closed check. No network.
  2. surface     — introspect the installed anthropic SDK's beta.{sessions,vaults,agents}
                   methods and signatures. No credentials needed. Confirms the names/args
                   chat.py, vault.py, and agents.py call actually exist.
  3. agent       — retrieve AGENT_ID and print its declared mcp_servers. Needs API key.
  4. session     — create a throwaway vault, create a session for the agent, send one
                   message, and DUMP every raw stream event (type + attributes) so the
                   real event shape can be reconciled against chat.py. Needs API key.
                   Cleans up the session and vault at the end.

Usage:
  uv run python scripts/smoke.py surface          # credential-free
  LIK_UI_ANTHROPIC_API_KEY=... LIK_UI_DEFAULT_AGENT_ID=... LIK_UI_DEFAULT_ENVIRONMENT_ID=... \
    uv run python scripts/smoke.py all

Nothing here logs tokens. It prints structural info (method names, event types/attrs).
"""

import inspect
import sys

from lik_ui.settings import Settings


def _hr(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def stage_config() -> Settings:
    _hr("1. config")
    settings = Settings()
    print(f"env={settings.env!r} is_stub={settings.is_stub}")
    try:
        settings.require_production_config()
        print("require_production_config: OK")
    except RuntimeError as exc:
        print(f"require_production_config: {exc}")
    print(f"agents configured: {[a.label for a in settings.agents]}")
    print(f"likmcp_resource_url={settings.likmcp_resource_url!r}")
    return settings


def _describe(obj, path: str) -> None:
    """Print callable attributes and their signatures for one SDK namespace."""
    print(f"\n-- {path}")
    for name in sorted(n for n in dir(obj) if not n.startswith("_")):
        try:
            attr = getattr(obj, name)
        except Exception:  # noqa: BLE001
            continue
        if callable(attr):
            try:
                sig = str(inspect.signature(attr))
            except (ValueError, TypeError):
                sig = "(...)"
            print(f"   {name}{sig}")
        else:
            print(f"   {name}  [namespace]")


def stage_surface() -> None:
    _hr("2. surface (SDK introspection — no credentials)")
    import anthropic

    client = anthropic.Anthropic(api_key="sk-not-used-for-introspection")
    beta = client.beta
    for path in ("agents", "sessions", "vaults"):
        ns = getattr(beta, path, None)
        if ns is None:
            print(f"\n-- client.beta.{path}: MISSING")
            continue
        _describe(ns, f"client.beta.{path}")
        # One level deeper for the sub-resources lik-ui uses.
        for sub in ("credentials", "events", "stream"):
            subns = getattr(ns, sub, None)
            if subns is not None and not callable(subns):
                _describe(subns, f"client.beta.{path}.{sub}")
    print("\nReconcile against: chat.py send_and_stream (sessions.create/stream),")
    print("vault.py (vaults.create, vaults.credentials.create/list), agents.py (agents.retrieve).")


def stage_agent(settings: Settings):
    _hr("3. agent retrieve")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = client.beta.agents.retrieve(settings.default_agent_id)
    servers = getattr(agent, "mcp_servers", None) or []
    print(f"agent {settings.default_agent_id}: {len(servers)} declared MCP server(s)")
    for s in servers:
        print(f"   name={getattr(s, 'name', '?')!r} url={getattr(s, 'url', '?')!r}")
    return client


def stage_session(settings: Settings, client) -> None:
    _hr("4. session create + one message (raw event dump)")
    vault = client.beta.vaults.create(display_name="lik-ui-smoke", metadata={"external_user_id": "smoke"})
    print(f"created throwaway vault {vault.id}")
    try:
        session = client.beta.sessions.create(
            agent=settings.default_agent_id,
            environment_id=settings.default_environment_id,
            vault_ids=[vault.id],
        )
        print(f"created session {session.id}")
        print("\n-- raw stream events (reconcile with chat.py normalization):")
        events = client.beta.sessions.events
        events.send(
            session.id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": "Say hello in one short sentence."}]}],
        )
        for i, event in enumerate(events.stream(session.id)):
            etype = getattr(event, "type", "")
            attrs = {k: getattr(event, k, None) for k in ("type", "name", "mcp_server_name", "content", "error")}
            print(f"   [{i}] {type(event).__name__} {attrs}")
            if etype == "end_turn" or etype.startswith(("session.status_idle", "session.status_terminated")) or i > 60:
                break
    finally:
        try:
            client.beta.sessions.delete(session.id)  # best-effort cleanup
        except Exception as exc:  # noqa: BLE001
            print(f"(session cleanup skipped: {exc})")
        try:
            client.beta.vaults.delete(vault.id)
        except Exception as exc:  # noqa: BLE001
            print(f"(vault cleanup skipped: {exc})")


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else "surface"
    settings = stage_config()

    if stage in ("surface", "all"):
        stage_surface()
    if stage in ("agent", "session", "all"):
        if not settings.anthropic_api_key or not settings.default_agent_id:
            print("\n[skip] stages 3-4 need LIK_UI_ANTHROPIC_API_KEY and LIK_UI_DEFAULT_AGENT_ID.")
            return
        client = stage_agent(settings)
        if stage in ("session", "all"):
            stage_session(settings, client)


if __name__ == "__main__":
    main()
