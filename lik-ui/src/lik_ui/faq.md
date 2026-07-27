# lik-ui — FAQ

Short answers about what this is, what it can do, and where it's headed. Each answer links to
the canonical document for the full story — this page is a starting point, not the source of truth.

## What is this?

`lik-ui` is a web app that lets a Nava user sign in, connect the data sources an AI agent needs, and
chat with that agent. `lik-ui` makes it easy to connect the relevant data sources
and pairs that with centrally-managed agents and skills aimed at common use cases, so the whole
team can get going without any setup of their own.
The bigger idea it serves is a **Discovery Layer**: material derived from
Nava's existing data sources (Google Drive, Confluence, Jira, GitHub, Slack, and more) that makes
company knowledge fast to find and reuse, without copying everything into one place and without
becoming a competing source of truth.

[More: project overview](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/01-overview.md)

### How is this different from other AI tools?

All of these let you ask an AI questions about your work, and each is a reasonable choice for
some situations. The short version: lik-ui is built to search **across** all of Nava's data
sources at once, while the alternatives are each strongest inside their own home turf. Pick
whichever fits your need.

**Claude Desktop** — Anthropic's app you install on your own computer. Great for personal,
one-off work and for chatting with the same Claude models. Limitations: each person has to
connect every source themselves, which can get technical and fiddly, and there's no shared
company setup — so it isn't the right tool for a common, maintained way for the whole team to
reach Nava's knowledge. You also manage the agents and their skills yourself, so keeping up
with the latest versions is on you (company-managed "enterprise" skills are updated
automatically when pushed out, but the rest isn't).

**Slack assistant** — AI inside Slack. Convenient for questions about recent conversations
and for staying in the flow of chat. Limitations: it's Slack-first and sees the rest of
Nava's knowledge only shallowly, reaching other sources means each person or channel wiring up
connectors themselves (which can get technical), and it's oriented around discussion rather
than pulling together documents, tickets, and code from everywhere.

**Atlassian Rovo** — Atlassian's built-in AI. Strong if your question lives in Confluence and
Jira, since that's its home ground. Limitations: it's centered on the Atlassian world and
reaches other sources (Google Drive, GitHub, Slack, Salesforce) less fully or not at all — 
so it's a partial view when an answer spans many sources.

**lik-ui** — searches across all of Nava's connected sources in one place, without copying
everything into a new system, and makes connecting each source point-and-click rather than a
technical chore. The agents and their skills are maintained centrally, so everyone is always
on the latest version without doing anything. Limitations: it's an early system with rough
edges (see below), and it only reaches sources that have a supported connector.

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

- [Overview](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/01-overview.md) — what we're building and why
- [Concepts](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/02-concepts.md) — the core ideas in plain language
- [Examples](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/03-examples.md) — how they map to systems Nava runs
- [Strategy](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/04-strategy.md) — the phased build plan
- [Architecture](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/05-architecture.md) — the technical design
- [Access control](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/06-access-control.md) — how permissions are enforced
- [Storage](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/07-storage.md) — where derived material lives
- [Open questions](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/08-open-questions.md) — what's still undecided

---

## For developers

*The rest of this page is for engineers working on lik-ui — architecture and open engineering items,
not end-user help.*

### Architecture and design

The full design lives in the [v0.5 documents](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/01-overview.md)
(overview, concepts, examples, strategy, architecture, access control, storage, open questions —
all linked above). For how the agent runtime is divided between Anthropic's platform and Nava's own
apps, see [Claude Managed Agents](https://github.com/navapbc/leverage-inst-knowl/blob/main/claude-managed-agents.md).

### Open engineering items

Tracked in the lik-ui [README](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md);
the notable open ones:

- [Decide how users get Anthropic API access](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-decide-how-users-get-anthropic-api-access) — per-user key vs. workload identity federation
- [Move OAuth client registrations off personal ownership](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-move-oauth-client-registrations-off-personal-ownership) — re-register clients under Nava org ownership before others depend on them
- [Streaming timeouts on the deployed ingress](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-streaming-timeouts-on-the-deployed-ingress-scaling) — the managed Lightsail ingress can cull idle SSE connections; largely mitigated by a keepalive heartbeat and drop re-attach, with a possible hard duration cap still to confirm
- [Cache agent `describe` results](https://github.com/navapbc/leverage-inst-knowl/blob/main/lik-ui/README.md#todo-cache-agent-describe-results) — avoid one SDK call per agent per page load
