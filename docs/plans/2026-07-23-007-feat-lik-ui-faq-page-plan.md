---
title: "feat: lik-ui FAQ page"
type: feat
status: completed
date: 2026-07-23
origin: docs/brainstorms/2026-07-23-02-lik-ui-faq-page-requirements.md
---

# feat: lik-ui FAQ page

## Summary

Add an FAQ entry to the lik-ui top navigation that opens a `/faq` page. The page fetches one curated
`faq.md` from the public repo (via a generalized doc-fetch module) and renders it client-side with the
existing marked+DOMPurify pipeline. A separate unit adds stable anchors to the source docs so rendering
canonical doc content inline (the deferred Option B) becomes viable later.

---

## Problem Frame

lik-ui users have no in-app way to learn what the system is, its limits, or which data sources connect;
that information is scattered across repo docs they'd have to know to find on GitHub. The material spans
two audiences (end-user help vs. internal architecture/roadmap), so the page must curate rather than dump.
The FAQ is inherently a curated summary layer, so it accepts *bounded* drift from the canonical docs —
mitigated by keeping answers thin (link-not-copy), not eliminated. See origin for full framing
(Sources & References).

---

## Requirements

- R1. Top-nav FAQ entry opens an in-app FAQ page (not a raw GitHub redirect).
- R2. The page renders one curated FAQ document in-app.
- R3. End-user help and internal/developer material appear in visibly separate sections.
- R4. The curated FAQ doc is the single source for FAQ phrasing; canonical docs stay the single source for
  their own content.
- R5. FAQ answers are brief (short answer + link), not copies of doc bodies.
- R6. Coverage: what the system is / can do, its limitations, data-source MCP status, links into the rest
  of `v0.4/`, and the open engineering items from `lik-ui/README.md` (in the developer section).
- R7. Content is fetched from the public repo at view time, reusing the SKILL.md fetch approach and its
  graceful degradation to a GitHub link on failure.
- R8. The curated FAQ links to *existing* stable headings in the source docs; a source doc gets a new
  anchor added only where a genuine link target is missing. `v0.4/` content is not edited (CLAUDE.md
  guards it against implementation-driven edits). This keeps link targets durable without the speculative
  render-anchor refactor, which is deferred with Option B.

---

## Scope Boundaries

- No rendering of whole `v0.4/` docs or the whole README inline now (that is the Option B end state that
  R8 unblocks).
- No search, feedback widgets, FAQ versioning, or CMS.
- No private/authenticated fetching — continues the public-repo + link-fallback posture.
- No change to the meaning/content of source docs beyond structural refactoring for render-ability.

### Deferred to Follow-Up Work

- Extract the duplicated marked+DOMPurify renderer (`connections.html` inline vs `static/chat.js`) into
  one shared helper: separate refactor PR.
- Render canonical doc sections inline in the FAQ (Option B): future iteration. Its render-anchor refactor
  of the source docs (including any `v0.4/` changes) travels with it, when it has a real consumer.
- Expose `/faq` pre-login (public help): future iteration if desired. Accepted for now that a user staring
  at the login screen with no context is not served — the nav that exposes `/faq` is itself login-gated.
- Add a CSP header across the app as defense-in-depth behind DOMPurify (pre-existing gap, app-wide).

---

## Context & Research

### Relevant Code and Patterns

- Fetch primitive to generalize: `lik-ui/src/lik_ui/skill_docs.py` — `_raw_url` (:18-22, builds
  `raw.githubusercontent.com/{repo}/{ref}/.claude/skills/{name}/SKILL.md`), `skill_source_url` (:25-33,
  human blob URL / fallback), `fetch_skill_instructions` (:36-48, async GET, `timeout=10`, returns `None`
  on `httpx.HTTPError` or non-200, injectable `client_factory`).
- Config: `lik-ui/src/lik_ui/settings.py:105-106` — `skills_repo` (`navapbc/leverage-inst-knowl`),
  `skills_ref` (`main`), `env_prefix="LIK_UI_"`.
- JSON-endpoint + client-render precedent: `lik-ui/src/lik_ui/agents.py:138-152` (`/skill-details`), rendered
  in `lik-ui/src/lik_ui/templates/connections.html:63-64` (CDN libs) and :137-152 (frontmatter strip,
  `DOMPurify.sanitize(marked.parse(body))`, `<pre>` fallback, "view on GitHub" fallback when content is
  `None`).
- Shared render reference: `lik-ui/src/lik_ui/static/chat.js:23-29` (`renderMarkdown`).
- Nav: `lik-ui/src/lik_ui/templates/base.html:12-24` (entries at :14-18; `{% if user %}` gated).
- App factory + router wiring: `lik-ui/src/lik_ui/app.py:27` (`templates`), :100-104 (`register_*_routes`).
- Page pattern: `lik-ui/src/lik_ui/app_auth.py:177-194` (`home()` → `templates.TemplateResponse`);
  templates extend `base.html` (`lik-ui/src/lik_ui/templates/agents.html:1-3`).
- Tests: `lik-ui/tests/test_agents.py` (`_app`/`_login` helpers :109-117; route test :120-138; JSON+
  degradation tests :163-198), `lik-ui/tests/test_skill_docs.py` (`MockTransport` factory :9,:24-88),
  `lik-ui/tests/conftest.py` (fixtures).

### Institutional Learnings

- The SKILL.md view feature is the direct precedent (origin references it); its plan is
  `docs/plans/2026-07-23-003-feat-lik-ui-skill-instructions-view-plan.md`.

### External References

- None needed — the pattern is fully established locally.

---

## Key Technical Decisions

- Curated file at repo **root `faq.md`** (per user), fetched at the existing `skills_repo`/`skills_ref` —
  no new config.
- New generic module `repo_docs.py` for path-based fetch, **and `skill_docs.py` is reduced to a thin
  wrapper over it in this PR** (a skill fetch is `repo_docs` with `path=".claude/skills/{name}/SKILL.md"`).
  Rationale: two hand-maintained copies of the timeout/`HTTPError`/non-200 contract would guarantee the
  divergence this plan claims to avoid; drafting mode (CLAUDE.md: no backward-compat overhead) makes
  collapsing them cheap and correct now. One fetch contract, one code path.
- `/faq` handler fetches **server-side** and embeds the raw markdown into the template for client-side
  render on load — one round-trip, no separate JSON endpoint (the FAQ content is the whole page, unlike the
  lazy-loaded skill "Details").
- **Embedding technique is mandated, not deferred (security):** the raw markdown is carried in a hidden
  non-`<script>` element (e.g. a `<template>`) and read via `.textContent`, never interpolated into a JS
  string literal or a `<script>` block. This defeats both the HTML-escaping-inside-`<script>` trap and the
  `</script>` tag-closure trap at the parser level, *before* `marked`/`DOMPurify` run. Render pipeline is
  then `marked.parse` → `DOMPurify.sanitize` → `innerHTML`, matching `connections.html:137-152`.
- Internal/developer separation is realized as **distinct sections in `faq.md` with explicit visual
  demarcation** (a divider, a distinct developer-section heading, and a one-line "the rest of this page is
  for engineers" framing) — not flat sequential headings, so a non-technical reader gets a clear signal
  before crossing into internal material (R3).
- `/faq` is **login-gated** (`require_user`) for consistency with other pages; nav only renders post-login.
  Security confirmed this adds discoverability, not exposure — the source repo is already public.
- **Full-page fetch blocks the response** (server-side, synchronous). Accepted as a tradeoff consistent
  with the app's other server-rendered pages (no interim loading state); the page fetch uses a **shorter
  timeout than the 10s skill default** to bound worst-case blocking. A slow GitHub fetch that times out
  degrades to the `None` → "view on GitHub" fallback.
- Content goes live only once `faq.md` and its link targets are on the ref the app reads (`main` by
  default) — same behavior as the SKILL.md feature. **`faq.md` and any newly-added anchors must reach
  `main` in the same merge**, or live links break. A `LIK_UI_SKILLS_REF` branch preview repoints *every*
  fetch (skills too), so treat it as illustrative, not isolated.

---

## Open Questions

### Resolved During Planning

- Where does the curated doc live? → repo root `faq.md` (user decision).
- Separate JSON endpoint vs server-side fetch? → server-side fetch + embed (whole-page content).
- How is internal material separated? → distinct sections in `faq.md` with visual demarcation (R3).
- How is the raw markdown embedded safely? → hidden non-`<script>` element read via `.textContent`
  (see Key Technical Decisions); the XSS-relevant choice is settled here, not deferred.
- One fetch module or two? → `repo_docs.py` with `skill_docs.py` as a thin wrapper (user decision).

### Deferred to Implementation

- Exact function/param names in `repo_docs.py` — settle against real code.
- The exact shorter timeout value for the page fetch — pick against observed GitHub latency.

---

## Implementation Units

- U1. **Generalized repo-doc fetch module (and collapse `skill_docs.py` onto it)**

**Goal:** A path-based fetcher for arbitrary markdown files in the public repo, mirroring the SKILL.md
fetch's degradation contract — and the single fetch contract for the app, with `skill_docs.py` reduced to
a thin wrapper so there is only one code path.

**Requirements:** R7

**Dependencies:** None

**Files:**
- Create: `lik-ui/src/lik_ui/repo_docs.py`
- Create: `lik-ui/tests/test_repo_docs.py`
- Modify: `lik-ui/src/lik_ui/skill_docs.py` (reduce `_raw_url`/`skill_source_url`/`fetch_skill_instructions`
  to thin wrappers that call `repo_docs` with `path=".claude/skills/{name}/SKILL.md"`)
- Modify: `lik-ui/tests/test_skill_docs.py` (keep as-is if green through the wrapper; adjust only if the
  wrapper changes call signatures)

**Approach:**
- Provide a raw-URL builder (`raw.githubusercontent.com/{skills_repo}/{skills_ref}/{path}`), a human blob
  source-URL builder (`github.com/{repo}/blob/{ref}/{path}`), and an async `fetch` that GETs the raw URL.
- Reuse `settings.skills_repo` / `settings.skills_ref`; accept a repo-relative `path` argument.
- Contract: catch `httpx.HTTPError` → `None`, non-200 → `None`, never raise; injectable `client_factory`
  for tests. Timeout is a parameter (default matches `skill_docs.py`'s current `10`s; the FAQ caller passes
  a shorter value per Key Technical Decisions).
- Rewrite `skill_docs.py`'s three functions as one-liners over `repo_docs` — no behavior change for the
  skill path; `test_skill_docs.py` must stay green.

**Patterns to follow:**
- `lik-ui/src/lik_ui/skill_docs.py:18-48` (structure and error contract being generalized).

**Test scenarios:**
- Happy path: given a path, the raw URL is built correctly for a custom `skills_repo`/`skills_ref`.
- Happy path: 200 response returns the body text.
- Happy path: the blob source-URL builder is pure (no network) and returns the expected GitHub blob URL.
- Edge case: a custom timeout value is honored (passed through to the client).
- Error path: non-200 (e.g., 404) returns `None`.
- Error path: transport error (`httpx.HTTPError`) returns `None`, does not raise.
- Integration/regression: existing `test_skill_docs.py` scenarios still pass through the wrapper (skill
  raw URL, success, non-200, transport error) — proving no divergence.

**Verification:**
- `uv run pytest lik-ui/tests/test_repo_docs.py lik-ui/tests/test_skill_docs.py` passes; the module never
  raises on network failure; the skill fetch path is unchanged in behavior.

---

- U2. **Ensure link targets exist in source docs (no v0.4/ edits)**

**Goal:** Confirm every heading the FAQ links to already exists; add a stable anchor to a source doc *only*
where a genuine target is missing. No speculative render-anchor refactor, and no edits to `v0.4/`.

**Requirements:** R8

**Dependencies:** None

**Files:**
- Modify (only if a target is missing): `claude-managed-agents.md`, `limitations.md`, `mcp-availability.md`,
  `lik-ui/README.md`
- Not edited: `v0.4/01-overview.md` and other `v0.4/` docs — CLAUDE.md guards these; the FAQ links to their
  existing headings ("The problem / The idea / The value" already serve as targets).

**Approach:**
- The FAQ links to existing headings. Feasibility confirmed the README already has stable `## TODO:` /
  `## DONE:` headings and `01-overview.md` has self-contained lead sections — so this unit is mostly
  verification, adding an anchor only where U3 finds a link with no real target.
- No content or meaning changes to any doc; no `v0.4/` edits at all.

**Execution note:** This unit likely results in zero or near-zero edits. If it starts to look like a doc
rewrite, stop — the render-anchor refactor belongs with Option B, not here.

**Test scenarios:**
- Test expectation: none — link-target verification with no runtime behavior. Enforced mechanically by
  U3's `faq.md` link-resolution test.

**Verification:**
- Every intra-repo link in `faq.md` (U3) resolves to a real heading/file in the checked-out tree; no
  `v0.4/` file was modified.

---

- U3. **Author curated `faq.md`**

**Goal:** The single curated FAQ document: brief end-user answers plus a separate developer section, each
answer linking to a canonical doc rather than restating it.

**Requirements:** R2, R3, R4, R5, R6

**Dependencies:** U2 (links target its anchors)

**Files:**
- Create: `faq.md` (repo root)
- Test: `lik-ui/tests/test_faq_content.py` (network-free content assertions — see Test scenarios)

**Approach:**
- Two sections with **explicit visual demarcation**: an end-user FAQ (what is this / what can it do / what
  are its limits / which sources connect), then a divider, a distinct "For developers" heading, and a
  one-line framing ("the rest of this page is for engineers"), then the developer section (links into
  `v0.4/`, and the open engineering items from `lik-ui/README.md`).
- Each answer: 1-3 sentences + a link to the canonical doc/anchor for depth (R5). No pasted doc bodies.
- Source coverage per R6: `claude-managed-agents.md`, `v0.4/01-overview.md` (+ links to the rest of
  `v0.4/`), `limitations.md`, `mcp-availability.md`, `lik-ui/README.md` open items.
- Links are GitHub URLs to the canonical docs (rendered page opens them on GitHub).
- Do **not** open `faq.md` with a `---` thematic break — a leading `---` would be misread as YAML
  frontmatter and stripped by the render (see U4).

**Execution note:** Content unit — keep answers thin by design to bound drift (R5).

**Test scenarios:**
- Content: `faq.md` parses and contains both the end-user section and the demarcated "For developers"
  section (R3).
- Content: every R6 source (`claude-managed-agents.md`, `v0.4/01-overview.md`, `limitations.md`,
  `mcp-availability.md`, `lik-ui/README.md`) is referenced.
- Link resolution: every intra-repo link/anchor in `faq.md` resolves to a real file/heading in the
  checked-out tree (this is the mechanizable check adversarial review flagged as highest-value — it runs
  in CI on the branch with no live fetch, and is the one guard that the real page isn't first seen in
  production). Enforces U2's verification too.

**Verification:**
- `LIK_UI_DB_PORT=5433 uv run pytest lik-ui/tests/test_faq_content.py` passes; `faq.md` has both demarcated
  sections, every R6 source is represented, no answer copies a source doc's body, and all links resolve.

---

- U4. **`/faq` route, template, and nav entry**

**Goal:** Serve the FAQ page: fetch `faq.md` server-side, render it in-app with graceful degradation, and
add the nav entry.

**Requirements:** R1, R2, R3, R7

**Dependencies:** U1 (fetch primitive); renders U3's content at runtime

**Files:**
- Create: `lik-ui/src/lik_ui/faq.py` (`register_faq_routes(app)`, `@app.get("/faq")`)
- Create: `lik-ui/src/lik_ui/templates/faq.html`
- Modify: `lik-ui/src/lik_ui/app.py` (import + call `register_faq_routes` at :100-104)
- Modify: `lik-ui/src/lik_ui/templates/base.html` (add FAQ nav `<a href="/faq">` at :14-18)
- Test: `lik-ui/tests/test_faq.py`

**Approach:**
- Handler calls `require_user`, fetches `faq.md` via `repo_docs` (U1) with the shorter page timeout, builds
  the blob source-URL, and passes `user` (from `require_user`), the raw content (or `None`), and the
  source-URL into `faq.html`. **`user` is required in the context** or `base.html`'s `{% if user %}`-gated
  header — including the new FAQ nav link — won't render (mirror `app_auth.py` `home()` at :194).
- `faq.html` extends `base.html`; loads marked + DOMPurify from CDN. The raw markdown is embedded in a
  hidden non-`<script>` element (e.g. `<template>`) and read via `.textContent` (see Key Technical
  Decisions — never a JS string literal or `<script>` block). On load: strip a leading YAML frontmatter
  block if present, render `DOMPurify.sanitize(marked.parse(body))` into `innerHTML`; fall back to a `<pre>`
  literal if the CDN libs are absent. **Treat `None` and empty/whitespace-only content the same** — show
  the "view on GitHub" fallback link rather than a blank page. Mirror `connections.html:137-152`.
- Nav link added to `base.html` (visible to logged-in users, matching existing entries).

**Patterns to follow:**
- Route/handler: `lik-ui/src/lik_ui/app_auth.py:177-194` and `agents.py:107-136`.
- Router registration: `lik-ui/src/lik_ui/app.py:100-104`.
- Render + fallback: `lik-ui/src/lik_ui/templates/connections.html:63-64,137-152`.
- Tests: `lik-ui/tests/test_agents.py:109-138,163-198`.

**Test scenarios:**
- Happy path: logged-in GET `/faq` returns 200 and the page HTML embeds the (mocked) fetched markdown.
- Happy path: nav includes an FAQ link pointing to `/faq` on an authenticated page (proves `user` reached
  the template context).
- Edge/degradation: when the fetch returns `None`, the page still renders 200 and shows the "view on GitHub"
  fallback link (assert the blob URL is present) — no error page. (Mirrors `test_agents.py:184-198`.)
- Edge case: fetch returns empty/whitespace-only content → same "view on GitHub" fallback, not a blank page.
- Error path: unauthenticated GET `/faq` is redirected/denied like other gated pages (assert `require_user`
  behavior consistent with an existing gated route).
- Security (adversarial content): fetch returns markdown containing embedded double/single quotes,
  backslashes, and a literal `</script>` substring → the page still renders 200, the content is delivered
  intact to the client carrier element, and no script executes / the page structure isn't broken. This
  exercises the mandated non-`<script>` embedding.
- Integration: the handler passes the `repo_docs` fetch result into the template — monkeypatch the fetch
  (as `test_agents.py` monkeypatches `fetch_skill_instructions`) and assert the body reaches the response.

**Verification:**
- `LIK_UI_DB_PORT=5433 uv run pytest lik-ui/tests/test_faq.py` passes; manually, the FAQ nav link opens a
  rendered page, and a forced fetch failure shows the GitHub fallback rather than an error.

---

## System-Wide Impact

- **Interaction graph:** New route registered alongside existing `register_*_routes` in `app.py`; new nav
  entry in the shared `base.html` (affects every authenticated page's header).
- **Error propagation:** Fetch failures are absorbed in `repo_docs` (return `None`) and degrade to a link —
  no failure reaches the page as a 5xx.
- **API surface parity:** `skill_docs.py` is rewritten as a thin wrapper over `repo_docs.py`, so there is a
  single fetch/degradation contract — no divergence possible. `test_skill_docs.py` must stay green,
  proving the skill path's behavior is unchanged.
- **Unchanged invariants:** the `/skill-details` endpoint and its behavior are unchanged (only `skill_docs`'s
  internals move under `repo_docs`); `settings` gains no new fields; existing nav entries and templates are
  unchanged except the one added FAQ link.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| FAQ content won't render on the PR branch (app reads `main`); the real page is otherwise first seen in production | U3's network-free link/coverage test validates `faq.md` on the branch in CI. A `LIK_UI_SKILLS_REF` branch preview works but repoints *all* fetches, so it's illustrative, not isolated (Key Decisions). |
| Broken links in production if `faq.md` merges before its link targets | `faq.md` and any newly-added anchors must land in the same merge to `main` (Key Decisions); the U3 link-resolution test guards it pre-merge. |
| Curated answers drift from source docs | Accepted as bounded drift inherent to a curated summary layer; mitigated by thin answers (link-not-copy, R5). Not credited to Option B, which is deferred with no scheduled consumer. |
| Rendering markdown fetched from GitHub (XSS) | Mandated non-`<script>` embedding defeats the escaping/`</script>` traps before render; `DOMPurify.sanitize` after `marked.parse` (same as chat/skills). No CSP anywhere in the app — deferred as an app-wide follow-up (Scope Boundaries). |
| A malicious/careless commit to the public repo reaches all logged-in users | Blast radius bounded by DOMPurify; CSP follow-up would add a second layer. Pre-existing to the SKILL.md path, not new here. |
| Repo goes private | Accepted posture; fetch degrades to the GitHub link fallback (R7). |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-23-02-lik-ui-faq-page-requirements.md](docs/brainstorms/2026-07-23-02-lik-ui-faq-page-requirements.md)
- Related code: `lik-ui/src/lik_ui/skill_docs.py`, `lik-ui/src/lik_ui/templates/connections.html`,
  `lik-ui/src/lik_ui/templates/base.html`, `lik-ui/src/lik_ui/app.py`
- Related plan (precedent): `docs/plans/2026-07-23-003-feat-lik-ui-skill-instructions-view-plan.md`
