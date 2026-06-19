# Leveraging Institutional Knowledge — Overview

*A plain-language introduction to what we're building and why. The concepts are explained in [02-concepts.md](02-concepts.md); engineers should continue to the [architecture](04-architecture.md) and [strategy](07-strategy.md).*

## The problem

A company's knowledge is scattered across many data sources — storage (Google Drive), wikis (Confluence), trackers (Jira/GitHub), chat (Slack), CRM (Salesforce), HR (Workday), and more. To answer one question, every AI agent, every app, and every person has to search all of those data sources, over and over. That is slow, expensive, inconsistent from one tool to the next, and prone to missing the answer that is most trusted or most current.

## The idea

Leave the knowledge where it already lives. On top of it, add a **Discovery Layer** that makes finding things fast — **without** copying everything into one place and **without** creating a second, competing "source of truth."

The Discovery Layer is *mostly computed*: the bulk of it is derived from the original data sources and rebuilt on demand, so it needs no careful tending. A small, slow-growing part — people's confirmations and saved answers — can't be rebuilt, and that part is backed up deliberately.

## The value

- **Faster, cheaper answers** — work is computed once and reused by every tool, instead of every tool re-searching every data source on every question.
- **More trustworthy answers** — answers cite their sources, carry content-freshness signals, and accumulate confirmations from the people who used them.
- **Knowledge stays governed** — each original data source keeps controlling who can see what; the Discovery Layer never becomes a back door to restricted data.
- **Low ongoing cost** — most of the Discovery Layer can be rebuilt or discarded, so there's little to maintain.

## Guiding principles

Every design choice traces back to these.

- **Very low maintenance** — most of the Discovery Layer is recomputed from the sources, so it can be rebuilt or discarded rather than tended. Only a small, slow-growing part (people's confirmations and saved answers) must be kept and backed up.
- **Loosely coupled** — keep the pieces independent so any one — a store, a source, a tool — can be swapped without rewriting the rest, and no single vendor becomes hard to leave.
- **Intuitive** — lean on standards (e.g., MCP) and common patterns rather than bespoke mechanisms, so people and tools pick it up quickly.
- **Flexible** — adaptable to a wide range of questions, data, and tools: many small, specialized skills instead of one rigid system.
- **One source of truth** — authoritative knowledge always stays in its original data source. The Discovery Layer holds only computed copies, pointers, and signals — never a competing master record.
- **Secure by default** — least privilege, deny when unsure, and access always enforced by the *original data source*, never by the Discovery Layer's own metadata. A wrong entry can misdirect a lookup but can never unlock a door.
- **Build on existing sign-in** — access reuses the existing Google SSO (single sign-on) and its group permissions instead of standing up a new identity system. (Sources that don't already use Google groups need a one-time mapping — see the [architecture](04-architecture.md).)
- **Earn each step** — add each capability only once the previous one's limits prove it's needed; spend follows evidence, not ambition.

## The approach: buy first, then build only the gaps

We don't commit to the full system up front. The [strategy](07-strategy.md) is a sequence of evidence-driven bets, each justified by a limitation in the one before it:

1. **Buy a commercial tool and learn.** Adopt an existing enterprise-search product, run it for a few months, and catalog exactly where it falls short. If nothing is worth building, we stop here.
2. **Direct access via standard interfaces.** Build our own agent that reads and writes knowledge in the data sources where it already lives, governed by existing sign-in.
3. **Precompute reusable results.** Stop re-searching from scratch by computing summaries, indexes, and pointers once and reusing them.
4. **Add human trust and a single directory.** Let people confirm which answers were right, and give every tool one place to look up where things live.
5. **Grow from real demand.** When someone gets a good answer that didn't exist yet, save it so the next person retrieves it instead of re-deriving it.

Each step ships, we learn from it, and we only spend on the next if the prior one proved the need.

## Where to go next

- **[02-concepts.md](02-concepts.md)** — the core concepts in plain language, with analogies.
- **[03-examples.md](03-examples.md)** — how these map to systems Nava already runs.
- **[04-architecture.md](04-architecture.md)** — the technical design (for engineers).
- **[07-strategy.md](07-strategy.md)** — the phased build plan (for engineers).
