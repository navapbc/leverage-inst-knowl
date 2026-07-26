---
title: "feat: Add dark mode toggle to the top navbar"
type: feat
status: active
date: 2026-07-25
---

# feat: Add dark mode toggle to the top navbar

## Summary

Add a light/dark theme toggle to the lik-ui top navbar (right side, before the email address). The
toggle is the small, visible part; the real work is making dark mode actually look right. The current
CSS defines only 5 `:root` variables but hardcodes ~30 other colors (topbar, cards, per-page body
backgrounds, chat-bubble tints, notices, errors). This plan migrates those hardcoded colors to
theme-aware variables and adds a full dark override, then wires a persisted, flash-free toggle.

---

## Problem Frame

lik-ui is a server-rendered app (Jinja templates via `base.html`) with a single light theme. Users have
no way to switch to a dark appearance. A toggle that only flipped the existing 5 variables would leave
the blue topbar, white cards, tinted per-page backgrounds, and chat bubbles in their light colors —
producing a visibly broken dark mode. Delivering a working dark mode requires the color layer to be
theme-driven first.

---

## Requirements

- R1. A theme toggle control appears in the top navbar, on the right, immediately before the email address.
- R2. Toggling switches the entire UI between a light and a dark theme across all pages.
- R3. The chosen theme persists across page loads and navigation (server-rendered, so full page reloads).
- R4. No flash of the wrong theme on page load (the correct theme is applied before first paint).
- R5. On a first visit with no stored preference, the theme follows the OS `prefers-color-scheme`.
- R6. Light theme appearance is unchanged from today (the variable migration is behavior-preserving).
- R7. The dark theme covers every surface currently colored: topbar, per-page body backgrounds, cards,
  chat-role bubbles, notices, error surfaces, borders, muted text, and links.

---

## Scope Boundaries

- Not adding a third "system/auto" selectable mode — OS preference is only the first-visit default (R5),
  after which the toggle sets an explicit light/dark choice.
- Not restyling or relaying out any component beyond color/theme changes.
- Not adding a backend/user-profile setting for theme — persistence is client-side.
- Not introducing a CSS framework, build step, or preprocessor; the app ships a single static `app.css`.

---

## Context & Research

### Relevant Code and Patterns

- `lik-ui/src/lik_ui/static/app.css` — single stylesheet. Already uses `:root { --fg; --muted; --accent;
  --bg; --line }` (line 2) but hardcodes many colors: topbar `#95b6ed` (line 18); per-page body
  backgrounds `#b6caeb`/`#daf2ee`/`#e7dec2` (lines 10-13); card/`#fff` surfaces throughout; chat bubble
  tints (lines 81-87); notice `#fffaf2` (line 39); error `#c05621`/`#fff5ef` (lines 87, 137-141).
- `lik-ui/src/lik_ui/templates/base.html` — the shared layout. Topbar markup lives here: `.topbar-account`
  wraps `.topbar-email` + Sign out (lines 20-23). Has a `{% block head %}` (line 9) and `<html lang="en">`
  root (line 2). The topbar only renders when `user` is set (line 12).
- `lik-ui/src/lik_ui/static/chat.js` — precedent for a separate static JS file loaded by a template;
  inline `<script>` blocks already appear in `faq.html`, `connections.html`, `chat.html`.

### Key Technical Decisions

- **Theme is expressed as `data-theme="light|dark"` on the `<html>` element.** CSS selects dark via
  `:root[data-theme="dark"] { ... }` overriding the variable values. This keeps all theming in one
  place and requires no per-component class changes.
- **Persistence via `localStorage` (key `lik-theme`), not a cookie.** No backend change needed; the app
  is otherwise client-agnostic. Cookie-based SSR theming was considered but rejected as heavier (request
  plumbing) for no user-visible gain here.
- **No-flash bootstrap: a tiny synchronous inline script in `<head>`** reads `localStorage`/`prefers-color-scheme`
  and sets `data-theme` on `<html>` before the stylesheet paints. An inline blocking script is the only
  way to avoid the flash; a deferred/external script would paint the wrong theme first. This is the one
  place an inline script is justified.
- **Toggle logic in a static `theme.js`**, mirroring `chat.js`, rather than more inline script — keeps the
  interactive handler cacheable and testable.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation
> specification. The implementing agent should treat it as context, not code to reproduce.*

```
<html data-theme="dark">              ← set by inline <head> bootstrap before paint
  :root { --fg; --bg; --topbar; --card; --body-agents; ... }        (light values)
  :root[data-theme="dark"] { --fg; --bg; --topbar; --card; ... }    (dark overrides)

  bootstrap (inline, blocking):  stored = localStorage['lik-theme']
                                 theme  = stored ?? (matchMedia(prefers-color-scheme:dark) ? 'dark' : 'light')
                                 html.dataset.theme = theme

  toggle button (topbar, before email):  onclick → flip theme,
                                          write localStorage['lik-theme'],
                                          update html.dataset.theme + button icon/label
```

Color migration shape: every literal color currently in `app.css` either (a) already maps to an existing
variable and is left as-is, or (b) is promoted to a new semantic variable (e.g. `--topbar`, `--card`,
`--body-agents`, `--bubble-user`, `--notice-bg`) defined in `:root` with its current value, then given a
dark counterpart under `:root[data-theme="dark"]`.

---

## Implementation Units

- U1. **Migrate hardcoded colors to theme variables + add dark overrides**

**Goal:** Make the entire stylesheet theme-driven and add a complete dark palette, with light appearance
unchanged.

**Requirements:** R2, R6, R7

**Dependencies:** None

**Files:**
- Modify: `lik-ui/src/lik_ui/static/app.css`

**Approach:**
- Inventory every literal color in `app.css`. For each, either reuse an existing `:root` variable or add a
  new semantic variable (suggested groups: `--topbar`, `--card`, `--card-alt`, per-page body backgrounds
  `--body-agents`/`--body-sessions`/`--body-settings`/`--body-connections`, chat bubbles
  `--bubble-user`/`--bubble-tool`/`--bubble-mcp`, `--notice-bg`/`--notice-line`, `--error-fg`/`--error-bg`,
  status `--status-ok`/`--status-warn`). Keep the light values identical to today so R6 holds.
- Add a `:root[data-theme="dark"]` block overriding every variable with a dark value. Dark palette should
  keep the existing hue relationships (blue-ish topbar/agents, teal-ish sessions, amber-ish settings/notice)
  but at low lightness with legible foreground contrast (target WCAG AA for body text on background).
- Ensure borders (`--line`) and muted text (`--muted`) get dark values so cards/inputs remain visible.

**Patterns to follow:**
- Existing `:root` variable declaration (`app.css:2`) and `var(--x)` usage throughout.

**Test scenarios:**
- Happy path: With `<html>` default (no `data-theme` or `data-theme="light"`), computed colors of body,
  topbar, a card, and each per-page background match the pre-change values (visual/computed-style check).
- Happy path: With `data-theme="dark"` on `<html>`, body background is dark and body text is light; topbar,
  cards, chat bubbles (user/tool/mcp), notice, and error surfaces all render dark variants.
- Edge case: Each per-page body class (`agents-page`, `sessions-page`, `settings-page`, `connections-page`)
  resolves to a dark background under `data-theme="dark"` and its original tint under light.
- Edge case: Body-text-on-background contrast in dark meets WCAG AA (≥ 4.5:1) — spot-check via a contrast check.

**Verification:**
- Toggling `data-theme` on `<html>` in devtools flips every visible surface with no element left in a
  light color; light mode is pixel-consistent with `main` before the change.

---

- U2. **No-flash theme bootstrap in the shared head**

**Goal:** Apply the correct theme to `<html>` before first paint on every page.

**Requirements:** R3, R4, R5

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/templates/base.html`

**Approach:**
- Add a small synchronous inline `<script>` in `<head>` (before the `app.css` link, or immediately after —
  it only sets an attribute) that reads `localStorage['lik-theme']`; if absent, falls back to
  `window.matchMedia('(prefers-color-scheme: dark)')`; then sets `document.documentElement.dataset.theme`.
- Must run for all pages including `login.html` (which has no `user`/topbar) so the login screen also
  respects the theme — place it in `base.html` head, not gated on `user`.

**Execution note:** Keep this script tiny and dependency-free; it runs before anything else loads.

**Patterns to follow:**
- Inline `<script>` usage already present in `faq.html`/`connections.html`; `{% block head %}` in
  `base.html:9`.

**Test scenarios:**
- Happy path: With `localStorage['lik-theme']='dark'`, loading any page sets `<html data-theme="dark">` and
  the page renders dark with no observable light flash.
- Edge case: No stored key + OS set to dark → resolves to dark; OS set to light → resolves to light.
- Edge case: Stored value takes precedence over OS preference.
- Error path: Malformed/unexpected stored value falls back to light (or OS) rather than throwing.

**Verification:**
- Hard-reloading a page with a dark preference shows dark immediately (no white flash), including on the
  login page.

---

- U3. **Theme toggle control in the topbar**

**Goal:** Add the user-facing toggle in the navbar, before the email, that flips and persists the theme.

**Requirements:** R1, R2, R3

**Dependencies:** U1, U2

**Files:**
- Modify: `lik-ui/src/lik_ui/templates/base.html`
- Create: `lik-ui/src/lik_ui/static/theme.js`

**Approach:**
- Add a `<button>` toggle inside `.topbar-account`, positioned before `.topbar-email` (base.html:20-23).
  Use a `<button>` (not a link) with an accessible label (e.g. `aria-label`) and an icon that reflects
  current state (sun in dark mode / moon in light mode). Minimal styling reusing existing button/topbar
  conventions; add a small `.theme-toggle` rule in `app.css` if needed (icon-only, transparent).
- Add `theme.js` (loaded via `<script src>` at end of body or through `{% block head %}` deferred) with a
  click handler: read current `data-theme`, flip it, write `localStorage['lik-theme']`, update the
  attribute and the button's icon/label. No full reload required for the flip.
- Reuse the same storage key (`lik-theme`) and attribute convention as U2 so bootstrap and toggle agree.

**Patterns to follow:**
- `.topbar-account`/`.topbar-email` markup (base.html:20-23); separate static JS precedent `chat.js`.

**Test scenarios:**
- Happy path: Clicking the toggle switches the page from light to dark (and back) live, and updates the
  button icon/label each time.
- Happy path: After toggling to dark and reloading, the page stays dark (persistence via U2 bootstrap).
- Edge case: Toggle DOM position is before `.topbar-email` within `.topbar-account`.
- Integration: The value the toggle writes to `localStorage` is the exact key the U2 bootstrap reads, so a
  toggle followed by navigation to another page preserves the theme.
- Accessibility: The control is keyboard-focusable and has a discernible accessible name.

**Verification:**
- With the app running, the toggle appears before the email, flips the whole UI on click, and the choice
  survives navigation and reload.

---

## System-Wide Impact

- **Interaction graph:** `base.html` renders on every page, so the head bootstrap (U2) and toggle (U3)
  reach all views. The toggle button only renders in the topbar (authenticated pages); the bootstrap runs
  everywhere including `login.html`.
- **State lifecycle risks:** Bootstrap (U2) and toggle (U3) must share one storage key + attribute name;
  a mismatch causes the toggle to appear to "not persist." Called out as an integration test in U3.
- **Unchanged invariants:** Light-theme appearance must be byte-for-byte equivalent after U1 (R6); the
  variable migration changes indirection, not values. No template structure changes beyond the added
  toggle button and head script.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Missed hardcoded color leaves a light patch in dark mode | U1 requires a full color inventory of `app.css`; U1 verification checks every surface flips. |
| Flash of wrong theme on load | U2 uses a synchronous inline `<head>` script that sets the attribute before paint. |
| Toggle and bootstrap disagree on key/attribute → no persistence | Shared `lik-theme` key + `data-theme` convention fixed in decisions; U3 has an integration test for it. |
| Poor dark contrast/legibility | U1 targets WCAG AA for body text and spot-checks contrast. |

---

## Sources & References

- Navbar markup: `lik-ui/src/lik_ui/templates/base.html`
- Stylesheet: `lik-ui/src/lik_ui/static/app.css`
- Static JS precedent: `lik-ui/src/lik_ui/static/chat.js`
