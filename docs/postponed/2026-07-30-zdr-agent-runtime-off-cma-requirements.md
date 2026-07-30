---
date: 2026-07-30
topic: zdr-agent-runtime-off-cma
status: postponed
---

# Zero-Data-Retention Agent Runtime (moving sensitive sessions off Claude Managed Agents)

## Summary

A second, zero-retention agent runtime inside lik-ui — built on the Claude Agent SDK against
the ZDR-eligible Messages API — that runs only sessions touching a fenced-off set of sensitive
data sources, while everything else stays on Claude Managed Agents (CMA) unchanged. Segregation
is enforced by credential custody: the sensitive sources' OAuth tokens are held only by the new
runtime and never deposited into the CMA vault, so a CMA session provably cannot reach the
sensitive data class. Sensitive sessions hold conversation content in memory only and persist
nothing at rest.

---

## Problem Frame

A concrete data class LIK must let the agent touch requires Zero Data Retention. CMA is stateful
by design and, in its current beta, is explicitly not eligible for ZDR (see
[claude-managed-agents.md](../../claude-managed-agents.md) → "Status: beta, with a data-retention
constraint"). Any session run on CMA keeps conversation history, sandbox state, and outputs on
Anthropic's servers — so any session that could reach the sensitive data class is non-compliant.

The retention rule is stricter than the usual third-party reading: the sensitive content must not
persist **at rest anywhere**, including LIK's own Postgres. LIK's DB today holds only nonsensitive
metadata (Discovery-Layer catalog records and links to Data-Source records), which is unaffected;
the exposure is the *conversation content*, which pulls retrieved sensitive source material into a
transcript.

`claude-managed-agents.md` already names ZDR as one of three triggers to unwind the CMA bet, and
enumerates the responsibilities a replacement must absorb. This document scopes the first real
exercise of that option — narrowed to the sensitive data class rather than a wholesale replacement.

---

## Actors

- A1. **Nava end user** — signs in to lik-ui, connects data sources, and chats with an agent. May
  use both general (CMA) and sensitive (ZDR) sources.
- A2. **CMA runtime** — Anthropic-hosted; continues to run all non-sensitive sessions unchanged.
- A3. **ZDR runtime** — the new in-lik-ui agent loop (Claude Agent SDK + Messages API) that runs
  sensitive-source sessions with no at-rest retention of content.
- A4. **Data sources** — external MCP-backed sources (e.g. Confluence, Drive, Slack, GitHub) plus
  lik-mcp. A fenced-off subset carries the sensitive data class and is reachable only by A3.

---

## Key Flows

- F1. **Connect a sensitive source**
  - **Trigger:** user connects a source that is designated sensitive.
  - **Actors:** A1, A3.
  - **Steps:** lik-ui runs the existing OAuth flow → the resulting token is deposited **only** into
    the ZDR runtime's own token store, never into the CMA vault.
  - **Outcome:** the sensitive source is reachable by A3 and unreachable by A2 (no credential exists
    for it on the CMA side).
  - **Covered by:** R1, R2, R7.

- F2. **Chat in a sensitive session**
  - **Trigger:** user starts a session with an agent wired to a sensitive source.
  - **Actors:** A1, A3, A4.
  - **Steps:** session is routed to the ZDR runtime → the agent loop runs in lik-ui, calling MCP
    tools with the ZDR-held token → conversation content lives in memory for the connection's life →
    on session end / disconnect, content is dropped; only nonsensitive metadata (e.g. token counts,
    timestamps) may be recorded.
  - **Outcome:** compliant session with no sensitive content at rest anywhere.
  - **Covered by:** R3, R4, R5, R6, R8.

- F3. **Chat in a general session** *(unchanged)*
  - **Trigger:** user starts a session with a non-sensitive agent.
  - **Actors:** A1, A2.
  - **Steps:** existing CMA path — vault, hosted loop, retained transcript, history replay, sharing.
  - **Outcome:** no change from today.
  - **Covered by:** R9.

---

## Requirements

**Runtime**
- R1. Provide a second agent runtime inside lik-ui that drives the agent loop itself (Claude Agent
  SDK) against the Messages API operated under a Zero-Data-Retention agreement. Claude remains the
  model provider; this is not a provider switch.
- R2. The ZDR runtime is a clean, standalone path — designed so a future decision to move all
  traffic onto it is a routing change, not a rebuild.
- R3. For sensitive sessions, conversation content exists only in memory for the life of the live
  connection and is never written to durable storage (Anthropic's or LIK's).
- R4. The ZDR runtime connects the agent to MCP servers (including lik-mcp and the sensitive
  sources), enforces which tools an agent may use, and gates risky tools behind approval —
  preserving the confirmation behavior CMA provides today.

**Segregation (the compliance invariant)**
- R5. Sessions touching a sensitive data source are routed to the ZDR runtime; all other sessions
  stay on CMA.
- R6. A CMA session must be *provably unable* to reach the sensitive data class. Segregation is
  enforced by credential custody, not by user choice or a session label.
- R7. Tokens for sensitive sources are stored only in the ZDR runtime's own token store and are
  never deposited into the CMA vault. The runtime owns encrypted-at-rest custody of these tokens
  and their OAuth refresh, with the secret injected only at request egress (never readable by the
  agent).

**Coexistence**
- R8. Sensitive sessions may record nonsensitive metadata only (e.g. token/usage counts,
  timestamps, session ownership) — never conversation content.
- R9. The CMA path (general sessions, vault, retained transcript, history replay, shared sessions,
  content analytics) is unchanged for non-sensitive use.

---

## Acceptance Examples

- AE1. **Covers R5, R6, R7.** Given a source designated sensitive, when a user attempts to reach it,
  then the session runs on the ZDR runtime; and given any CMA session, when it attempts to reach
  that source, then it fails because no CMA-side credential exists for it.
- AE2. **Covers R3, R8.** Given a completed sensitive session, when its live connection ends, then
  no conversation content remains in Anthropic's systems or LIK's DB; only nonsensitive metadata
  (token counts, timestamps) may persist.
- AE3. **Covers R4.** Given a sensitive session where the agent requests a risk-gated tool, when the
  turn reaches that tool, then the user is prompted to allow/deny before it runs — matching today's
  CMA confirmation behavior.

---

## Success Criteria

- The sensitive data class can be used through the agent with a defensible ZDR posture: no
  conversation content is retained by Anthropic or by LIK.
- The segregation boundary is an enforced invariant a reviewer can verify (no CMA credential for
  sensitive sources), not a convention that depends on users picking the right mode.
- General chat is observably unchanged — no regression to CMA-backed sessions, sharing, or history.
- A downstream planner can build the ZDR runtime without having to re-decide model provider,
  segregation mechanism, retention posture, or which features are dropped for the MVP.

---

## Scope Boundaries

- Replacing CMA wholesale for all traffic. (This is the later "collapse to a single runtime"
  option; the standalone design in R2 keeps it cheap, but it is not this work.)
- Switching to a non-Claude model provider.
- Rebuilding a per-session code/shell/file sandbox — LIK agents are MCP-tool-callers, not
  code-writers, so it is not needed.
- Retained-transcript–dependent features for sensitive sessions: history-replay-on-reload,
  resume-after-dropped-connection, shared sessions, and content-bearing analytics. These conflict
  with "nowhere at rest" and are deliberately dropped for the sensitive path.
- Scheduled unattended runs against sensitive sources (they need stored refresh tokens and a
  landing place for output — both require separate resolution).
- Changes to lik-mcp (a standard MCP server; unaffected).
- HIPAA BAA coverage (ZDR only was specified).

---

## Key Decisions

- **Keep Claude via the ZDR-eligible Messages API, don't leave the model.** ZDR is an Anthropic API
  contract term; CMA is excluded because it is stateful, but the Messages API can be covered. So
  "off CMA" ≠ "off Claude." Avoids retuning prompts/tool behavior for a new provider.
- **Enforce segregation by credential custody, not session mode.** The agent reaches sensitive
  content via a source's OAuth token; if CMA holds no token for the sensitive sources, it cannot
  retain their content regardless of session labeling. This turns dual-mode from a convention into a
  provable invariant — and is the reason dual-mode is defensible at all.
- **Build the ZDR runtime standalone so it can later absorb all traffic.** If ZDR demand spreads,
  flipping everyone onto it becomes a routing change rather than a second rebuild.
- **No code/shell sandbox.** The environment today is `networking: limited` + `allow_mcp_servers`
  with no code execution, so CMA's per-session sandbox (responsibility #2 in
  claude-managed-agents.md) does not need replacing — the runtime is a model loop + MCP client.
- **MVP drops retained-transcript features for sensitive sessions.** Those features inherently
  require persistence that "nowhere at rest" forbids; dropping them is a consequence of the
  constraint, not an arbitrary cut.

---

## Dependencies / Assumptions

- Anthropic contract/config makes the Messages API ZDR-eligible for this account (must be confirmed
  before build).
- The sensitive data class maps cleanly to a fenceable set of data sources (confirmed in
  brainstorm) — credential-custody segregation depends on this.
- LIK's existing Postgres content (catalog metadata + DS links) is nonsensitive and out of the ZDR
  boundary.
- The Claude Agent SDK provides the agent loop, MCP client wiring, tool-approval gating, and
  context compaction the runtime relies on. *(Assumed from the SDK's role; verify capabilities
  against the current SDK during planning.)*

---

## Outstanding Questions

### Resolve Before Planning

- [Affects R7][User decision] Token custody for sensitive sources: is storing encrypted OAuth
  refresh tokens at rest in LIK acceptable, or must even tokens be non-persistent (forcing
  per-session re-auth)? This gates whether any unattended use is ever possible.
- [Affects R5, R6][User decision] What designates a source (or agent) as "sensitive," and who
  controls that designation — config, per-source flag, or per-agent wiring?

### Deferred to Planning

- [Affects R1][Needs research] Confirm Claude Agent SDK coverage for streaming to the browser,
  clean resume semantics, and permission-gated tool confirmation equivalent to CMA's.
- [Affects R3][Technical] How in-flight sensitive sessions survive (or intentionally don't survive)
  a lik-ui process restart, given content is memory-only.
- [Affects R2][Technical] Where session routing (CMA vs ZDR) lives so it stays a thin,
  swappable decision.
- [Affects R8][Technical] Which analytics/metadata the stats page can still derive for sensitive
  sessions without touching content.
