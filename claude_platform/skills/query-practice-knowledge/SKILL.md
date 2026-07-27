---
name: query-practice-knowledge
description: Answer craft "how-to" and tool-recommendation questions by discipline — design, engineering/frontend, research, accessibility, content strategy, product, service design, data, security, and AI technique. This is peer craft knowledge (how practitioners do the work), distinct from a named project's history or an official org standard. Searches Nava's practice Confluence spaces and the discipline's Slack channels live, synthesizes an answer, and records confirmation feedback. Use for "how do you approach X?", "what's the best practice for Y?", "what tool do people recommend for Z?", "has anyone solved W in a given discipline?". Do NOT use for a named project (query-project-index), an official policy/process (query-org-guidance), or HR questions.
---

# Query Practice Knowledge

Answer a craft question from Nava's practice sources, cite every source that contributed, and record confirmation
signals per cited source (`read_confirmations` / `confirm_source`). The text passed to this skill is the question.

Practice knowledge is **the least formally captured** class: some lives in Confluence practice spaces, much lives in
community-of-practice Slack channels. Be honest about **what kind of source** an answer rests on — a documented practice
page carries more weight than one peer's Slack reply, and you must label the difference.

## Practice sources

Confluence (cloudId `navasage.atlassian.net`), these spaces — discipline craft, standards, and best practices:

| Space key | Discipline |
|---|---|
| `DOH` | Design & Research |
| `PL` | Pattern Library (design patterns/components) |
| `ENG` | Engineering (standards, delivery practices, best practices) |
| `PM1` | Product Management |
| `NL` | Nava Labs (AI research & technique) |
| `TSS` | Technology Solutions and Services (reusable tooling & platforms) |

Slack community-of-practice channels, routed by discipline:

| Discipline | Channels |
|---|---|
| Design (incl. research, content) | `#design`, `#design-communities-of-practice` |
| Engineering / frontend / data / security | `#engineering` |
| Product | `#product-org` |
| Anything else / cross-discipline | search all four channels |

Space keys and channels are configuration — update these tables if Nava adds, renames, or retires a practice space or
CoP channel. GitHub is **not** searched directly: practice Confluence pages link to the relevant repos, so follow those
links rather than searching code.

## Errors

If a tool call fails or a required source is unavailable, **do not stop** — report it (the error, likely cause, remedy)
and continue with the sources and steps still available. Note in the answer which sources were skipped, so the gap is
visible. A failure is not a "nothing found" — don't present a skipped source as an empty result.

## Step 1 — Identify the discipline

Map the question to its discipline (design, engineering/frontend, research, accessibility, content, product, service
design, data, security, AI technique). The discipline picks which Slack channel(s) to search (table above). If ambiguous
between two, search both. The Confluence search spans all practice spaces regardless, so the discipline mainly narrows
the Slack side.

## Step 2 — Search practice sources (durable first, then peer discussion)

**2a — Documented practice (Confluence).** `searchConfluenceUsingCql` (cloudId `navasage.atlassian.net`) over the
practice spaces on the question's key terms:
`space in (DOH, PL, ENG, PM1, NL, TSS) AND type = page AND text ~ "<key terms>"`.
A hit here is a **documented** practice — the strongest kind of answer. If a page links a GitHub repo or a Drive doc
that holds the real detail, follow that link and cite what it holds.

**2b — Peer discussion (Slack).** Search the discipline's community-of-practice channel(s) for prior threads answering
the same question. A Slack answer is **peer opinion**, not a standard — cite the thread and label it as such.

Prefer the cheapest source that answers well; reach for Slack when Confluence is thin or the question is clearly
"what do people recommend". If the question spans disciplines or both source kinds contribute, synthesize **one**
answer — reconcile agreements, surface disagreements — rather than dumping per-source lists.

## Step 3 — Present with source-weight labels

Synthesize the answer, then cite each contributing source (numbered, hyperlinked on its title), **labeled by kind**:
- **Documented practice** — Confluence practice page.
- **Peer discussion** — Slack thread (one practitioner's view unless corroborated by others).

If only weak / peer sources exist, say so plainly — "this is peer practice, not a documented Nava standard" — rather
than overstating confidence.

Per citation:
- `store_kind`: `"confluence"` or `"slack"`
- `location`: the page URL or Slack message permalink
- `locator`: the Confluence page ID, or the Slack `channel` + `ts`
- `source_state`: for Confluence, the live body hash (recipe below); for Slack, the message `ts` already pins the
  version.

Reuse the **content-state marker recipe** and **Response integrity guard** from `query-project-index` for any
Confluence page read: hash the `body` from `getConfluencePage(pageId, contentFormat:"markdown")` with no normalization
(`shasum -a 256 FILE | cut -d' ' -f1`), and before hashing or citing assert each returned `id` matches the requested
`pageId` (and each CQL result belongs to your query); on mismatch re-issue serially until it matches.

`read_confirmations` — pass the citation and `current_source_state` = the same live marker. **Signed ranking:** ups
boost; downs **soft-demote, never hide**; weight `edited_since=false` votes more than `=true`. Annotate positives and
**explain demotions** with the reason and any comment.

## Feedback (after answering)

Offer least-typing feedback:

> *"Was a cited source right or wrong? Reply with its number to vouch it was right (e.g. `2`), or the number with a
> trailing `-` to flag it was wrong (e.g. `2-`). Multiple separated by spaces or commas."*

A bare number (or trailing `+`) = **up**; a trailing `-` = **down**. On a down, ask one pick — *bad retrieval*
(poor/irrelevant) or *wrong content* (factually wrong); on wrong content, ask what's wrong (capture as `comment`) and,
when the source is one the user can edit, offer the correction path. Then `confirm_source` with the **same citation**,
the live marker as `source_state`, the chosen `vote`/`reason`/`comment`, and the user's email as the token. Report
`recorded` or `rejected` (and if rejected, say so — don't retry).
