---
date: 2026-07-06
topic: lik-ui-managed-agent-app
---

# lik-ui — Managed Agent Companion App

## Summary

A hosted, multi-user web app (new top-level `lik-ui/` folder) where a Nava user logs in, picks an
agent, connects the data sources that agent needs (lik-mcp, Atlassian, more later) by completing
each source's OAuth flow once, and then chats with a Claude Managed Agent that acts on those
connections on their behalf. lik-ui's core job is the OAuth-and-vault plumbing the Managed Agents
platform does *not* do — obtaining each source's tokens and depositing them in the user's
credential vault — plus a streaming chat surface.

---

## Problem Frame

The Discovery Layer's value only lands when a real person can ask a question and get an answer that
draws on their own, permission-scoped access to the data sources. Claude Managed Agents supplies the
agent harness (loop, sandbox, tools, token refresh and injection), but it deliberately runs headless
server-side sessions with **no browser** — so it cannot walk a user through an OAuth consent screen.
The platform will *inject and refresh* a token, but only one that already exists in a credential
vault. Someone has to run each provider's initial authorization-code flow, capture the resulting
tokens, and put them in the right per-user vault. Today nothing does that: the enabling work landed
only as far as "lik-mcp auth works with a Managed Agent" at the server level. Without a front door
that handles login, per-source connection, and chat, the agent has no way for an actual Nava user to
reach it under their own identity.

---

## Actors

- A1. Nava user: logs into lik-ui, selects an agent, connects the required data sources, and chats.
- A2. lik-ui app: hosts login, drives per-source OAuth flows, manages the user→vault mapping, creates and streams sessions.
- A3. Claude Managed Agents platform: holds the agent/environment definitions, credential vaults, and runs the sessions.
- A4. Data-source MCP servers (lik-mcp, Atlassian, future): the OAuth-protected servers the agent connects to on the user's behalf.
- A5. Agent author (out of band): defines each selectable agent and its declared `mcp_servers` on the platform; not a lik-ui role.

---

## Key Flows

- F1. Log in and pick an agent
  - **Trigger:** A user opens lik-ui.
  - **Actors:** A1, A2
  - **Steps:** User signs in (Google Workspace SSO) → lik-ui resolves or creates the user's record → user is shown the list of available agents (one today) and selects one.
  - **Outcome:** lik-ui knows who the user is and which agent (and its paired environment) they want to use.
  - **Covered by:** R1, R2, R3

- F2. Discover and connect required sources
  - **Trigger:** A user has selected an agent.
  - **Actors:** A1, A2, A3, A4
  - **Steps:** lik-ui queries the selected agent via the Claude SDK to read its declared MCP servers → compares that required set against credentials already in the user's vault → for each missing connection, presents a "connect" action that runs *that source's* OAuth authorization-code flow (lik-mcp via Google using `LIK_OAUTH_CLIENT_ID`; Atlassian via its own OAuth) → on callback, exchanges the code for tokens and stores them in the user's vault keyed by the exact MCP server URL.
  - **Outcome:** The user's vault holds a valid credential for each server the selected agent requires.
  - **Covered by:** R4, R5, R6, R7, R8

- F3. Chat with the agent
  - **Trigger:** A user with the required sources connected sends a message.
  - **Actors:** A1, A2, A3, A4
  - **Steps:** lik-ui creates (or resumes) a session referencing the selected agent, its environment, and the user's vault → user's message is sent as an event → the agent's streamed response (including MCP tool calls, auto-approved) is rendered back in the chat.
  - **Outcome:** The user gets an answer drawn from their own connected sources, in a normal chat rhythm.
  - **Covered by:** R9, R10, R11, R12

---

## Requirements

**App identity & agent selection**
- R1. lik-ui authenticates the user through an app login that is *separate* from the data-source connections. App login is assumed to be Google Workspace SSO (planner to finalize the provider).
- R2. lik-ui maintains a durable per-user record and a persistent **user→VAULT_ID mapping**, so a returning user reuses their existing vault and connections.
- R3. lik-ui presents a selectable list of agents; each option pairs an agent with its environment. The design must accommodate multiple agents even though only one exists today (`AGENT_ID=agent_01E7mqTKAdtosKpWDSLxALmq`, `ENV_ID=env_016c6vWcCUvyVUaztWhvsAQt`).

**Deriving & making connections**
- R4. The set of required connections for a session is **derived from the selected agent's definition** (its declared MCP servers), read via the Claude SDK — not from a hardcoded list. Different agents may require different source sets.
- R5. Connecting a source runs a **generic, discovery-driven MCP-OAuth flow**: from the server's URL, discover its OAuth authorization server and endpoints (RFC 9728 protected-resource metadata → RFC 8414 / OIDC authorization-server metadata), obtain a client (see R6), then run a PKCE authorization-code flow, returning the user to lik-ui via a registered callback. lik-ui should not hardcode per-source OAuth endpoints.
- R6. Obtaining a client follows the source's capability: **(a) Dynamic Client Registration** when the authorization server advertises a `registration_endpoint` (e.g., Atlassian) — lik-ui self-registers and **persists** the registered `client_id`/secret for reuse; **(b) a pre-configured client** when the AS has no DCR (e.g., lik-mcp, whose AS is Google) — lik-ui holds a per-source config entry. Adding a DCR-capable source later requires **no** per-source config; adding a no-DCR source requires one config entry.
- R7. The lik-mcp connection uses the pre-configured Google client `LIK_OAUTH_CLIENT_ID` (secret supplied via env var) with scopes `openid,email` plus offline access, and is stored keyed by `LIK_RESOURCE_SERVER_URL`. The Atlassian connection uses DCR against its advertised registration endpoint.
- R8. Stored credentials must key on the **exact** MCP server URL the agent declares; a mismatch means the token is silently not injected. lik-ui stores the OAuth `refresh` block (token endpoint + the client id/secret from R6, whether DCR-issued or pre-configured) so the platform refreshes tokens, and surfaces a re-connect prompt when a credential can no longer be refreshed.

**Chat & session**
- R9. lik-ui creates a Managed Agents session referencing the selected agent, its environment, and the user's vault, and streams the agent's responses into a web chat UI.
- R10. MCP tool calls are **auto-approved** — no per-call approval UI. (Realized via the agent's MCP permission policy; see Dependencies.)
- R11. A user's conversations persist and are resumable: lik-ui stores the session id(s) per user and re-opens rather than always starting fresh.
- R12. lik-ui shows per-source **connection status** for the selected agent and lets the user connect any missing source. A user may open the app before everything is connected; an unconnected source means its tools are simply unavailable to the agent (nudge, do not hard-block chat).

---

## Success Criteria

- A first-time Nava user can log in, select the sole available agent, connect lik-mcp and Atlassian through in-app OAuth, and receive a chat answer that demonstrably used both sources — without any manual token handling.
- A returning user's connections persist: they log in and chat without re-authorizing, unless a credential has expired/revoked, in which case they are prompted to re-connect only the affected source.
- Adding a second agent that requires a different source set works with no lik-ui code change to the connection logic — the required sources come from the agent definition.
- No source token is ever entered or seen by the user as a raw value; connections happen only through OAuth flows.

---

## Scope Boundaries

- **In:** app login; per-user vault + user→vault mapping; SDK-driven discovery of an agent's required MCP servers; OAuth connect flows for lik-mcp (Google) and Atlassian; session creation and streamed chat; connection status and re-connect prompts.
- **Out — building/managing agents:** lik-ui references agents and environments defined elsewhere; it does not create or edit them.
- **Out — lik-mcp server changes:** the server's auth already works; this app is a client of it.
- **Out — per-call tool approval UI:** auto-approve is the chosen behavior.
- **Out (for now) — non-Google app login** and any provider-selection UI beyond the agent list.

---

## Key Decisions

- **Hosted multi-user web app** (not a local single-user proof). Chosen deliberately despite higher carrying cost, because the goal is real Nava users under their own identity.
- **App login decoupled from data-source connections.** Rationale: more MCP servers will be added later, so connection is an extensible, per-source action rather than fused to login.
- **Required connections are agent-derived via the Claude SDK**, not hardcoded — so agents remain a growable list and each can declare its own source set.
- **lik-ui owns the initial OAuth consent; the platform owns refresh + injection.** This is the reason the app exists rather than being a thin chat wrapper.
- **Auto-approve MCP tool calls** for a smooth, read-oriented chat experience.
- **One generic discovery-driven OAuth connector, not per-source code.** Endpoints are discovered from each server; only no-DCR sources (lik-mcp/Google) carry a small pre-configured-client entry. This is the mechanism that keeps "add a new source later" cheap.

---

## Dependencies / Assumptions

- **Google OAuth client secret** for `LIK_OAUTH_CLIENT_ID` is **supplied via an environment variable** (resolved). The lik-mcp connect flow uses it plus `offline` access to mint a refresh token.
- **Atlassian OAuth client** does *not* need manual provisioning — Atlassian's remote MCP advertises a `registration_endpoint`, so lik-ui self-registers via DCR at runtime and persists the result.
- **Registered redirect/callback URIs** for each provider must point at lik-ui's hosted domain — for pre-configured clients (Google) set in the provider console; for DCR clients (Atlassian) supplied in the registration request.
- **Agent-side configuration is external:** auto-approve (R10) depends on the agent's MCP permission policy being set on the agent definition, since lik-ui does not manage agents. Likewise, adding a connectable server later requires updating *both* the agent's declared `mcp_servers` and (if provider config isn't discoverable) lik-ui's per-source OAuth setup.
- `LIK_RESOURCE_SERVER_URL` is currently an ephemeral ngrok URL that rotates on restart; a stable resource-server URL is needed for durable stored credentials to keep matching.

---

## Outstanding Questions

- **App-login provider:** assumed Google Workspace SSO — confirm, and confirm whether app-login identity should equal the Google identity used for the lik-mcp grant or stay fully independent.
- ~~**Per-source OAuth config: discovered vs configured.**~~ *Resolved:* endpoints are always discoverable (RFC 9728 → RFC 8414/OIDC). Only the client-acquisition differs — DCR where advertised (Atlassian: zero config), pre-configured client where not (lik-mcp/Google: one config entry). See R5–R6.
- **Conversation model:** one resumable session per conversation with a conversation list, or a single rolling session per user+agent? (R11 assumes the former.)
- **Deployment target / hosting** for lik-ui (and where secrets live) — likely a ce-plan concern, noted here because hosted multi-user was chosen.
