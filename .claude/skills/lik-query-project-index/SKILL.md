---
name: lik-query-project-index
description: Answer questions about Nava's projects using the Discovery Layer Catalog (the lik-mcp service) and the project-index pages it points to. Covers, per project: scope and summary, impact and outcomes, client and agency details, client satisfaction and CPARS ratings, workstreams, capabilities and competencies, tech stack and technologies, tools/templates/frameworks, best practices, team roster (who worked on it), internal and shareable artifacts and deliverables, research findings, annual reports, external comms (blogs/decks), published case studies, and business-development assets. Use whenever someone asks about Nava's past or current work, or about a specific project's people, technology, delivery approach, results, or client. Triggers on questions like "what has Nava done with X?", "find projects related to Y", "which projects involve Z agency", "what tech stack did <project> use?", "who worked on <project>?", "how satisfied was the client on <project>?", "tell me about the <name> project". Do NOT use for HR/policy questions or general web research.
---

# Query Project Index

Answer a project question from the **Catalog** (the lik-mcp service), following its pointers to
project-index pages in Confluence. Also surface and accumulate **confirmation signals** per cited
source (`read_confirmations` / `confirm_source`).

Two widening modes:
- **Retrieval miss** (no project located) → escalate Levels 1→3, **asking before each widening**,
  so the Catalog stays primary and a broad Confluence search is the last resort.
- **Content gap** (project located, but its page lacks the asked-for detail) → check the
  project's own pages automatically, then **ask before widening further** — see **Content gap**.

The text passed to this skill is the user's question.

## Errors

If any tool call fails or a required tool is unavailable, **stop** — do not fall through to the
next level. Present: (1) the error / missing tool name; (2) likely causes (server down, tool not
deployed, stale MCP session); (3) remedies (restart server, reconnect MCP, redeploy).

## Level 1 — Catalog lookup (exact, then fuzzy)

Named project → derive `subject = "project: <name>"` and call `lookup_catalog_entry`
(`entry_type="index"`, that `subject`).

- **Hit:** `getConfluencePage` at the row's `locator` (page ID) or `location` (URL), read, answer
  → **Rank & present**. If the page resolves but lacks the asked-for detail → **Content gap**.
- **Miss**, or the question doesn't name one project exactly: call `search_catalog_entries`
  (`entry_type="index"`, `query` = key terms) — catches partial names, typos, reordered words.
  - **Candidate(s):** follow the top candidate's `locator`/`location`, read, answer →
    **Rank & present**.
  - **None:** → **Level 2**.

`search_catalog_entries` is a bounded top-N keyed lookup (not a full read), so it runs **without**
the ask-before-widening prompt — it stays part of the primary Catalog path.

## Level 2 — list & scan (ask first)

On a Level 1 miss, ask (single-letter pick):

> No exact Catalog match. Widen how?
> **(a)** List all Catalog project-index entries and scan them, or
> **(b)** Skip to a Confluence search over project-index pages.

**(a):** `list_catalog_entries` (`entry_type="index"`); scan rows (match the question's terms
against each `subject` and `category`), pick the most relevant, `getConfluencePage` their
pointers, answer → **Rank & present**. If nothing relevant, ask again before Level 3.
**(b):** → **Level 3**.

## Level 3 — Confluence fallback (ask first)

Only with the user's go-ahead, `searchConfluenceUsingCql`:
- cloudId: `navasage.atlassian.net`
- cql: `label = "project-index" AND text ~ "<key terms>"`

Read top matches, answer — note it came from a **bounded Confluence search**, not the Catalog →
**Rank & present**.

A Catalog miss or broken pointer is never an error — it's a cache miss that degrades to the next
level.

## Content gap — project found but its page doesn't answer

The index/Home page the Catalog points at is a **summary**; most detail lives on child pages in
the same Confluence space. A located page that lacks the asked-for detail — or whose relevant
field/child page is a **placeholder** (e.g. "TBD", "Coming Soon", "No … yet", a blank field) — is
**not** an answer; treat it as a content gap. First search the project's own space automatically;
if that doesn't answer, **stop and ask the user** how to widen.

**Auto — the project's own space.** Nava project spaces share a standard page tree, so map the
question to its likely child page and read that page directly:

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

Find it: `searchConfluenceUsingCql`, cloudId `navasage.atlassian.net`, cql
`space = "<space key>" AND title ~ "<mapped title>" AND type = page` (space key = the located
page's `space.key`, or its `location` URL, e.g. `/spaces/PITIR/` → `PITIR`). This tree is a
**hint, not a guarantee** — thinner or newer projects may omit pages. If the title map misses or
returns nothing, fall back to a full-text scan of the space:
`space = "<space key>" AND type = page AND text ~ "<key terms>"`. Read the matches and answer,
noting the detail came from a child page, not the index.

**Still a gap → report and ask.** If the auto step finds no usable answer — no mapped page, or the
page is placeholder/empty — **report the gap to the user** and ask how to widen (single-letter
pick). Offer the options the page itself earns: alongside the always-available links and
Confluence-search options, add one option **per external pointer the page named** as where the
detail actually lives, and **say what named it** so the offer is grounded, not invented:

> The project's index doesn't capture that — its `<page>` is empty/placeholder. Widen how?
> **(a)** Follow the most likely links I found so far (the pages reference external docs/links), or
> **(b)** Run a Confluence-wide search on the key terms (beyond this project), or
> **(c)** Check `<system type>` `<the pointer the page named>` — *the `<page>` says `<quote/paraphrase:
>     e.g. "synced from Workday", or links a `program-review-…` channel>`*, so the live detail
>     likely lives there, or
> **(d)** Something else — tell me.

Include a **(c)**-style option only when the page genuinely names such a pointer — an external
system it syncs from, a chat channel, a linked tool/doc. **Name the pointer's system type** (e.g.
"Slack channel", "Workday", "Google Doc", "Jira board") — a bare name like `program-review-wa-ui`
or "the channel" is ambiguous; the user must see *what kind of thing* it is to judge the option.
List one per distinct pointer; cite the exact in-page reference (a quoted phrase or the link text)
as the reason. This stays store-agnostic: don't assume any particular system exists — surface
whatever *this* page pointed at, labeled by its type. If acting on a pointer needs a tool you don't have (no connector for that system), still offer
it but note you'd need that access — or that the user may have to look there themselves.

Act on the pick. For **(a)**, fetch the specific linked pages/docs you already surfaced. For
**(b)**, `searchConfluenceUsingCql` on `text ~ "<key terms>"` with no `space`/`label` restriction;
note the answer came from a broad search, not the Catalog or this project. For a **(c)** pointer,
follow it with whatever tool fits (e.g. fetch the linked page, search the named channel); if no
such tool is available, say so and stop rather than guessing.

Apply the **Response integrity guard** and **marker recipe** to every page read here, and cite
each page drawn from in **Rank & present**. If nothing surfaces the detail, say so plainly — it
genuinely isn't captured.

## Rank & present (every level)

**Cite every page that contributed to the answer** — whichever level/method surfaced it (Level 1
hit or fuzzy candidate, Level 2 scan pick, Level 3 search, Content-gap (a)/(b)) — each as its own
**numbered** source. The numbered citations are what the user votes on in **Feedback**, so an
uncited page can never be confirmed or flagged. When in doubt, cite.

Each citation:
- `store_kind`: `"confluence"`
- `location`: the page URL
- `locator`: the page ID
- `source_state`: the live body hash (marker recipe below), from the `getConfluencePage` you
  already ran to read the page. Compute it once per page per run and reuse it for both the
  citation and the `current_source_state` you read confirmations with, so they line up.

**Marker recipe (shared with `lik-sync-catalog-from-project-indexes`).** Take the `body` field
**verbatim** from `getConfluencePage(pageId, contentFormat:"markdown")`, write it to a file (no
added trailing newline, no normalization), and hash: `shasum -a 256 FILE | cut -d' ' -f1` (or
`sha256sum FILE | cut -d' ' -f1`). The sync skill stores `source_state` this identical way, so a
live marker equals the stored one whenever content is unchanged. The connector exposes no stable
native signal (no version number; `lastModified` is only a relative string like
`"about 5 hours ago"`), so the body hash is the only reliable marker — see
[../../../limitations.md](../../../limitations.md).

**Response integrity guard (required).** Concurrent `getConfluencePage` / `searchConfluenceUsingCql`
calls can silently return the **wrong page**'s body, with no error (see
[../../../limitations.md](../../../limitations.md)) — hashing it yields a `source_state` for the
wrong page, corrupting confirmations and `edited_since`. Before you hash or cite any page, assert
the returned object's `id` equals the requested `pageId` (and that each CQL result belongs to the
query you sent); on mismatch, re-issue that single call serially until the `id` matches. Parallel
fetches are fine as long as each response passes this check first.

`read_confirmations` — pass the citation **and** `current_source_state` = the same live body hash.
Returns one row per voter:
- `confirmed_by`
- `vote` — `up` (source was right) / `down` (wrong)
- `reason` — for a down, `bad-retrieval` (poor/irrelevant) or `wrong-content` (factually wrong);
  `null` for an up
- `comment` — optional free-text note (mostly on `wrong-content` downs)
- `edited_since` — `true` if the voter's content has since changed (stored marker ≠ live),
  `false` if it still matches, `null` if unknown.

**Signed ranking:** ups boost, downs **soft-demote — never hide**. Rank a source lower when downs
outweigh ups, but still return it. Weight `edited_since=false` votes more heavily than `=true`
ones (a vote on since-changed content — including a wrong-content flag whose source was since
corrected — counts only weakly). Annotate each cited source:
- positives, e.g. *"(3 confirmations, 1 on a since-edited version)"*;
- downs — **explain the demotion** with the reason kind and any `comment`, e.g.
  *"(demoted — flagged by 2: wrong content — 'states the 2019 rate, superseded in 2022')"*.

**Page-stated freshness.** If a cited page states its own currency in the body you already read —
a "canonical as of <date>" note, an "Update Frequency", or a "Verified <date>" stamp — surface it
alongside the confirmation annotations, so the user sees how current the page claims to be. Read
from the body you already have; don't fetch extra pages for this.

**Presenting sources.** Each source is a hyperlink on its title — the `location` URL is the href.
- **Don't show the page ID** (the `locator`). It's needed only to build the citation/tool calls,
  never in the displayed Source line.
- **Only annotate confirmations when there are any.** If `read_confirmations` returned rows,
  summarize them (the signed-ranking annotations above). If it returned none, **say nothing** —
  do not print "No prior confirmations" or equivalent.

## Feedback (after answering)

Offer least-typing feedback:

> *"Was a cited source right or wrong? Reply with its number to vouch it was right (e.g. `2`), or
> the number with a trailing `-` to flag it was wrong (e.g. `2-`)."*

A bare number (or trailing `+`) = **up**; a trailing `-` = **down**.

**On a down**, ask one pick — *bad retrieval* (poor/irrelevant) or *wrong content* (factually
wrong):
- **bad retrieval** → record immediately (`vote="down"`, `reason="bad-retrieval"`).
- **wrong content** → ask *"What's wrong with it?"*, capture the reply as `comment`
  (`vote="down"`, `reason="wrong-content"`), **and** offer the correction path: help the user fix
  the source under their own login (e.g. edit the Confluence page). Logged regardless of whether
  they correct it.

Then `confirm_source` with the **same citation** (live body hash as `source_state`), the chosen
`vote`/`reason`/`comment`, and the user's email as the token (so `confirmed_by` is the real
person, not the service account). One current vote per source — re-voting replaces the prior vote
and updates the voter's stored marker to current content. Report:
- `recorded` — saved (or replaced).
- `rejected` — didn't go through (citation didn't resolve, or a down without a valid reason); say
  so and don't retry.
