# LIK — FAQ

Short answers about what this is, what it can do, and where it's headed. Each answer links to
the canonical document for the full story — this page is a starting point, not the source of truth.

## What is this?

The **LIK app** is a web app that lets a Nava user sign in, connect the data sources an AI agent needs, and
chat with that agent. LIK makes it easy to connect the relevant data sources
and pairs that with centrally-managed agents and skills aimed at common use cases, so the whole
team can get going without any setup of their own.
The bigger idea it serves is a **Discovery Layer**: material derived from
Nava's existing data sources (Google Drive, Confluence, Jira, GitHub, Slack, and more) that makes
company knowledge fast to find and reuse, without copying everything into one place and without
becoming a competing source of truth.

[More: project overview](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/01-overview.md)

### How is this different from other AI tools?

All of these let you ask an AI questions about your work, and each is a reasonable choice for
some situations. The short version: LIK is built to search **across** all of Nava's data
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

**LIK** — searches across all of Nava's connected sources in one place, without copying
everything into a new system, and makes connecting each source point-and-click rather than a
technical chore. The agents and their skills are maintained centrally, so everyone is always
on the latest version without doing anything. Sessions can also be shared read-only so others
can see how you worked with the agent and build on it (see [Share a chat session with
others](#share-a-chat-session-with-others)). Limitations: it's an early system with rough
edges (see below), and it only reaches sources that have a supported connector.

## What can the agent do, and how does it work?

You pick an agent, connect the sources it needs, and ask it questions in chat. The agent itself runs
on Anthropic's **Claude Managed Agents** platform — Anthropic runs the model-and-tools loop and a
per-session sandbox — while the LIK app handles the human side (sign-in and per-source connection) and a
separate service (lik-mcp) supplies Nava's governed knowledge.

[More: why we run on Claude Managed Agents](https://github.com/navapbc/leverage-inst-knowl/blob/main/claude-managed-agents.md)

### Pick the right agent for your question

The picker groups purpose-built agents into labeled sections, and a Knowledge Search Agent routes a
question to the matching source of knowledge (projects, org guidance, or practice knowledge) for you.
Useful because you don't have to know which specialist to ask — you get a clear menu and sensible routing.

### Connect many data sources

You can point-and-click to connect the sources the agent needs — Confluence/Jira, GitHub, Google Drive,
and Slack. Useful because an answer can draw on the places your team actually works, not just one.
Which sources are reachable depends on whether each offers a supported connector (MCP server): the ones listed
have official ones; some Google apps and other sources are community or third-party, and a few have none yet.

When you connect a source you sign in to that provider yourself and approve the LIK app. Approving hands LIK a
personal access token (an OAuth grant) that stands in for you, so whichever agent you use acts **on your
behalf**: it can reach exactly what you can reach in that source and nothing more, and each person connects
their own sources. The consent is for the LIK app as a whole — every agent in it draws on the same connection,
you don't re-approve per agent. The provider itself enforces your permissions on every request — LIK never
holds a shared, all-access login, and connecting one source doesn't expose anything in the others. What each
connection gives the agent access to:

- **`atlassian`** — Confluence pages and Jira issues (with their comments and attachments) in the Atlassian
  sites you belong to.
- **`google-drive-drivemcp`** — Google Docs, Sheets, Slides, and other files in your Google Drive, read-only.
- **`github`** — the repositories, code, issues, and pull requests your GitHub account can see, including
  your organization membership.
- **`slack`** — messages, channels, canvases, and people you can already see in Slack, read-only (search and
  history — the agent can look things up but can't post, react, or edit on your behalf).
- **`lik-mcp`** — Nava's own governed knowledge layer (the Discovery Layer material derived from the sources
  above); it uses your sign-in to identify you and still checks your permissions before returning anything.

[More: data-source availability](https://github.com/navapbc/leverage-inst-knowl/blob/main/mcp-availability.md)

### See what the agent is doing while it works

The activity indicator shows the specific tool the agent is running (and how many times), and each reply
notes how long the turn took. Useful because long agent turns no longer look frozen — you can tell it's
making progress and roughly how much work a question took.

### Guardrails on agents that change shared data

Agents that can write to or change shared data are hidden behind a Settings toggle and kept separate from
read-only ones. Useful because you won't stumble into a data-changing agent by accident.

### Schedule an agent to run on its own

From Settings you can schedule an eligible agent to run automatically on a cadence you choose — pick how often
(every so many days or weeks), enter the message to send, and it runs unattended using your own connected
sources. Routine steps proceed on their own; anything that needs a decision is skipped and recorded, and each
run shows up in your sessions like any other conversation. Useful because recurring work — a weekly index sync,
a regular digest — happens without you having to remember to kick it off. Deleting your credential vault cancels
your schedules, since a run can't work without connected sources.

### Share a chat session with others

A session can be shared as a read-only link so any logged-in user can see how you asked and guided the
agent. A shared session shows the whole conversation, including any content the agent pulled in
while answering, so only share the session ID with people you'd show that material to, and treat the link as
exposing everything in the session.

Sharing is also a starting point for collaboration: someone with the link can copy snippets from the session into
their own chat and keep going — for example, adding context they can reach but you can't (e.g., Slack DMs or
restricted Google Docs). They can ask the agent to summarize or aggregate as they go, but that's a
convenience, not a privacy guarantee: the agent can't reliably strip sensitive details, so whoever
adds or re-shares information is responsible for making sure it's appropriate to share onward.

### Control over your chat data

You can delete a session yourself, and sessions are also cleaned up automatically after a set time. Useful
because sensitive material a session pulled in doesn't linger indefinitely.

## What are its limitations?

It's an early system with known rough edges — for example, how change is detected in Confluence
pages, and quirks of specific data-source connectors. These are tracked and worked around
deliberately.

[More: known limitations](https://github.com/navapbc/leverage-inst-knowl/blob/main/limitations.md)

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

The full design lives in the [v0.5 documents](https://github.com/navapbc/leverage-inst-knowl/blob/main/v0.5/01-overview.md)
(overview, concepts, examples, strategy, architecture, access control, storage, open questions —
all linked above). For how the agent runtime is divided between Anthropic's platform and Nava's own
apps, see [Claude Managed Agents](https://github.com/navapbc/leverage-inst-knowl/blob/main/claude-managed-agents.md).
