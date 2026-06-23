# Leveraging Institutional Knowledge — Overview

*A plain-language introduction to what we're building and why. The concepts are explained in <u>Concepts</u>; engineers should continue to the <u>Strategy</u> and <u>Architecture</u>.*

## The problem

A company's knowledge is scattered across many data sources — storage (Google Drive), wikis (Confluence), trackers (Jira/GitHub), chat (Slack), CRM (Salesforce), HR (Workday), and more. To answer one question, every AI agent, every app, and every person has to search all of those data sources, over and over. That is slow, expensive, inconsistent from one tool to the next, and prone to missing the answer that is most trusted or most current.

## The idea

Leave the knowledge where it already lives. On top of it, add a **Discovery Layer** that makes finding things fast — **without** copying everything into one place and **without** creating a second, competing "source of truth."

The Discovery Layer is *mostly computed*: the bulk of it is derived from the original data sources and rebuilt on demand, so it needs no careful tending. The small part that can't be rebuilt is still kept safe: saved answers live in a data source and ride on its backup like any record, while people's confirmations are the one piece the Discovery Layer stores and backs up itself.

## The value

- **Faster, cheaper answers** — work is computed once and reused by every tool, instead of every tool re-searching every data source on every question.
- **More trustworthy answers** — answers cite their sources, carry content-freshness signals, and accumulate confirmations from the people who used them.
- **Knowledge stays governed** — each original data source keeps controlling who can see what; the Discovery Layer never becomes a back door to restricted data.
- **Low ongoing cost** — most of the Discovery Layer can be rebuilt or discarded, so there's little to maintain.

## Guiding principles

Every design choice traces back to these.

- **Very low maintenance** — most of the Discovery Layer is recomputed from the sources, so it can be rebuilt or discarded rather than tended. The small part that can't be rebuilt rides on existing backups: saved answers are backed up by the data source that holds them, and only people's confirmations need a backup the Discovery Layer runs itself. "Low maintenance" means the stored data needs little tending — not that ongoing cost is zero: recomputing it is recurring compute, and the skills that do the recomputing must be owned and kept current (see <u>Strategy</u>).
- **Loosely coupled** — keep the pieces independent so any one — a store, a source, a tool — can be swapped without rewriting the rest, and no single vendor becomes hard to leave.
- **Intuitive** — lean on standards (e.g., MCP) and common patterns rather than bespoke mechanisms, so people and tools pick it up quickly.
- **Flexible** — adaptable to a wide range of questions, data, and tools: many small, specialized skills instead of one rigid system.
- **One source of truth** — authoritative knowledge always stays in its original data source. The Discovery Layer holds only computed copies, pointers, and signals — never a competing master record. (Two things are derived but not recomputable, the deliberate exceptions: people's confirmations, and saved answers. A saved answer goes stale because it's written once and not rebuilt, so it drifts as its sources change — but it lives *inside* a data source carrying the `discovery-layer` tag, so it's never mistaken as an original source; staleness flags it and, in time, a person folds its trust back into the sources by hand.)
- **Secure by default** — least privilege, deny when unsure, and access always enforced by the *original data source*, never by the Discovery Layer's own metadata. A wrong entry can misdirect a lookup but can never unlock a door.
- **Build on existing sign-in** — access reuses the existing Google SSO (single sign-on) and its group permissions instead of standing up a new identity system. (Sources that don't already use Google groups need a one-time mapping — see <u>Architecture</u>.)
- **Earn each step** — add each capability only once the previous one's limits prove it's needed; spend follows evidence, not ambition.

## The approach

We don't commit to the full system up front. The <u>Strategy</u> is a sequence of evidence-driven bets, each justified by a limitation in the one before it:

1. **Buy a commercial tool and learn.** Adopt an existing enterprise-search product, run it for a few months, and catalog exactly where it falls short. If nothing is worth building, we stop here.
2. **Direct access via standard interfaces.** Build our own agent that reads and writes knowledge in the data sources where it already lives, governed by existing sign-in.
3. **Precompute reusable results.** Stop re-searching from scratch by computing summaries, indexes, and pointers once and reusing them.
4. **Add human trust and a single directory.** Let people confirm which answers were right, and give every tool one place to look up where things live.
5. **Grow from real demand.** When someone gets a good answer that didn't exist yet, save it so the next person retrieves it instead of re-deriving it.

Each step ships, we learn from it, and we only spend on the next if the prior one proved the need.

## Where to go next

- **<u>Concepts</u>** — the core concepts in plain language, with analogies.
- **<u>Examples</u>** — how these map to systems Nava already runs.
- **<u>Strategy</u>** — the phased build plan (for engineers).
- **<u>Architecture</u>** — the technical design (for engineers).
