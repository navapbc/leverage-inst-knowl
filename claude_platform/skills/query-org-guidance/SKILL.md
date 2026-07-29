---
name: query-org-guidance
description: Answer questions about Nava's organizational guidance — standards, processes, approval paths, templates and kickoff artifacts, and tool/license/vendor access — that apply across projects (not one project's work). Searches Nava's guidance Confluence spaces live and follows their links to Google Drive templates, returns cited answers, and records confirmation feedback. Use for "what is Nava's policy on X?", "is there a process for Y?", "does Nava have a license for Z and how do I get access?", "where is the template for W?", "who approves V?". Do NOT use for a named project's history (that's query-project-index), craft how-to (query-practice-knowledge), or HR/benefits questions.
---

# Query Org Guidance

Answer an organizational-guidance question from Nava's guidance sources, cite every page or file that contributed, and
record confirmation signals per cited source (`read_confirmations` / `confirm_source`). The text passed to this skill is
the question.

This is a **findability-first** skill: most of this content already exists but is hard to locate or scattered across
spaces. Your job is to find it and point to it — never invent a policy, a process step, or a license that a source does
not state.

## Guidance sources

Confluence (cloudId `navasage.atlassian.net`), these spaces — org-wide guidance that applies across projects:

| Space key | Covers |
|---|---|
| `NH` | Sage / Nava Handbook — company-wide policies, procedures, and "how we operate / deliver" |
| `BB` | Business Development — bid process, BD templates, proposal prep |
| `PD` | Program Delivery — delivery standards, process, and approval paths |
| `ENG` | Engineering — engineering standards, guardrails, and delivery practices |

`ENG` also serves discipline craft, so `query-practice-knowledge` searches it too; a space may back more
than one topic.

Google Drive holds many of the actual template files that these pages link to.

Space keys are configuration: if Nava adds or renames a guidance space, update this table. Keep the set store-agnostic —
these are the *sources* the skill reads, not the subject of any question.

## Errors

If a tool call fails or a required source is unavailable, **do not stop** — report it (the error, likely cause, remedy)
and continue with the sources and steps still available. Note in the answer which sources were skipped, so the gap is
visible. A failure is not a "nothing found" — don't present a skipped source as an empty result.

## Step 1 — Read the sub-intent

Classify the question into one sub-intent; it picks the search path:
- **Standard / process / policy / approval path** — "what's the rule for…", "who approves…".
- **Template / artifact** — "where's the template for kickoff / RACI / screener…".
- **Tool / license / vendor access** — "does Nava have a license for X / how do I get access".

## Step 2 — Search the guidance sources (cheap → broad, ask before the broadest)

**2a — Targeted Confluence search.** `searchConfluenceUsingCql` (cloudId `navasage.atlassian.net`) over the guidance
spaces, on the question's key terms:
`space in (NH, BB, PD, ENG) AND type = page AND text ~ "<key terms>"`.
Read the top matches. Many guidance pages are **hubs** that link the real artifact (a Google Sheet template, a
sub-page) — follow the in-page link to the specific artifact before answering.

**2b — Templates in Drive.** For a **template / artifact** sub-intent, if the Confluence hub links or names a Google
Drive file, follow it with the Google Drive connection and cite the file itself, not just the hub that named it.

**2c — Broaden (ask first).** If 2a/2b surface nothing usable, ask ONE single-letter pick before widening:

> No guidance page matched. Widen how?
> **(a)** Search the other discipline practice spaces too (design / product / AI standards sometimes live there), or
> **(b)** Site-wide Confluence search (beyond the guidance spaces), or
> **(c)** Search Google Drive for a matching template / doc, or
> **(d)** Stop — report that no source was found.

Act on the pick: **(a)** add `space in (DOH, PL, PM1, NL, TSS)` to the CQL; **(b)** drop the `space` restriction;
**(c)** search Drive; **(d)** report the gap. Note the broadening in the answer.

## Step 3 — Tool / license / vendor honesty

There is **no single tool/license inventory** at Nava, so a "does Nava have X"
question is answered by evidence, not assumption:
- Found a page / doc that states the license or access path → answer and cite it.
- Found only indirect signals (a project using the tool, a passing mention) → say so, labeled as indirect, and cite them.
- Found nothing → say plainly that no source confirms it, and suggest where to ask (e.g. the relevant practice or IT
  channel). **Never** state that Nava does or does not have a license without a source.

## Rank & present (every path)

**Cite every page or file that contributed** — each a numbered source, hyperlinked on its title. Per citation:
- `store_kind`: `"confluence"` or `"gdrive"`
- `location`: the page / file URL
- `locator`: the Confluence page ID or Drive file ID
- `source_state`: the live marker (Confluence body hash — recipe below; for a Drive file, its `modifiedTime` /
  version identifier)

Reuse the **content-state marker recipe** and **Response integrity guard** from `query-project-index` verbatim: hash
the `body` from `getConfluencePage(pageId, contentFormat:"markdown")` written to a file with no normalization
(`shasum -a 256 FILE | cut -d' ' -f1`), and before hashing or citing, assert each returned `id` equals the requested
`pageId` (and each CQL result belongs to your query); on mismatch, re-issue serially until it matches.

`read_confirmations` — pass the citation and `current_source_state` = the same live marker. **Signed ranking:** ups
boost; downs **soft-demote, never hide**; weight `edited_since=false` votes more than `=true`. Annotate positives (e.g.
*"(3 confirmations)"*) and **explain demotions** with the reason and any comment. Surface any **page-stated freshness**
("canonical as of <date>", "Update Frequency", "Verified <date>") you already read in the body.

## Feedback (after answering)

Offer least-typing feedback:

> *"Was a cited source right or wrong? Reply with its number to vouch it was right (e.g. `2`), or the number with a
> trailing `-` to flag it was wrong (e.g. `2-`). Separate multiple sources with a space or comma."*

A bare number (or trailing `+`) = **up**; a trailing `-` = **down**. On a down, ask one pick — *bad retrieval*
(poor/irrelevant) or *wrong content* (factually wrong); on wrong content, ask what's wrong (capture as `comment`) and
offer the correction path (help the user fix the source under their own login). Then `confirm_source` with the **same
citation**, the live marker as `source_state`, the chosen `vote`/`reason`/`comment`, and the user's email as the token.
Report `recorded` or `rejected` (and if rejected, say so — don't retry).
