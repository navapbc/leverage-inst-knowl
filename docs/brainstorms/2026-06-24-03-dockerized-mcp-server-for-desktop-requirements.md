---
date: 2026-06-24
topic: dockerized-mcp-server-for-desktop
---

# Dockerized MCP Server for Claude Desktop Testing

## Summary

Run the lik-mcp server as an HTTP service in Docker Compose alongside Postgres, so testing
the Discovery Layer skills in Claude Desktop is a single `docker compose up` plus a URL
connection — instead of the local uv / Python 3.14 / absolute-path setup the README requires
today. The container serves over the same HTTP transport a cloud deploy would use, so `local`
and deployed differ only by environment, not by serving shape.

---

## Problem Frame

Testing the skills (`lik-sync-catalog-from-project-indexes`, `lik-query-project-index`) in Claude
Desktop means standing the server up locally. The current README path makes the tester install
uv, provision the Python 3.14 environment, create `likdb_local`, and hand-edit
`claude_desktop_config.json` with absolute paths to `uv` and the checkout — and Desktop doesn't
inherit a shell `PATH`, so the `uv` location often has to be discovered and pasted in too. That
is a lot of machine-specific setup for a non-technical or first-time tester, and every step is a
place to get stuck.

It also leaves `local` and deployed shaped differently. Today's container (`Dockerfile`) runs
stdio and `LIK_ENV=prod`, so it boots inert; a real deploy would serve over HTTP. Testing locally
over stdio while deploying over HTTP means the local environment never exercises the transport,
networking, or startup path the deployed one uses.

---

## Actors

- A1. Tester / teammate: wants to exercise the skills against a real Catalog from Claude Desktop, with minimal local setup.
- A2. Claude Desktop: the MCP client; connects to the server by URL and invokes the lik-mcp tools.
- A3. lik-mcp server (container): serves the tools over HTTP, reaches Postgres over the Compose network.
- A4. Postgres (container): holds the Catalog and confirmation signals; already in Compose.

---

## Key Flows

- F1. Stand up and connect
  - **Trigger:** Tester wants to test the skills in Claude Desktop.
  - **Actors:** A1, A2, A3, A4
  - **Steps:** `docker compose up` brings up Postgres and the lik-mcp HTTP server → tester adds the server URL as a connector in Claude Desktop → the lik-mcp tools appear.
  - **Outcome:** Desktop is connected to a running, DB-backed server with no per-machine Python/uv setup.
  - **Covered by:** R1, R2, R3, R6

- F2. Populate then query
  - **Trigger:** Catalog is empty on first run.
  - **Actors:** A1, A2, A3, A4
  - **Steps:** Run `lik-sync-catalog-from-project-indexes` to populate → run `lik-query-project-index` with a question → confirm a source.
  - **Outcome:** Tester gets a real, confirmation-ranked answer end to end.
  - **Covered by:** R4, R5

---

## Requirements

**Serving**
- R1. The server runs as a long-lived HTTP service (streamable-http transport) that Claude Desktop connects to by URL.
- R2. Transport is selectable at runtime: the container serves HTTP; plain `uv run python -m lik_mcp` keeps stdio for no-Docker local dev.
- R3. The container binds to localhost only and runs `LIK_ENV=local` (StubVerifier) — same self-asserted-identity trust posture as local testing today.

**Compose and data**
- R4. The server is a service in the existing `docker-compose.yml`, alongside Postgres; one `docker compose up` runs both, and the server reaches Postgres over the Compose network.
- R5. The server points at the persistent `likdb_local` (data survives the test-suite truncate), not the disposable `likdb_test`.

**Image and docs**
- R6. The README's Claude Desktop section is rewritten to the URL / connector flow, replacing the absolute-path `uv` config; the CLI path may stay as an alternative.
- R7. The same image and HTTP transport are usable for a future deploy — `local` vs `prod` is an environment override, not a separate build — reconciling today's stdio + `prod` Dockerfile.

---

## Success Criteria

- A tester with only Docker installed can go from clone to a connected, DB-backed server in Claude Desktop without installing uv or Python and without editing absolute paths.
- The transport, startup, and DB-networking path exercised locally is the same one a deploy would use; only auth/env differ.
- `ce-plan` can implement without inventing the transport mechanism, the Compose topology, the DB target, or the auth posture — all are fixed here.

---

## Scope Boundaries

- Real Google OIDC / fail-closed prod auth — stays deferred (see lik-mcp README TODO); this container is local-test only.
- TLS/HTTPS, cloud hosting, and the actual deployed deployment.
- Group → Postgres-role RLS, real per-store citation resolution, governed-writer controls — untouched.
- Redesigning the `likdb_local` database strategy or the skills themselves.
- Making the Compose server a shared/remote demo target — that would pull OIDC and TLS back into scope (see Outstanding Questions).

---

## Key Decisions

- HTTP over stdio for the container: matches the deployed serving shape, which is the stated reason for the work. stdio-in-container would cut setup but leave the local/deployed gap intact.
- One image, env-selected behavior: avoids a separate "local" build drifting from the deployed one; the existing Dockerfile is updated rather than forked.
- Keep `likdb_local`: the persistent DB convention already exists for manual testing; the disposable `likdb_test` would lose data the tester needs across runs.

---

## Dependencies / Assumptions

- FastMCP supports a long-lived HTTP transport the current server can switch to. [Likely — needs confirmation in planning against the installed FastMCP version.]
- ~~Claude Desktop can connect to a self-hosted MCP server by URL (connector/integration).~~ **Verified false (2026-06-24):** Desktop custom connectors route the URL through Anthropic's cloud and cannot reach localhost. Desktop's only local mechanism is stdio via `claude_desktop_config.json`, so it connects to the HTTP container through an `mcp-remote` stdio→HTTP bridge. See the plan's Key Technical Decisions.
- `likdb_local` is created once inside the Postgres container per the README; the Compose flow assumes that step or automates it.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R1, R2][Technical] How is transport selected — env var, CLI flag, or Compose command override — and what port/path does HTTP bind? 
- [Affects R3][Needs research] Does Claude Desktop require any auth (even a token) to connect to a self-hosted HTTP MCP server, and does that interact with the StubVerifier token the skills pass?
- [Affects R5][Technical] Should `likdb_local` creation be automated in the Compose startup (init script / entrypoint) so the tester skips the manual `createdb` step?
- [Affects R6] If the same Compose is ever pointed at a non-localhost address for a shared demo, what is the minimum auth bar — does that force OIDC/TLS earlier than the TODO assumes?
