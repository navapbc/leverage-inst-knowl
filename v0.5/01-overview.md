# Leveraging Institutional Knowledge — Overview

*A plain-language introduction to what we're building and why. The concepts are explained in <u>Concepts</u>; engineers should continue to the <u>Strategy</u> and <u>Architecture</u>.*

## The problem

A company's knowledge is scattered across many data sources — storage (Google Drive), wikis (Confluence), trackers (Jira/GitHub), chat (Slack), CRM (Salesforce), HR (Workday), and more. To answer one question, every AI agent, every app, and every person has to search all of those data sources, over and over. That is slow, expensive, inconsistent from one tool to the next, and prone to missing the answer that is most trusted or most current.

## The idea

Leave the knowledge where it already lives, in the **Data Sources** — each stays authoritative for the knowledge it holds, and each keeps controlling who may see what. On top, add a **Discovery Layer**: material — mostly *derived* from those sources — whose only job is to make knowledge fast to find and reuse — **without** copying everything into one place and **without** becoming a competing authority.

Its resources come in three kinds:

- **Most of it (stored as "DL records")** — summaries, indexes, and pointers written back into a Data Source and marked `discovery-layer` to flag their role: an entry point an AI agent looks at first. Most are generated automatically from the sources, though a person may curate or edit one. Without this prepared material, every tool would re-search the full sources from scratch on each question — the slow, costly repetition the Discovery Layer exists to remove.
- **The Catalog** — an index to look up where a topic's material lives, and the first place to start answering a question. It's built only from the DL records — not the full sources — so it's the coarse, topic-level map of what exists and where across many systems. Without it, a tool would have to search every system just to learn what exists before it could begin.
- **Confirmation signals** — people vouching that the source behind an answer was right, or flagging it wrong. Without them, future answers couldn't favor the sources people have already confirmed or steer clear of ones flagged wrong — so the system would never grow more trustworthy the more it's used.

Almost all of this is **disposable** — recomputed from the sources on demand, so it's never backed up; any one such piece can be rebuilt or discarded freely. The parts that are **backed up instead** are those a person **touched by hand**: a DL record someone edited or verified, the answers people save, the Catalog entries people register by hand, and the confirmations they leave. Each is preserved by the store it lives in — a Data Source, or DL's own store.

## The value

- **Faster, cheaper answers** — work is computed once and reused by every tool, instead of every tool re-searching every data source on every question.
- **More trustworthy answers** — answers cite their sources, carry content-freshness signals, and accumulate confirmations from the people who used them.
- **Knowledge stays governed** — each original data source keeps controlling who can see what; the Discovery Layer never becomes a back door to restricted data.
- **Control over what's stored** — the Discovery Layer's own store holds only the entry points it is deliberately given — summaries, indexes, pointers, and confirmation signals — never a bulk copy or search-index of the sources' content. Sensitive material stays in its original source under that source's controls instead of being duplicated into a new store, so there's no second copy to secure and what lands in the Discovery Layer is under our control, not swept in wholesale.
- **Low ongoing cost** — almost everything is rebuilt or discarded on demand; only what a person touched by hand is kept — hand-edited records, saved answers, hand-registered Catalog entries, and confirmations — so there's little to maintain.

## Guiding principles

Every design choice traces back to these.

- **Very low maintenance** — the stored data is mostly disposable: recomputed from the sources, so it can be rebuilt or discarded rather than tended. This describes the data, not ongoing cost — recomputation is recurring compute, and the skills behind it must be owned and kept current (see <u>Strategy</u>).
- **Loosely coupled** — keep the pieces independent so any one — a store, a source, a tool — can be swapped without rewriting the rest, and no single vendor becomes hard to leave.
- **Intuitive** — lean on standards (e.g., MCP) and common patterns rather than bespoke mechanisms, so people and tools pick it up quickly.
- **Flexible** — adaptable to a wide range of questions, data, and tools: many small, specialized skills instead of one rigid system.
- **Knowledge stays authoritative where it lives** — each piece of knowledge stays authoritative in the data source that owns it. The Discovery Layer isn't a place to author authoritative knowledge for its own sake; its resources — DL records, summaries, indexes, pointers, and signals — exist to make that knowledge faster to find. Its safety comes from where those resources live (governed and backed up by the source) and from always citing what they point to, not from a rule that they can never contain original content.
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
