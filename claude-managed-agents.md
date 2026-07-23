# Claude Managed Agents

Why LIK runs its agent on Anthropic's [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview)
platform instead of building and operating its own agent runtime — and the two gaps that platform
leaves, which are exactly what [lik-mcp](lik-mcp/README.md) and [lik-ui](lik-ui/README.md) fill.

## What it is

Claude Managed Agents (CMA) is a hosted place to run an AI agent. You describe an **agent** once —
which model it uses, its instructions, and which tools and data sources it may reach — and Anthropic
runs it. Each task is a **session**: Anthropic runs the back-and-forth loop between the model and its
tools, hands the agent a private sandbox to work in, and streams the results back to your app.

### Status: beta, with a data-retention constraint

CMA is in **beta**. [Anthropic's own words](https://platform.claude.com/docs/en/managed-agents/overview#beta-access):
*"Claude Managed Agents is in beta. [...] Behaviors may be refined between releases to improve outputs."*
All endpoints require a dated beta header (`managed-agents-2026-04-01`), so behavior can change between
releases — something to weigh before depending on it long term.

The beta also carries a data-handling limit that shapes our design. CMA is stateful by design — sessions
keep conversation history, sandbox state, and outputs on Anthropic's servers:

> Claude Managed Agents is stateful by design [...]. Because of this, Managed Agents is not currently
> eligible for [Zero Data Retention] or HIPAA Business Associate Agreement (BAA) coverage.

For a system built around governed knowledge, that bounds what data may flow through an agent session and
is a factor in the access-control design (see [v0.4/06-access-control.md](v0.4/06-access-control.md)).

## Why use it instead of building our own

Running an agent yourself means standing up and operating a lot of moving parts. CMA provides each of
them as managed infrastructure, so LIK doesn't have to build, host, or maintain them:

- **The agent loop.** The repeated cycle of "ask the model → run the tool it asked for → feed the
  result back → repeat until done" runs on Anthropic's side. We don't write or host that loop.
- **A per-session sandbox.** Each session gets its own isolated workspace where tools actually run
  (shell commands, file edits, code). We don't provision, secure, or tear down containers.
- **Session state and streaming.** Conversation history, the sandbox's files, and progress events are
  kept server-side and streamed to the app. We don't build a state store or an event pipeline.
- **Secret storage and OAuth refresh.** Credentials for the data sources an agent uses live in
  Anthropic-managed **vaults**. The secret is injected into outbound requests only as they leave the
  sandbox — it never sits inside the workspace where agent-run code could read it. For OAuth
  credentials, Anthropic **auto-refreshes** the access token from the stored refresh token, so tokens
  don't silently expire mid-task. We don't build a secrets store or a token-refresh service.
- **Versioned agent configs.** An agent is a saved, versioned object. We can change its instructions
  or tools and pin sessions to a known-good version, without a config-management system of our own.
- **Built-in efficiency.** Prompt caching, context compaction for long runs, and extended thinking are
  handled by the platform.

In short, CMA covers the *generic* machinery of running an agent — the part that is the same for
everyone and that we'd gain nothing by rebuilding. This fits the architecture's principle of leaning on
standards and common patterns rather than bespoke mechanisms (see [v0.4/01-overview.md](v0.4/01-overview.md)).

## What it does not provide

CMA is a runtime, not a product. It hosts an agent and connects it to tools, but it knows nothing about
LIK's knowledge, LIK's people, or how they sign in. Two gaps remain — one on each side of the agent —
and each is a whole app in this codebase.

### The knowledge side → lik-mcp

CMA can *connect to* an external tool provider (an MCP server), but it does not *supply* one. LIK's
Discovery Layer needs a governed store of its own — the **Catalog** (where a topic's material lives)
and **Confirmation signals** (people vouching a source was right or flagging it wrong). That store has
rules CMA has no concept of: a fixed menu of intent-named tools instead of raw database access, and
access enforced per the original data source rather than by the agent.

[lik-mcp](lik-mcp/README.md) is that MCP server. CMA's role is only to let an agent call it, as one more
declared MCP server; building, hosting, and governing it is ours.

### The human side → lik-ui

CMA stores and refreshes credentials, but it never *obtains* them, and it has no notion of the human
using the agent. Before a vault can hold a token, someone has to authenticate the person, run the
interactive OAuth consent flow for each data source (discovery, dynamic client registration, PKCE, the
browser sign-in), and deposit the resulting token in that user's vault. CMA does none of this — it
picks up only after the token already exists.

[lik-ui](lik-ui/README.md) is that front door: a web app where a Nava user signs in, connects the data
sources the agent needs, and chats with the agent. It runs the per-source OAuth flow and deposits the
tokens into the user's Claude vault — in its own words, *"the part the Managed Agents platform does not
do for you."* It also carries what CMA has no opinion on: how each user's calls are authorized against
Anthropic (per-user key vs. workload identity federation), and the chat and agent-picker surface itself.

## The division of labor

```
 [ Nava user ]
      │  sign in, connect sources, chat
      ▼
 [ lik-ui ]───────────── deposits OAuth tokens ──────────▶ [ Claude vault ]
   (our front door)                                          (CMA-managed)
      │  starts a session                                        │ refreshes + injects at egress
      ▼                                                          ▼
 [ Claude Managed Agents ]  ── runs the agent loop + sandbox ──▶ calls tools
      │                                                          │
      └── connects to MCP servers ───────────────────────────────┤
                                                                  ▼
                                                          [ lik-mcp ]
                                                       (our governed store:
                                                        Catalog + Confirmations)
```

CMA owns the middle — the generic agent runtime. LIK owns the two ends: the governed knowledge
([lik-mcp](lik-mcp/README.md)) and the human front door ([lik-ui](lik-ui/README.md)).

## Future option: replacing CMA

Using CMA is a bet we can unwind. Consistent with the architecture's "earn each step" principle
(see [v0.4/01-overview.md](v0.4/01-overview.md)), we'd only build a replacement once evidence shows it's
needed. Three triggers could justify it:

- **Cost** — per-session platform and sandbox charges outgrow what self-hosted compute would cost at our
  volume.
- **Vendor lock-in** — we want to run on our own infrastructure, or reduce dependence on a single vendor.
- **Data handling** — the [retention constraint](#status-beta-with-a-data-retention-constraint)
  (no ZDR / HIPAA BAA) blocks a class of data we may need the agent to touch.
  This may be resolved once Managed Agents is promoted out of Beta status.

### What already insulates us

Because the design is loosely coupled, most of LIK would not change. The two ends are already ours and
built on standards, not on CMA:

- **[lik-mcp](lik-mcp/README.md)** is a standard MCP server. Any runtime that speaks MCP can call it
  unchanged.
- **[lik-ui](lik-ui/README.md)** is our own web app. Its OAuth flows and chat surface stay; only where it
  *starts a session* and *deposits tokens* would repoint from CMA to the replacement.

The seam is narrow: CMA sits in the middle, between those two ends. A replacement swaps the middle and
leaves the ends in place.

### What the replacement must take on

Building our own runtime means absorbing every responsibility CMA provides today (mirroring
[Why use it instead of building our own](#why-use-it-instead-of-building-our-own)). At minimum:

1. **The agent loop** — drive the cycle of ask-the-model → run the requested tool → feed the result back
   → repeat until done. Model access itself is separate: we can keep calling Claude directly, or (the
   deeper lock-in escape) swap in another model provider — a larger change, since prompts and tool
   behavior are tuned per model.
2. **A per-session sandbox** — provision an isolated workspace to run tools (shell, files, code), secure
   it against the agent's own untrusted output, and tear it down after each session.
3. **Session state and streaming** — persist conversation history and sandbox state, and stream progress
   back to lik-ui, including clean resume after a dropped connection.
4. **Credential handling** — a vault to store each user's source tokens, injection of the secret only at
   the point a request leaves the sandbox (never inside it), and automatic OAuth token refresh so tokens
   don't expire mid-task. This is where lik-ui would deposit tokens instead of the Claude vault.
5. **Tool and MCP wiring** — connect the agent to MCP servers (including lik-mcp), enforce which tools an
   agent may use, and gate the risky ones behind approval.
6. **Agent configuration** — store each agent's model, instructions, and tool set as a versioned,
   reusable object so sessions can pin a known-good version.
7. **Efficiency and long-run support** — prompt caching, context compaction for long sessions, and
   safe handling of turns that run for minutes. (Prompt caching and compaction are model-API features we
   can use directly, so this is partly inherited rather than fully rebuilt.)
8. **Operational concerns** — scaling, container lifecycle, secret custody and rotation, audit logging,
   and per-user authorization against whatever model provider we use.

This list is the cost of the option, not a plan to exercise it. It's recorded here so the trade-off is
visible: CMA buys us all of the above today, and this is what we'd re-shoulder to leave it.
