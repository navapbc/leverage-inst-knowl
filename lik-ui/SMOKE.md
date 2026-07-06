# lik-ui smoke test

End-to-end acceptance checks against the real Anthropic/Google/Atlassian services. This is
a manual acceptance run, not CI — it creates real vaults, credentials, and sessions, and
requires clicking through OAuth consent. Run it once when you have credentials and the two
external prerequisites in place.

## Prerequisites

- **Stable `LIK_UI_LIKMCP_RESOURCE_URL`** — a non-ngrok URL that won't rotate (credentials
  are keyed by exact URL; a rotating URL silently stops matching).
- **Agent auto-approve** — the MCP permission policy on `LIK_UI_DEFAULT_AGENT_ID` set to
  auto-approve, or chat will block waiting for approvals lik-ui doesn't render.
- **Registered redirect URIs** on a reachable host:
  - Google app-login client → `<APP_BASE_URL>/auth/callback`
  - Google lik-mcp data client → `<APP_BASE_URL>/connections/callback`
  - Atlassian DCR uses `<APP_BASE_URL>/connections/callback` (registered automatically).
- Real values for all `LIK_UI_*` secrets in `.env` (see `.env.example`), `LIK_UI_ENV=prod`.
- Postgres running with the schema applied.

## Automated part (SDK surface + live session)

```
# Credential-free: confirms the SDK method names/signatures chat.py, vault.py, agents.py call.
uv run python scripts/smoke.py surface

# Full: also retrieves the agent and runs one real session, dumping raw event shapes.
uv run python scripts/smoke.py all
```

Stages 2–4 were run during implementation and used to correct `chat.py`:

- The send/stream path is `sessions.events.send(session_id, events=[{type: "user.message",
  content: [{type: "text", text: ...}]}])` then `sessions.events.stream(session_id)` — NOT a
  `sessions.stream(input=...)` call.
- A turn terminates with a `session.status_idle` event (confirmed live). `session.error`
  events for unconnected MCP servers stream first, and the agent still answers.

Re-run `surface` after any SDK upgrade to catch drift. What remains for a full live pass is
only the browser OAuth legs below (Stage 4 ran with an empty vault, so tool *use* — the
`agent.mcp_tool_use` event — has not been exercised end to end yet).

## Manual part (browser OAuth legs)

The consent flows need a browser and can't be scripted:

```
docker compose up -d db
uv run python -m lik_ui        # or `docker compose up`
```

Then in a browser at `<APP_BASE_URL>`:

1. **Log in** with Google → you land on the agent picker; confirm your email shows.
   Verify a `users` row and a `user_vaults` mapping now exist.
2. **Select the agent** → the connections page lists the servers it declares, each "Not
   connected".
3. **Connect lik-mcp** → Google consent → back on connections, now "Connected". Verify a
   credential exists in your vault keyed by exactly `LIK_UI_LIKMCP_RESOURCE_URL`.
4. **Connect Atlassian** → Atlassian consent → "Connected".
5. **Start chatting** → send a question that needs a source (e.g. "What Confluence pages
   mention project X?"). Confirm: streamed answer, tool activity appears with no approval
   prompt (auto-approve), and the answer reflects real data.
6. **Reopen the conversation** later → it resumes the same session (no new session created).
7. **Revoke a credential** (archive it via the API) and chat again → a reconnect nudge
   appears for that source; chat stays usable.
