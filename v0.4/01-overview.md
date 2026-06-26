# Leveraging Institutional Knowledge — Overview

*A plain-language introduction to what we're building and why. The concepts are explained in <u>Concepts</u>; engineers should continue to the <u>Strategy</u> and <u>Architecture</u>.*

## The problem

A company's knowledge is scattered across many data sources — storage (Google Drive), wikis (Confluence), trackers (Jira/GitHub), chat (Slack), CRM (Salesforce), HR (Workday), and more. To answer one question, every AI agent, every app, and every person has to search all of those data sources, over and over. That is slow, expensive, inconsistent from one tool to the next, and prone to missing the answer that is most trusted or most current.

## The idea

Leave the knowledge where it already lives, in the **Data Sources** — each stays authoritative for the knowledge it holds, and each keeps controlling who may see what. On top, add a **Discovery Layer**: material *derived* from those sources whose only job is to make knowledge fast to find and reuse — **without** copying everything into one place and **without** becoming a competing authority.

Its outputs come in three kinds, sorted by where each lives and who keeps it safe:

- **Most of it (stored as DS records)** — summaries, indexes, and pointers written back into a Data Source and marked as `discovery-layer` to represent that it is derived. That source stores and backs them up like any record, and can be rebuilt from the sources on demand. Without this prepared material, every tool would re-search the full sources from scratch on each question — the slow, costly repetition the Discovery Layer exists to remove.
- **The Catalog** — an index to look up where a topic's material lives. This is the first place to start answering a user's question or request. It's built only from the `discovery-layer` DS records — not the full sources — so there's far less to keep current; the Catalog is the coarse, topic-level view across multiple DS systems, while those `discovery-layer` DS records carry the same "what exists and where" in finer detail. The Catalog recomputable and doesn't need backup. Without it, a tool would have to search every DS system to learn what exists and where before it could begin.
- **Confirmation signals** — people vouching that the source behind an answer was right, or flagging it wrong. These can't be re-derived, so they're the one part the Discovery Layer must back up. Without them, future answers couldn't favor the sources people have already confirmed or steer clear of ones flagged wrong — so without this, the system would never grow more trustworthy the more it's used.

## The value

- **Faster, cheaper answers** — work is computed once and reused by every tool, instead of every tool re-searching every data source on every question.
- **More trustworthy answers** — answers cite their sources, carry content-freshness signals, and accumulate confirmations from the people who used them.
- **Knowledge stays governed** — each original data source keeps controlling who can see what; the Discovery Layer never becomes a back door to restricted data.
- **Low ongoing cost** — most of the Discovery Layer can be rebuilt or discarded, so there's little to maintain.

## Guiding principles

Every design choice traces back to these.

- **Very low maintenance** — most of the Discovery Layer is recomputed from the sources, so it can be rebuilt or discarded rather than tended; only the part that can't be rebuilt is kept safe — saved answers by the data source that holds them, confirmations by the Discovery Layer itself. "Low maintenance" describes the stored data, not ongoing cost: recomputation is recurring compute, and the skills behind it must be owned and kept current (see <u>Strategy</u>).
- **Loosely coupled** — keep the pieces independent so any one — a store, a source, a tool — can be swapped without rewriting the rest, and no single vendor becomes hard to leave.
- **Intuitive** — lean on standards (e.g., MCP) and common patterns rather than bespoke mechanisms, so people and tools pick it up quickly.
- **Flexible** — adaptable to a wide range of questions, data, and tools: many small, specialized skills instead of one rigid system.
- **Knowledge stays authoritative where it lives** — each piece of knowledge stays authoritative in its original data source. The Discovery Layer holds only computed copies, pointers, and signals — never a competing master record. (Two things are derived but not recomputable, the deliberate exceptions: people's confirmations, and saved answers. A saved answer goes stale because it's written once and not rebuilt, so it drifts as its sources change — but it lives *inside* a data source carrying the `discovery-layer` tag, so it's never mistaken as an original source; staleness flags it and, in time, a person folds its trust back into the sources by hand.)
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
