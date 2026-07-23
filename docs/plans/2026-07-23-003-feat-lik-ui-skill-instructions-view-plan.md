---
title: "feat: lik-ui shows full skill instructions from GitHub"
type: feat
status: completed
date: 2026-07-23
origin: docs/brainstorms/2026-07-22-01-skill-instruction-hosting-requirements.md
---

# feat: lik-ui shows full skill instructions from GitHub

## Summary

Make lik-ui's connections page show a skill's full `SKILL.md` on demand by fetching it from the
**public** GitHub repo (raw content, no auth), rather than from Managed Agents. The existing
`/connections/skill` JSON endpoint gains an `instructions` field populated from
`.claude/skills/<name>/SKILL.md` on `main`; the connections page renders it (escaped) beneath the
skill's name/description, with a graceful "unavailable" fallback when the fetch fails.

---

## Problem Frame

lik-ui can show each skill's name and description but not its full instructions. The original blocker
— `beta.skills.versions.download` 403s and no download-capable credential was identified — was closed
as won't-fix in favor of reading from GitHub, which is the single source of truth (see origin R7 and
docs/plans/2026-07-23-001-...-plan.md "Deferred to Follow-Up Work"). That plan deferred this feature
pending one unknown: repo visibility. **Resolved during planning: the repo (`navapbc/leverage-inst-knowl`)
is public**, so the fetch needs no token, no OAuth, and no bundled-files workaround — the deferral
condition is gone.

---

## Requirements

- R1. lik-ui's "show full instructions" renders `SKILL.md` sourced from GitHub, not a Managed Agents download. *(origin R7)*
- R2. The connections page shows a skill's full `SKILL.md` on demand, and degrades gracefully (a fallback message, never a page/endpoint error) when the file can't be fetched.
- R3. No new secret or auth: the feature reads the public repo's raw content.
- R4. When the fetch fails for any reason (including the repo later becoming private), the fallback shows a link to the skill's `SKILL.md` on GitHub so the user can open it themselves.

**Origin actors:** A5 lik-ui viewer. **Origin flows:** F3 view instructions in lik-ui.

---

## Scope Boundaries

- Only `SKILL.md` is shown — not the skill's reference files (those are the agent's on-demand bundle, not a lik-ui viewing concern).
- No Markdown-to-HTML rendering — the raw `SKILL.md` text is shown escaped. Rich rendering is a separate nice-to-have.
- Read-only viewer — no editing of instructions in lik-ui (rejected in the brainstorm).

### Deferred to Follow-Up Work

- **Rendered Markdown** (headings, lists, links) instead of raw text — needs a Markdown dependency and an HTML-sanitization decision; separate PR.
- **Caching the fetched `SKILL.md`** — align with the existing "cache agent `describe` results" TODO in `lik-ui/README.md` if per-expand GitHub fetches become a concern; separate PR.

---

## Context & Research

### Relevant Code and Patterns

- `lik-ui/src/lik_ui/agents.py` — `describe_skill(skill_id, version) -> {name, description}` (the `name` equals the repo skill-dir name — see Key Decisions) and the `GET /connections/skill` endpoint (agents.py:136) returning that as JSON. This endpoint is the integration point.
- `lik-ui/src/lik_ui/oauth_connector.py:126-127` — the **pattern to mirror**: an injected `client_factory or (lambda: httpx.AsyncClient(timeout=10))` so tests supply an `httpx.MockTransport`-backed client. `httpx` is already a lik-ui dependency (used here).
- `lik-ui/src/lik_ui/templates/connections.html` (skill `<details>` list, `.skill-details-btn`, and the `fetch("/connections/skill?...")` JS at ~line 88-113) — where the fetched JSON is rendered inline; extend it to show `instructions`.
- `lik-ui/src/lik_ui/settings.py` — `LIK_UI_`-prefixed pydantic `BaseSettings`; add the repo/ref config here.
- `.claude/skills/<name>/SKILL.md` — the files to fetch; deployed from `main`.

### Institutional Learnings

- None yet (`docs/solutions/` is empty).

---

## Key Technical Decisions

- **Fetch raw content from the public repo; no auth.** Resolves the origin's deferred visibility question — the repo is public, so `https://raw.githubusercontent.com/<repo>/<ref>/.claude/skills/<name>/SKILL.md` is readable with a plain GET. This is the mechanism origin R7 called for, at minimum cost.
- **Address the file by skill *name*, not skill_id.** The deploy pipeline enforces `display_title == SKILL.md name == directory name` (docs/plans/2026-07-23-001-...-plan.md U1), so `describe_skill(...)["name"]` maps directly to `.claude/skills/<name>/SKILL.md`. No id→path lookup needed.
- **Show raw, escaped text — no Markdown rendering.** Avoids a new dependency and any HTML-injection surface; the connections JS renders via `textContent` (not `innerHTML`). Rich rendering is deferred.
- **Graceful degradation, mirroring the connections page.** A failed fetch (404, non-200, timeout, network error) yields `instructions: null` and a fallback line — it never turns the endpoint into a 502 or breaks the page. `describe_skill` failures keep their existing 502 behavior.
- **Always expose a human-facing GitHub link.** The endpoint returns a `source_url` (the GitHub *blob* URL — `https://github.com/{repo}/blob/{ref}/.claude/skills/{name}/SKILL.md`) regardless of fetch success. When `instructions` is present it's a "view on GitHub" affordance; when the fetch failed (e.g., the repo went private and now 404/401s for the app) the fallback links it so the user can open it themselves (R4). The blob URL renders in a browser for anyone on a public repo, and for logged-in authorized users if it's private.
- **Config with public defaults.** `LIK_UI_SKILLS_REPO` (default `navapbc/leverage-inst-knowl`) and `LIK_UI_SKILLS_REF` (default `main`) let a dev point at a fork/branch without code changes.
- **Injectable `client_factory` for the fetcher**, mirroring `oauth_connector.py`, so tests drive it with `httpx.MockTransport`.

---

## Open Questions

### Resolved During Planning

- **Repo visibility** (the origin's deferred blocker): public → raw fetch, no token/bundling.
- **How to address the file**: by skill name, which the deploy pipeline guarantees equals the dir/path.

### Deferred to Implementation

- **Exact endpoint response shape** for `instructions` (e.g., `null` vs an explicit `{available: false}`): pick whatever the connections JS renders most simply; both satisfy R2.
- **Version skew note**: the shown `SKILL.md` is current `main`, which may differ from the exact skill *version* pinned on the agent. Since agents pin `latest` and skills deploy from `main`, `main` ≈ the deployed instructions; acceptable. Surface a caption ("from `main`") if skew is ever confusing.

---

## Implementation Units

- U1. **GitHub `SKILL.md` fetcher**

**Goal:** A function that fetches a skill's `SKILL.md` text from the public repo by skill name, returning the text or `None` on any failure.

**Requirements:** R1, R3

**Dependencies:** None

**Files:**
- Create: `lik-ui/src/lik_ui/skill_docs.py`
- Modify: `lik-ui/src/lik_ui/settings.py` (add `skills_repo`, `skills_ref` with defaults)
- Test: `lik-ui/tests/test_skill_docs.py`

**Approach:**
- `fetch_skill_instructions(name, settings, client_factory=None) -> str | None`: build the *raw* URL `https://raw.githubusercontent.com/{settings.skills_repo}/{settings.skills_ref}/.claude/skills/{name}/SKILL.md`, GET with a short timeout, return `resp.text` on 200, else `None`. Catch `httpx` transport/timeout errors and return `None` — never raise.
- `skill_source_url(name, settings) -> str`: build the human-facing GitHub *blob* URL `https://github.com/{settings.skills_repo}/blob/{settings.skills_ref}/.claude/skills/{name}/SKILL.md` (pure string builder, no network) for the "view on GitHub" / fallback link (R4).
- `client_factory` defaults to `lambda: httpx.AsyncClient(timeout=10)`, injectable for tests (mirror `oauth_connector.py`).

**Patterns to follow:** `lik-ui/src/lik_ui/oauth_connector.py:126-127` (injected client factory + `httpx.MockTransport` in tests); `lik-ui/src/lik_ui/settings.py` (BaseSettings field with default).

**Test scenarios:** *(httpx.MockTransport-backed client)*
- Happy path: transport returns 200 with a body → returns exactly that text; assert the requested URL is the expected raw path for a given name + default repo/ref.
- Edge: non-default `skills_repo`/`skills_ref` → both the raw fetch URL and `skill_source_url` reflect them.
- `skill_source_url`: returns the expected `github.com/.../blob/<ref>/.claude/skills/<name>/SKILL.md` for a given name (pure, no network).
- Error path: 404 → returns `None`.
- Error path: 500 → returns `None`.
- Error path: `httpx.ConnectError` / `httpx.TimeoutException` raised by the transport → returns `None` (does not propagate).

**Verification:** `cd lik-ui && uv run pytest tests/test_skill_docs.py` passes; the function never raises on network/HTTP failure.

---

- U2. **Surface instructions on the connections page**

**Goal:** Extend `/connections/skill` to include the fetched `SKILL.md`, and render it (escaped) in the skill-details view with a graceful fallback.

**Requirements:** R1, R2, R4

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/agents.py` (the `skill_details` endpoint — add `instructions` and `source_url`)
- Modify: `lik-ui/src/lik_ui/templates/connections.html` (render `instructions` beneath name/description via `textContent`; show a fallback line **with the `source_url` link** when `null`; also show a "view on GitHub" link when present)
- Test: `lik-ui/tests/test_agents.py` (extend — it already fakes `AgentsClient`)

**Approach:**
- In `skill_details`: after `describe_skill(...)` succeeds, compute `source_url = skill_source_url(details["name"], settings)` (always) and `instructions = await fetch_skill_instructions(details["name"], settings)` (`None` when unavailable); add both to the JSON. Keep the existing `describe_skill`-failure → 502 path unchanged.
- Frontend: in the existing `fetch("/connections/skill?...")` success handler — when `instructions` is present, append a `<pre>` whose `textContent` is `res.d.instructions`, plus a "view on GitHub" link to `source_url`; when `null`, render a fallback line like "Full instructions unavailable — view on GitHub" linking `source_url`. Use `textContent`, never `innerHTML` (escaping); the link's `href` is `source_url`.

**Patterns to follow:** the existing `skill_details` endpoint and the connections.html skill-details JS (agents.py:136, connections.html ~88-113); FastAPI `TestClient` usage already in `lik-ui/tests/`.

**Test scenarios:**
- Happy path (endpoint): `describe_skill` returns a name + a monkeypatched/injected fetch returning body → JSON has `name`, `description`, `instructions == body`, and `source_url` = the blob URL. *Covers F3.*
- Edge (endpoint): fetch returns `None` → JSON has `instructions: null` **and a non-null `source_url`**, HTTP 200 (page shows the fallback link). *Covers R4.*
- Error path (endpoint, unchanged): `describe_skill` raises → 502 with the existing `detail` shape, and no fetch is attempted.
- Integration/frontend: rendering is JS driving `textContent` — verify manually (see Verification) that the instructions block appears on expand, that raw Markdown/HTML in `SKILL.md` is shown literally, and that the fallback link points at `source_url`.

**Verification:** With a real agent that has a deployed skill, expanding "Details" shows its `SKILL.md` plus a working GitHub link; pointing repo/ref at a nonexistent path shows the fallback with a clickable GitHub link and does not break the page; endpoint tests pass.

---

- U3. **Flip the lik-ui README section to DONE**

**Goal:** Update the "show full skill instructions" section from TODO to done, describing the public-repo raw fetch.

**Requirements:** R1

**Dependencies:** U2

**Files:**
- Modify: `lik-ui/README.md` (the `## TODO: show full skill instructions (SKILL.md)` section)

**Approach:** Documentation only. Note that instructions are read from the public repo's raw `SKILL.md` (source of truth), configurable via `LIK_UI_SKILLS_REPO`/`LIK_UI_SKILLS_REF`, and that rendered Markdown/caching are deferred. Supersedes the "deferred pending repo visibility" note added in docs/plans/2026-07-23-001-...-plan.md's U3.

**Patterns to follow:** the existing README section style (the "DONE:" heading convention already used elsewhere in this README).

**Test scenarios:** Test expectation: none — documentation change, no runtime behavior.

**Verification:** The README section reflects the shipped behavior and points at the two config vars.

---

## System-Wide Impact

- **Interaction graph:** Adds one outbound HTTP dependency (GitHub raw) reached only when a user expands a skill's details. No change to auth, chat, vault, or MCP paths.
- **Error propagation:** Fetch failures are contained in U1 (return `None`); the endpoint and page degrade to a fallback, never a 500/502 from this feature.
- **State lifecycle risks:** None — read-only, no persistence.
- **API surface parity:** Only the `/connections/skill` JSON gains a field; additive, no breaking change to the endpoint's existing consumers.
- **Unchanged invariants:** `describe_skill`'s 502 behavior, login-gating on `/connections/skill`, and the connections page's existing name/description rendering are unchanged.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| GitHub raw is slow/unreachable, delaying the details view. | Short timeout in the fetcher; failure → fallback, not a hang or error. Caching is a deferred follow-up if it matters. |
| Shown `SKILL.md` (from `main`) differs from the skill version pinned on the agent. | Agents pin `latest` and skills deploy from `main`, so they converge; add a "from `main`" caption only if skew confuses users (deferred detail). |
| Repo becomes private later, breaking the unauthenticated fetch. | The fetch degrades to the fallback, which links the skill's GitHub URL so the user can open it themselves (R4). Documented dependency on public visibility (R3); a durable fix (server-side token) is a localized change behind the fetcher's `client_factory` seam. |
| Markdown/HTML in `SKILL.md` injected into the page. | Render via `textContent`/escaped `<pre>`, never `innerHTML`. |

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-22-01-skill-instruction-hosting-requirements.md](docs/brainstorms/2026-07-22-01-skill-instruction-hosting-requirements.md) (R7)
- Related plan: [docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md](docs/plans/2026-07-23-001-feat-skill-instruction-deploy-pipeline-plan.md) (deferred this feature; enforces skill name == dir == path)
- Related code: `lik-ui/src/lik_ui/agents.py`, `lik-ui/src/lik_ui/oauth_connector.py`, `lik-ui/src/lik_ui/templates/connections.html`
