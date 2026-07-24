---
date: 2026-07-23
topic: lik-ui-faq-page
---

# lik-ui FAQ Page

## Summary

Add an FAQ link to the lik-ui top navigation that opens an in-app page rendering a single curated
`faq.md` fetched from the public repo. The FAQ answers questions in its own voice and links down to
the canonical docs instead of copying them, with end-user help and internal/developer material in
visibly separate sections. Source docs get an incremental refactor toward being directly renderable,
so the lower-maintenance "render canonical docs inline" end state becomes viable later.

---

## Problem Frame

lik-ui users (Nava people who sign in to chat with a Managed Agent) have no in-app way to learn what
the system is, what it can and can't do, which data sources connect, or where the deeper design lives.
That information already exists — but scattered across `claude-managed-agents.md`, the `v0.4/` design
docs, `limitations.md`, `mcp-availability.md`, and engineering notes in `lik-ui/README.md`. Today a
user would have to know those files exist and browse them on GitHub.

Two forces make this awkward. First, the material spans two audiences: some is genuine end-user help,
while `v0.4/` and the README TODOs are internal architecture and engineering roadmap that would leak if
dumped verbatim in front of users. Second, whatever surface we build must not become a fifth copy of
content that already lives in those docs — a copy drifts the moment a source doc changes, and the
project's guiding principle is very low maintenance. The cost of getting this wrong is either an FAQ
that misleads users, or one that silently rots.

---

## Requirements

**Navigation and page**
- R1. The lik-ui top navigation bar includes an FAQ entry that opens an FAQ page.
- R2. The FAQ page renders the content of a single curated FAQ document, displayed in-app (not a raw
  redirect to GitHub).
- R3. End-user help and internal/developer material appear in visibly separate sections on the page,
  so a user is not shown internal roadmap or infrastructure caveats mixed into basic help.

**Content sourcing (no duplication)**
- R4. The curated FAQ document is the single source for FAQ phrasing and organization; the canonical
  docs (`claude-managed-agents.md`, `v0.4/*`, `limitations.md`, `mcp-availability.md`,
  `lik-ui/README.md`) remain the single source for their own content.
- R5. FAQ answers are brief (a short answer plus a link to the canonical doc for depth), not copies of
  doc bodies. This bounds summary-vs-source drift.
- R6. The FAQ page covers, at minimum: what the system is and what it can do (from
  `claude-managed-agents.md`, `v0.4/01-overview.md`); its limitations (`limitations.md`); which data
  sources connect and their MCP status (`mcp-availability.md`); links into the rest of `v0.4/`; and the
  open engineering items from `lik-ui/README.md`, placed in the internal/developer section.
- R7. Content is fetched from the public repo at view time using the existing fetch-and-render approach
  (the same mechanism the SKILL.md feature uses), reusing its graceful degradation: any fetch failure
  falls back to a link to the file on GitHub rather than an error.

**Refactor toward the render-inline end state**
- R8. As part of this work, the source docs are refactored incrementally so their content becomes
  directly renderable in-app later — e.g., each has a clean, reader-facing anchor or section the FAQ
  could eventually render inline instead of summarizing. This refactor changes structure, not the
  meaning of the docs.

---

## Success Criteria

- A signed-in lik-ui user can reach the FAQ from the nav and, without leaving the app, understand what
  the system is, its limits, and which sources connect — with deeper docs one click away.
- Updating a canonical doc requires no change to the FAQ page for content the FAQ links to (only the
  curated answers, kept deliberately thin, are maintained by hand).
- Internal/developer material is never interleaved with end-user help.
- A downstream implementer can build R1–R8 without having to decide what content is user-facing vs.
  internal, or how the fetch/render/fallback behaves — those are settled here and by the existing
  SKILL.md precedent.

---

## Scope Boundaries

- Rendering whole `v0.4/` docs or the entire README inline now — that is the deferred end state, gated
  on the R8 refactor.
- Search, feedback widgets, FAQ versioning, or any FAQ content-management system.
- Private or authenticated fetching — continues to assume the public-repo pattern, with the existing
  link fallback if the repo is ever not public.
- Changing the actual content or meaning of the source docs beyond structural refactoring for
  render-ability.

---

## Key Decisions

- Curated FAQ file (Option C) over a raw doc aggregator (Option B) or a bare link hub (Option A):
  the sources are a mix of user-help and internal docs, so an FAQ must be a curated view, not a doc
  dump. A raw aggregator would show whole architecture docs and the entire README to end users; a bare
  link hub sends users to raw GitHub Markdown. C controls exactly what each audience sees while keeping
  answers thin enough to avoid duplication.
- Build on the existing GitHub-fetch + Markdown-render pipeline rather than new machinery: the SKILL.md
  feature already fetches Markdown from this public repo and renders it with graceful degradation to a
  GitHub link. Reusing it keeps carrying cost near zero.
- Refactor source docs toward render-ability now, so Option B (inline canonical docs, lowest drift)
  becomes the natural next step once the docs are shaped for it.

---

## Dependencies / Assumptions

- The repo (`navapbc/leverage-inst-knowl`) stays public for the view-time fetch; the link fallback
  covers the case where it isn't. [Verified: this is the same repo and public-fetch assumption the
  existing SKILL.md feature relies on.]
- The existing `marked`/`DOMPurify` render path and its fallback behavior are reused as-is.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R2, R4][Technical] Where the curated `faq.md` lives in the repo and its exact path.
- [Affects R6][Technical] Which specific README TODO items surface in the internal section, and whether
  they are hand-summarized or linked to `lik-ui/README.md` anchors.
- [Affects R8][Technical] The concrete anchor/section convention the refactor introduces so the FAQ can
  later render canonical doc fragments inline.
