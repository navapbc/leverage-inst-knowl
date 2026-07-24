---
name: lik-query-project-index
description: Answer questions about Nava's projects using the Discovery Layer Catalog (the lik-mcp service) and the project-index pages it points to. Covers, per project: scope, impact and outcomes, client and agency, client satisfaction and CPARS ratings, workstreams, capabilities, tech stack, tools/templates/frameworks, best practices, team roster, artifacts and deliverables, research findings, case studies, and business-development assets. Use whenever someone asks about Nava's past or current work, or a project's people, technology, delivery approach, results, or client. Triggers on questions like "what has Nava done with X?", "find projects related to Y", "which projects involve Z agency", "what tech stack did a project use?", "who worked on a project?", "how satisfied was the client on a project?", "tell me about a named project". Do NOT use for HR/policy questions or general web research.
---

# Query Project Index

Answer a project question from the **Catalog** (lik-mcp), following its pointers to project-index pages in Confluence,
and accumulate **confirmation signals** per cited source (`read_confirmations` / `confirm_source`). The text passed to
this skill is the question.

Two widening modes:
- **Retrieval miss** (no project located) → escalate Levels 1→3, **asking before each widening** — the Catalog stays
  primary, a broad Confluence search is the last resort.
- **Content gap** (project located, page lacks the detail) → check the project's own pages automatically, then **ask
  before widening** — see **Content gap**.

## Errors

If any tool call fails or a required tool is unavailable, **stop** — don't fall through to the next level. Report:
- the error / missing tool;
- likely causes (server down, tool not deployed, stale MCP session);
- remedies (restart server, reconnect MCP, redeploy).

## Level 1 — Catalog lookup (exact, then fuzzy)

Named project → `lookup_catalog_entry` (`entry_type="index"`, `subject="<name>"`) → matching pointers `entries`,
**ranked best-first** (verified over unverified, then fresher). Confirmation-based boost/demotion is **not** in this
order — this skill applies it in **Rank & present** after reading confirmations live.
- **Hit** (`count ≥ 1`): follow the **top** entry's `locator`/`location` with `getConfluencePage`, read, answer →
  **Rank & present**. The top row is the default; if several came back (independent saves on the same key), cite the
  others only when they add detail. If the page resolves but lacks the detail → **Content gap**.
- **Miss** (`count = 0`), or the question names no single project: `search_catalog_entries` (`entry_type="index"`, `query`=key terms)
  — catches partial names, typos, reordering.
  - **Candidate(s):** follow the top candidate's `locator`/`location`, read, answer → **Rank & present**.
  - **None:** → **Level 2**.

`search_catalog_entries` is a bounded top-N keyed lookup, not a full read, so it runs **without** the
ask-before-widening prompt — still the primary Catalog path.

## Level 2 — list & scan (ask first)

On a Level 1 miss, ask (single-letter pick):

> No Catalog match found. How should the search be widened?
> **(a)** List all Catalog project-index entries and scan them, or
> **(b)** Skip to a Confluence search over project-index pages.

**(a):** `list_catalog_entries` (`entry_type="index"`); scan each row's `subject` and `category` against the question's
terms, pick the most relevant, `getConfluencePage` its pointer, answer → **Rank & present**. Nothing relevant → ask
again before Level 3.
**(b):** → **Level 3**.

## Level 3 — Confluence fallback (ask first)

Only with the user's go-ahead, 
`searchConfluenceUsingCql` (cloudId `navasage.atlassian.net`, cql `label = "project-index" AND text ~ "<key terms>"`).
Read top matches, answer, noting it came from a **bounded Confluence search**, not the Catalog → **Rank & present**.

A Catalog miss or broken pointer is never an error — it's a cache miss that degrades to the next level.

## Content gap — project found but its page doesn't answer

The page the Catalog points at is a **summary**; most detail lives on child pages in the same space. A page that lacks
the detail — or whose relevant field/child page is a **placeholder** ("TBD", "Coming Soon", "No … yet", blank) — is
**not** an answer. First search the project's own space automatically; if that fails, **stop and ask** how to widen.

**Automatic — the project's own space.** Spaces share a standard page tree; map the question to its likely child page and
read it directly:

| Question is about… | Likely page |
|---|---|
| scope / summary / what the project is | `1.1 Project Scope` |
| impact, outcomes, results | `1.2 Project Impact` |
| client / agency | `1.3 Client Details` |
| client satisfaction, CPARS ratings | `1.4 Client Satisfaction Results` |
| workstreams | `1.5 Workstreams Overview` |
| capabilities, competencies | `2.1 Capabilities and Competencies` |
| tech stack, technologies | `2.2 Tech Stack / Technology` |
| tools, templates, frameworks | `2.3 Templates, Tools, Frameworks` |
| best practices, lessons | `2.4 Best Practices` |
| team, who worked on it, roster | `3.1 Team Roster` |
| artifacts, deliverables, sprint reports | `4.1 Artifacts (Internal)` / `4.2 Artifacts (Shareable)` |
| research, discovery findings | `4.3 Research Index` |
| annual reports | `4.4 Annual Reports` |
| blogs, decks, external comms | `5.1 External Comms` |
| case studies | `5.2 Published Case Studies` |
| BD / proposal assets | `5.3 BD Asset Index` |

Find it with `searchConfluenceUsingCql` (cloudId `navasage.atlassian.net`, cql
`space = "<space key>" AND title ~ "<mapped title>" AND type = page`; space key = the located page's `space.key` or its
`location` URL, e.g. `/spaces/PITIR/` → `PITIR`). The tree is a **hint, not a guarantee** — thinner/newer projects omit
pages. If the title map misses, fall back to a full-text scan:
`space = "<space key>" AND type = page AND text ~ "<key terms>"`. Answer, noting the detail came from a child page, not
the index.

**Still a gap → report and ask.** If the auto step finds nothing usable — no mapped page, or it's placeholder/empty —
**report the gap** and ask how to widen (single-letter pick). Offer the options the page earns: the always-available
links and Confluence-search options, plus one option **per external pointer the page named**, **saying what named it**
so the offer is grounded:

> The project's index doesn't capture that — its `<page>` is empty/placeholder. Widen how?
> **(a)** Follow the most likely links I found so far (the pages reference external docs/links), or
> **(b)** Run a Confluence-wide search on the key terms (beyond this project), or
> **(c)** Check `<system type>` `<the pointer the page named>` — *the `<page>` names it (e.g. it says "synced from
> Workday", or links a `program-review-…` channel)* — so the live detail likely lives there, or
> **(d)** Something else — tell me.

Add a **(c)**-style option only when the page genuinely names a pointer — a system it syncs from, a chat channel, a
linked tool/doc. **Name the pointer's system type** ("Slack channel", "Workday", "Google Doc", "Jira board"); a bare
`program-review-wa-ui` or "the channel" is ambiguous. One option per pointer, citing the exact in-page reference as the
reason. Stay store-agnostic: assume no particular system — surface whatever *this* page pointed at, labeled by type. If
acting on a pointer needs a tool you lack, still offer it but note the access gap (or that the user may look
themselves).

Act on the pick:
- **(a)** fetch the surfaced links/docs;
- **(b)** `searchConfluenceUsingCql` on `text ~ "<key terms>"` with no `space`/`label` restriction, noting the broad
  search;
- **(c)** follow the pointer with whatever tool fits — if none is available, say so and stop rather than guess.

Apply the **Response integrity guard** and **marker recipe** to every page read, and cite each in **Rank & present**. If
nothing surfaces the detail, say so plainly.

## Rank & present (every level)

**Cite every page that contributed**, whatever surfaced it (Level 1 hit/candidate, Level 2 scan, Level 3 search,
Content-gap (a)/(b)/(c)) — each a **numbered** source. Citations are what the user votes on in **Feedback**; an uncited
page can't be confirmed or flagged. When in doubt, cite.

Each citation:
- `store_kind`: `"confluence"`
- `location`: the page URL
- `locator`: the page ID
- `source_state`: the live body hash (recipe below)

Compute the hash once per page per run and reuse it for both the citation and the `current_source_state` you read
confirmations with.

**Marker recipe (shared with `lik-sync-catalog-from-project-indexes`).** Take the `body` **verbatim** from
`getConfluencePage(pageId, contentFormat:"markdown")`, write it to a file (no added trailing newline, no normalization),
and hash: `shasum -a 256 FILE | cut -d' ' -f1` (or `sha256sum`). The sync skill stores `source_state` identically, so a
live marker equals the stored one when content is unchanged. The connector exposes no stable native signal (no version
number; `lastModified` is only a relative string like `"about 5 hours ago"`), so the body hash is the only reliable
marker.

**Response integrity guard (required).** Concurrent `getConfluencePage` / `searchConfluenceUsingCql` calls can silently
return the **wrong page**'s body, with no error — hashing it
corrupts confirmations and `edited_since`. Before hashing or citing, assert the returned `id` equals the requested
`pageId` (and each CQL result belongs to your query); on mismatch, re-issue that call serially until the `id` matches.
Parallel fetches are fine once each passes this check.

`read_confirmations` — pass the citation **and** `current_source_state` = the same live hash. One row per voter:
- `confirmed_by`
- `vote` — `up` (right) / `down` (wrong)
- `reason` — on a down, `bad-retrieval` (poor/irrelevant) or `wrong-content` (factually wrong); `null` on an up
- `comment` — optional note (mostly on `wrong-content` downs)
- `edited_since` — `true` if the voter's content has since changed (stored ≠ live), `false` if unchanged, `null` if
  unknown.

**Signed ranking:** ups boost; downs **soft-demote, never hide** — rank lower when downs outweigh ups, but still return.
Weight `edited_since=false` votes more than `=true` (a vote on since-changed content counts only weakly). Annotate each
source:
- positives, e.g. *"(3 confirmations, 1 on a since-edited version)"*;
- downs — **explain the demotion** with the reason and any `comment`, e.g. *"(demoted — flagged by 2: wrong content —
  'states the 2019 rate, superseded in 2022')"*.

**Page-stated freshness.** If a cited page states its own currency in the body you already read — "canonical as of
<date>", "Update Frequency", "Verified <date>" — surface it alongside the confirmation annotations. Read from the body
you have; don't fetch extra pages.

**Presenting sources.** Each source is a hyperlink on its title (the `location` URL).
- **Don't show the page ID** (`locator`) — it's only for building citations/tool calls.
- **Annotate confirmations only when there are some.** None → say nothing (no "No prior confirmations").

## Feedback (after answering)

Offer least-typing feedback:

> *"Was a cited source right or wrong? Reply with its number to vouch it was right (e.g. `2`), or
> the number with a trailing `-` to flag it was wrong (e.g. `2-`). Provide multiple citations separated by spaces or commas."*

A bare number (or trailing `+`) = **up**; a trailing `-` = **down**.

**On a down**, ask one pick — *bad retrieval* (poor/irrelevant) or *wrong content* (factually wrong):
- **bad retrieval** → record immediately (`vote="down"`, `reason="bad-retrieval"`).
- **wrong content** → ask *"What's wrong with it?"*, capture the reply as `comment` (`vote="down"`,
  `reason="wrong-content"`), **and** offer the correction path — help the user fix the source under their own login
  (e.g. edit the Confluence page). Logged whether or not they fix it.

Then `confirm_source` with the **same citation** (live hash as `source_state`), the chosen `vote`/`reason`/`comment`,
and the user's email as the token (so `confirmed_by` is the real person, not the service account). One vote per source —
re-voting replaces the prior one and updates the voter's marker to current content. Report:
- `recorded` — saved (or replaced);
- `rejected` — didn't go through (citation didn't resolve, or a down without a valid reason); say so, don't retry.
