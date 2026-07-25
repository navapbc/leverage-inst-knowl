---
title: "feat: Make lik-ui private-repo-safe (link-only skills, bundled FAQ)"
type: feat
status: active
date: 2026-07-24
origin: docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md
---

# feat: Make lik-ui private-repo-safe (link-only skills, bundled FAQ)

## Summary

Remove lik-ui's two runtime fetches from `raw.githubusercontent.com` so the GitHub repo can go private.
Skill instructions on the connections page become a "view on GitHub" link only (no in-app render);
`faq.md` moves into the lik-ui package and is read locally. The now-dead fetch helpers in
`repo_docs.py` are removed, keeping only the pure blob-URL builders that back the links.

---

## Problem Frame

lik-ui's only dependency on the repo being **public** is a tokenless raw fetch in
[repo_docs.py](lik-ui/src/lik_ui/repo_docs.py), used by the FAQ page (`faq.md`) and the connections
page (`SKILL.md`). Agent specs now live in the repo (shipped agent-spec pipeline), so it should be able
to go private — which breaks those fetches (see origin: docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md).

---

## Requirements

- R1. No production code path fetches `SKILL.md` or `faq.md` from `raw.githubusercontent.com`.
- R2. `faq.md` is packaged into the lik-ui image and read locally; the FAQ page renders it inline,
  unchanged from the viewer's perspective.
- R3. The connections page shows skill entries with a working "view on GitHub" link; it no longer
  renders `SKILL.md` in-app.
- R4. "View on GitHub" links are retained and point at correct blob URLs.
- R5. `settings.skills_repo` / `settings.skills_ref` are retained only as far as needed to build blob
  URLs; the fetch-only URL builder is removed.
- R6. The connections page carries a note that the linked GitHub instructions may not exactly match
  what is currently deployed.
- R7. After merge, the repo can be flipped to **private** with no lik-ui runtime regression.

---

## Scope Boundaries

- Not adding a server-side GitHub token or any authenticated fetch.
- Not bundling `claude_platform/skills/` — skill instructions are link-only, not shipped in the image.
- No Docker, docker-compose, or CI/build-context changes (the relocated `faq.md` stays inside the
  existing `lik-ui/` build context).
- Not changing who can view the FAQ or connections pages (auth unchanged).

### Deferred to Follow-Up Work

- Flipping the GitHub repo to private: a repo-settings action done after this merges, not a code change.
  Covered under Documentation / Operational Notes.

---

## Context & Research

### Relevant Code and Patterns

- [repo_docs.py](lik-ui/src/lik_ui/repo_docs.py) — `raw_doc_url` (L23), `repo_doc_source_url` (L27, pure,
  keep), `fetch_repo_doc` (L35, remove).
- [skill_docs.py](lik-ui/src/lik_ui/skill_docs.py) — `fetch_skill_instructions` (L31, remove),
  `skill_source_url` (L26, keep), `_skill_path` (L18, keep for the link path).
- [faq.py](lik-ui/src/lik_ui/faq.py) — `GET /faq` fetches `faq.md` (L28) then builds `source_url` (L33).
- [agents.py](lik-ui/src/lik_ui/agents.py) — `/skill-details` (L181) sets `source_url` (L193) and
  `instructions` (L194); remove the `instructions` line and import.
- [connections.html](lik-ui/src/lik_ui/templates/connections.html) — inline JS (L94-154) fetches
  `/skill-details`, sets the GitHub link (L124), and renders `instructions` markdown via marked +
  DOMPurify (L127-153). Remove the markdown-render branch; keep the link.
- **Package-data precedent (mirror this):** `agents.toml` ships via
  [pyproject.toml](lik-ui/pyproject.toml) `[tool.setuptools.package-data]` (L34-35) and is read from
  `Path(__file__).parent / "agents.toml"` with an overridable `agents_config_path`
  ([settings.py](lik-ui/src/lik_ui/settings.py) L19, L125).

### Institutional Learnings

- The Dockerfile does a non-editable `pip install .`, so any bundled non-Python file must be declared in
  `package-data` or it will not land in the image ([pyproject.toml](lik-ui/pyproject.toml) L31-33).

---

## Key Technical Decisions

- **Skill instructions become link-only** rather than bundled: avoids relocating/copying the
  `claude_platform/skills/` tree (which lives outside the `lik-ui/` Docker build context) and the
  Docker/CI changes that would require. (see origin)
- **`faq.md` is relocated into `src/lik_ui/`** rather than copied at build time: it is lik-ui's own
  content with no other consumer, so its natural home is the package. This keeps it inside the existing
  build context and `package-data` — no build-topology change. Its "view on GitHub" blob URL path is
  updated to the new location.
- **Read `faq.md` via an overridable settings path** mirroring `agents_config_path`, so tests can point
  at a fixture and the default resolves inside the installed package.
- **`settings.skills_repo` / `skills_ref` stay** — `repo_doc_source_url` still needs them to build blob
  URLs for the links.

---

## Open Questions

### Resolved During Planning

- How to get docs into the image given the narrow build context: solved by not bundling skills (link
  only) and relocating `faq.md` into the package.
- Whether to keep "view on GitHub" links: keep (viewers have repo access).

### Deferred to Implementation

- Exact helper/setting names (e.g., a `faq_path` setting vs. reading `Path(__file__).parent` directly in
  `faq.py`) — decide when touching the code; mirror the `agents_config_path` shape.
- Whether the `.skill-instructions` CSS in [app.css](lik-ui/src/lik_ui/static/app.css) (L74-78) and the
  marked/DOMPurify `<script>` includes in `connections.html` are fully removable — confirm no other view
  uses them before deleting.

---

## Implementation Units

- U1. **Bundle `faq.md` into the package and read it locally**

**Goal:** The FAQ page renders `faq.md` from the package instead of fetching it over the network.

**Requirements:** R1, R2, R4

**Dependencies:** None

**Files:**
- Move: `faq.md` → `lik-ui/src/lik_ui/faq.md`
- Modify: `lik-ui/pyproject.toml` (add `faq.md` to `package-data`)
- Modify: `lik-ui/src/lik_ui/faq.py` (read from package path; drop the fetch)
- Modify: `lik-ui/src/lik_ui/settings.py` (optional overridable `faq_path`, mirroring
  `agents_config_path`)
- Modify: `lik-ui/src/lik_ui/repo_docs.py` (update `repo_doc_source_url` call site / path so the FAQ blob
  link points at the new `faq.md` location)
- Test: `lik-ui/tests/test_faq.py`, `lik-ui/tests/test_faq_content.py`

**Approach:**
- Read the bundled file at request time and render it exactly as today; keep the graceful "unavailable →
  view on GitHub" fallback for a missing/unreadable file.
- The FAQ `source_url` must reflect the new repo path (`lik-ui/src/lik_ui/faq.md`).

**Patterns to follow:**
- `agents.toml` packaging + `Path(__file__).parent` load in [settings.py](lik-ui/src/lik_ui/settings.py).

**Test scenarios:**
- Happy path: `GET /faq` returns 200 and the rendered body contains known content from the bundled
  `faq.md` — with no network access available (no `raw.githubusercontent.com` call).
- Edge case: bundled file missing/unreadable → page still renders the fallback with a working
  "view on GitHub" link, no 500.
- Happy path: the FAQ `source_url` points at the new `lik-ui/src/lik_ui/faq.md` blob path.
- `test_faq_content.py`: the bundled file is discoverable at the package path the loader uses.

**Verification:**
- Running the app with outbound network blocked still serves a fully-rendered FAQ page.

---

- U2. **Make skill instructions link-only on the connections page**

**Goal:** The connections page shows each skill's name/description and a "view on GitHub" link, with no
in-app `SKILL.md` fetch or render.

**Requirements:** R1, R3, R4, R6

**Dependencies:** None

**Files:**
- Modify: `lik-ui/src/lik_ui/agents.py` (drop the `instructions` field and `fetch_skill_instructions`
  import/use in `/skill-details`; keep `source_url`)
- Modify: `lik-ui/src/lik_ui/templates/connections.html` (remove the `instructions` markdown-render
  branch and marked/DOMPurify includes; keep the link; add the "may not match deployed" note)
- Modify: `lik-ui/src/lik_ui/static/app.css` (remove now-unused `.skill-instructions` rules if nothing
  else uses them)
- Modify: `lik-ui/src/lik_ui/skill_docs.py` (remove `fetch_skill_instructions` and `_raw_url`; keep
  `skill_source_url` / `_skill_path`)
- Test: `lik-ui/tests/test_agents.py`, `lik-ui/tests/test_skill_docs.py`

**Approach:**
- `/skill-details` returns name/description + `source_url` only. The frontend renders the link plus a
  short note (R6); wording/placement is the implementer's to finalize per repo UI conventions.

**Patterns to follow:**
- Existing `/skill-details` response shape and the connections page's existing link element (the `gh`
  anchor already set from `source_url`).

**Test scenarios:**
- Happy path: `/skill-details` response includes `source_url` and no longer includes `instructions`.
- Happy path: the endpoint performs no `raw.githubusercontent.com` request (no fetch on this path).
- Edge case: a skill whose `SKILL.md` would previously have 404'd still returns a normal response with a
  link (no dependency on fetch success).
- `test_skill_docs.py`: `skill_source_url` still builds the correct blob URL; the removed fetch function
  is gone.

**Verification:**
- The connections page renders skill entries with a working GitHub link and the deployed-mismatch note,
  and issues no doc fetch.

---

- U3. **Remove the dead fetch machinery**

**Goal:** Delete the now-unused fetch code so no code path can reach `raw.githubusercontent.com`.

**Requirements:** R1, R5, R7

**Dependencies:** U1, U2

**Files:**
- Modify: `lik-ui/src/lik_ui/repo_docs.py` (remove `fetch_repo_doc` and `raw_doc_url`; keep
  `repo_doc_source_url`; update the module docstring)
- Modify: `lik-ui/tests/test_repo_docs.py` (drop fetch tests; keep/adjust the source-URL test)
- Modify: `lik-ui/src/lik_ui/settings.py` only if a `skills_*` usage is now fully dead (expected: keep
  both — still used by `repo_doc_source_url`)

**Approach:**
- After U1 and U2, `fetch_repo_doc`/`raw_doc_url` have no callers. Remove them and confirm the app still
  imports and starts.

**Patterns to follow:**
- Keep `repo_docs.py` as the single home for the pure blob-URL builder.

**Test scenarios:**
- Test expectation: primarily deletion. Retain a test that `repo_doc_source_url` builds the correct blob
  URL from `skills_repo`/`skills_ref`.
- Regression: a repo-wide search finds no remaining reference to `raw.githubusercontent.com` or the
  removed functions in non-test code.

**Verification:**
- App starts; `grep raw.githubusercontent` over `src/` returns nothing; test suite passes.

---

## System-Wide Impact

- **Interaction graph:** `/faq` and `/skill-details` are the only affected routes; both are already
  wired via `register_*` in [app.py](lik-ui/src/lik_ui/app.py).
- **API surface parity:** `/skill-details` drops the `instructions` field — the connections page is its
  only consumer (updated in U2).
- **Unchanged invariants:** auth/login gating, page routes, and the "view on GitHub" link behavior are
  unchanged; `skills_repo`/`skills_ref` settings remain for blob URLs.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Relocated `faq.md` not included in the non-editable install → empty FAQ in prod | Add to `package-data` (U1) and cover with `test_faq_content.py` asserting discovery at the package path. |
| A stale reference to the removed fetch functions breaks import | U3 depends on U1+U2; verify with a repo-wide grep and app startup. |
| Flipping the repo private before deploy breaks the still-public build | Deploy the new image first, verify, then flip the repo private (Operational Notes). |

---

## Documentation / Operational Notes

- **Go-private sequence (post-merge):** build & deploy the new lik-ui image via
  [deploy-images.yml](.github/workflows/deploy-images.yml), verify FAQ + connections render with network
  to GitHub raw effectively unused, then flip the GitHub repo to private and re-verify both pages.
- No DB or infra changes.

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md](docs/brainstorms/2026-07-24-02-lik-ui-bundle-docs-private-repo-requirements.md)
- Related code: [repo_docs.py](lik-ui/src/lik_ui/repo_docs.py), [faq.py](lik-ui/src/lik_ui/faq.py),
  [agents.py](lik-ui/src/lik_ui/agents.py), [connections.html](lik-ui/src/lik_ui/templates/connections.html)
- Related: [deploy-images.yml](.github/workflows/deploy-images.yml)
