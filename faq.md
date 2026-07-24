# lik-ui — FAQ

Short answers about what this is, what it can do, and where it's headed. Each answer links to
the canonical document for the full story — this page is a starting point, not the source of truth.

## What is this?

lik-ui is a web app that lets a Nava user sign in, connect the data sources an AI agent needs, and
chat with that agent. The bigger idea it serves is a **Discovery Layer**: material derived from
Nava's existing data sources (Google Drive, Confluence, Jira, GitHub, Slack, and more) that makes
company knowledge fast to find and reuse, without copying everything into one place and without
becoming a competing source of truth.

[More: project overview](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/01-overview.md)

## What can the agent do, and how does it work?

You pick an agent, connect the sources it needs, and ask it questions in chat. The agent itself runs
on Anthropic's **Claude Managed Agents** platform — Anthropic runs the model-and-tools loop and a
per-session sandbox — while lik-ui handles the human side (sign-in and per-source connection) and a
separate service (lik-mcp) supplies Nava's governed knowledge.

[More: why we run on Claude Managed Agents](https://github.com/navapbc/leverage-inst-knowl/blob/main/claude-managed-agents.md)

## What are its limitations?

It's an early system with known rough edges — for example, how change is detected in Confluence
pages, and quirks of specific data-source connectors. These are tracked and worked around
deliberately.

[More: known limitations](https://github.com/navapbc/leverage-inst-knowl/blob/main/limitations.md)

## Which data sources can it connect to?

It depends on whether each source offers a supported connector (MCP server). Confluence/Jira,
GitHub, Slack, Google Drive, and Salesforce have official ones; some Google apps and other sources
are community or third-party, and a few have none yet.

[More: data-source availability](https://github.com/navapbc/leverage-inst-knowl/blob/main/mcp-availability.md)

## Where can I learn more?

The design is written up in a set of short documents:

- [Overview](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/01-overview.md) — what we're building and why
- [Concepts](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/02-concepts.md) — the core ideas in plain language
- [Examples](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/03-examples.md) — how they map to systems Nava runs
- [Strategy](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/04-strategy.md) — the phased build plan
- [Architecture](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/05-architecture.md) — the technical design
- [Access control](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/06-access-control.md) — how permissions are enforced
- [Storage](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/07-storage.md) — where derived material lives
- [Open questions](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/08-open-questions.md) — what's still undecided

---

## For developers

*The rest of this page is for engineers working on lik-ui — architecture and open engineering items,
not end-user help.*

### Architecture and design

The full design lives in the [v0.4 documents](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.4/01-overview.md)
(overview, concepts, examples, strategy, architecture, access control, storage, open questions —
all linked above). For how the agent runtime is divided between Anthropic's platform and Nava's own
apps, see [Claude Managed Agents](https://github.com/navapbc/leverage-inst-knowl/blob/main/claude-managed-agents.md).

### Open engineering items

Tracked in the lik-ui [README](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md);
the notable open ones:

- [Decide how users get Anthropic API access](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-decide-how-users-get-anthropic-api-access) — per-user key vs. workload identity federation
- [Move OAuth client registrations off personal ownership](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-move-oauth-client-registrations-off-personal-ownership) — re-register clients under Nava org ownership before others depend on them
- [Streaming timeouts on the deployed ingress](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-streaming-timeouts-on-the-deployed-ingress-scaling) — the managed Lightsail ingress can cut long SSE responses
- [Cache agent `describe` results](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-cache-agent-describe-results) — avoid one SDK call per agent per page load
