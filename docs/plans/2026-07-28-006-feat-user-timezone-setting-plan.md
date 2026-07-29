---
title: "feat: User-configurable time zone (client-side, like dark mode)"
type: feat
status: active
date: 2026-07-28
---

# feat: User-configurable time zone (client-side, like dark mode)

## Summary

Replace the two hardcoded `America/New_York` constants with a single, user-chosen time zone stored
client-side (localStorage), mirroring the dark-mode mechanism. The server stops formatting local times
and instead emits raw UTC instants; a small `tz.js` module formats every timestamp into the user's
effective zone in the browser, and a Settings-page dropdown lets the user change it. Default is the
browser-detected zone. The one remaining zone-dependent write — rescheduling a session's auto-delete —
is converted from a "keep until `<date>`" picker to a relative "keep for `<N days/weeks>`" duration, so
no zone is needed on the write path at all (it stores `now() + interval` in UTC, reusing the existing
cadence parser).

---

## Problem Frame

The display time zone is hardcoded to `America/New_York` in two places — [chat.py:34](src/lik_ui/chat.py#L34)
(`EASTERN`, drives the session auto-delete date and the date-picker) and
[app.py:38](src/lik_ui/app.py#L38) (`_EASTERN`, the next-run filter). There is no way for a user outside
Eastern Time to see times in their own zone, and the value lives in two spots that can drift. The user
asked to make it a single user setting, settable on the Settings page, using the same mechanism as the
existing dark-mode toggle.

---

## Requirements

- R1. The effective time zone is defined and resolved in exactly one place; no `America/New_York` literal
  remains in Python display/formatting code.
- R2. Users can choose their time zone on the Settings page from a short curated list.
- R3. The preference persists client-side via localStorage, matching the dark-mode pattern (no DB column,
  no server session state).
- R4. When the user has not chosen a zone, the effective zone is auto-detected from the browser.
- R5. All existing user-facing timestamps render in the effective zone: scheduled-run next-run time
  (with UTC in parentheses) and session auto-delete date (sessions list, chat page).
- R6. Rescheduling a session's auto-delete needs no time zone: the user picks a relative duration
  ("keep for N days/weeks") and the server stores `now() + interval` in UTC. This removes the last
  zone-dependent server write.

---

## Scope Boundaries

- Not adding a server-persisted (DB) time-zone column — this is deliberately client-side like dark mode.
- Not adding a full IANA zone picker — the curated list (Auto + US Eastern/Central/Mountain/Pacific + UTC)
  is the product decision. The server write path still accepts any valid IANA zone, so expanding the list
  later is a template/JS-only change.
- Not changing auto-delete cleanup semantics (still a stored UTC instant, still swept by the pruner) —
  only *how the reschedule is expressed* changes (relative duration instead of an absolute date).
- Not adding per-timestamp zone overrides — one effective zone applies to the whole UI.

---

## Context & Research

### Relevant Code and Patterns

- Dark-mode mechanism to mirror: [static/theme.js](src/lik_ui/static/theme.js) (localStorage key
  `lik-theme`, control wiring, re-render on change) and [base.html](src/lik_ui/templates/base.html)
  (script include + the `topbar` control). The tz feature mirrors this: a `lik-tz` key and a `tz.js` module.
- Server-side tz code to remove/replace: [chat.py:34-43](src/lik_ui/chat.py#L34-L43) (`EASTERN`,
  `_auto_delete_local`), [chat.py:480-483](src/lik_ui/chat.py#L480-L483) (picker date→ET end-of-day→UTC
  write, replaced by a duration in U4), [chat.py:498](src/lik_ui/chat.py#L498) (`auto_delete_local` prep),
  [app.py:36-50](src/lik_ui/app.py#L36-L50) (`_EASTERN` + `et_with_utc` filter, added earlier this session).
- Reschedule pattern to reuse for U4: [account.py:22-42](src/lik_ui/account.py#L22-L42)
  (`parse_cadence` / `format_cadence` / `CADENCE_UNITS` / `MAX_CADENCE_COUNT`) already turn a count+unit
  into a `timedelta` with guardrails — the auto-delete duration reuses the same helper and the same
  weeks/days units.
- Timestamp display sites: [settings.html:106](src/lik_ui/templates/settings.html#L106) (next run),
  [sessions.html:17](src/lik_ui/templates/sessions.html#L17) (deletes date),
  [chat.html:12](src/lik_ui/templates/chat.html#L12) (shared-session note). The reschedule control at
  [chat.html:47-54](src/lik_ui/templates/chat.html#L47-L54) is a date picker today and becomes a duration
  picker in U4; it also shows the current auto-delete date (a display site).
- Test precedent for a client-side preference exercised server-side: [tests/test_theme_toggle.py](tests/test_theme_toggle.py)
  (asserts the control/script are present in the rendered page). No JS unit-test harness exists in the repo.
- `AUTO_DELETE_WARN_WINDOW` / `delete_soon` are UTC-based comparisons — they stay server-side and are unaffected.

### Institutional Learnings

- CLAUDE.md: keep designs simple; audience may be non-technical (drove the curated-list decision).
- Two local DBs on distinct ports (5432 / 5433); the `lik-ui` suite ignores `.env` — run pytest with
  `LIK_UI_DB_PORT=5433`.
- This plan intentionally has **no** DB schema change, so no prod migration is required.

---

## Key Technical Decisions

- **Client-side, mirroring dark mode (R3).** The preference lives in `localStorage["lik-tz"]` and a
  `tz.js` module — no DB column, no server session key. Rationale: the user explicitly asked for the
  dark-mode mechanism, and it avoids a prod migration.
- **Server emits UTC, browser formats.** Because the zone now lives only in the browser, the server can no
  longer produce local strings. Templates emit machine-readable UTC in a `data-utc` attribute (via a tiny
  always-UTC `utc_iso` serialization filter) with a plain UTC string as no-JS fallback text; `tz.js`
  rewrites each element's text into the effective zone. This is the direct consequence of choosing the
  dark-mode mechanism and is the core shape of the change.
- **Effective-zone resolution in one function (R1, R4).** `tz.js` exposes one resolver: stored value, or
  if unset/`"auto"` → `Intl.DateTimeFormat().resolvedOptions().timeZone`. It is used only for *display* —
  no write path reads it — which is why the zone can live purely in the browser.
- **Reschedule by relative duration, not a date (R6).** The auto-delete reschedule is the only write that
  used to depend on a zone (interpreting a chosen calendar day as end-of-day → UTC). We remove that
  dependency entirely by changing the control from "keep until `<date>`" to "keep for `<count> <days|weeks>`":
  the server stores `now() + interval` in UTC and never touches a zone. Rationale: it eliminates the
  fragile browser wall-time→UTC conversion *and* any hardcoded server zone at once, and it reuses the app's
  existing interval model (`parse_cadence`), so the reschedule and the scheduled-run cadence share one
  mental model. Trade-off: the control's meaning shifts from an absolute date to a relative extension
  (a deliberate UX change). Alternatives (send zone as form data; browser computes via Temporal/library;
  store a date column) were considered and rejected — see the reschedule discussion in the session that
  produced this plan.
- **Curated zone list defined once (R2).** The Auto + US-zones + UTC list lives in `tz.js` and populates
  the `<select>`; the template ships an empty select that JS fills, so there is no second copy of the list.

---

## Open Questions

### Resolved During Planning

- Persistence mechanism: client-side localStorage (user chose the dark-mode mechanism).
- Default when unset: browser auto-detect (user chose).
- Selector contents: curated list — Auto, US Eastern/Central/Mountain/Pacific, UTC (user chose).
- Auto-delete reschedule write path: relative duration (Option E), not a zone-carrying date — chosen to
  avoid browser DST math and any server-side hardcoded zone (user chose).

### Deferred to Implementation

- Exact zone-abbreviation rendering (e.g. `EDT` vs `GMT-4`): use `Intl.DateTimeFormat` `timeZoneName: "short"`
  via `formatToParts`; confirm the abbreviation reads well for the curated zones during implementation.
- Whether to add an inline pre-paint bootstrap for timestamps: likely unnecessary (a brief UTC→local
  reflow is acceptable, unlike a theme flash); decide when wiring `base.html`.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation
> specification. The implementing agent should treat it as context, not code to reproduce.*

```
DISPLAY (client-side, mirrors dark mode; no server involvement):

  localStorage["lik-tz"]  ──►  tz.js: getEffectiveZone()  ──►  format every [data-utc] element
     ("auto" | IANA)            (stored, else Intl detect)        into the effective zone
          ▲                                                              ▲
          │ Settings <select> onchange                                   │ data-utc="<UTC ISO>"
     user picks zone                                       server renders via utc_iso filter
                                                           (fallback text: "<...> UTC")

WRITE — auto-delete reschedule (zone-independent):

  duration picker  ──►  POST /chat/{id}/auto-delete {count, unit}
  "keep N days/weeks"        │
                             ▼
                    parse_cadence → timedelta → store now() + interval  (UTC, no zone)
```

---

## Implementation Units

- U1. **Client-side time-zone module + global wiring**

**Goal:** Introduce the single source of truth for the effective zone and apply it to every timestamp on
every page.

**Requirements:** R1, R3, R4, R5

**Dependencies:** None

**Files:**
- Create: `src/lik_ui/static/tz.js`
- Modify: `src/lik_ui/templates/base.html`

**Approach:**
- `tz.js` mirrors `theme.js` structure: `STORAGE_KEY = "lik-tz"`; `getStored()`; `getEffectiveZone()`
  (stored concrete zone, else `Intl.DateTimeFormat().resolvedOptions().timeZone`); `setZone(value)`
  (persist + re-render). Guard localStorage access in try/catch (session-only fallback), same as theme.js.
- `applyAll()` scans `document.querySelectorAll("[data-utc]")` and sets each element's text using its
  `data-format` (`"datetime"` → `"YYYY-MM-DD HH:MM <ABBR> (HH:MM UTC)"`; `"date"` → `"YYYY-MM-DD"`). Parse
  timestamps with `new Date(iso)` (the ISO carries a UTC offset, so this is zone-safe). `tz.js` is
  display-only — it does not touch any form (the reschedule write in U4 is zone-independent).
- Format via `Intl.DateTimeFormat(undefined, {timeZone, ...})` / `formatToParts`; derive the short zone
  abbreviation from the `timeZoneName: "short"` part. Always compute the parenthetical UTC piece from the
  same instant.
- `base.html`: add `<script src="/static/tz.js" defer></script>` alongside the existing `theme.js` include
  so formatting runs on all pages.

**Patterns to follow:** [static/theme.js](src/lik_ui/static/theme.js) (module shape, localStorage guard,
current()/render() split).

**Test scenarios:**
- Test expectation: none for the JS itself — no JS test harness in the repo. Covered indirectly by U2/U3
  server-render assertions and manual verification (see Verification).

**Verification:**
- Loading any page with a `data-utc` element shows the local-zone string; with localStorage unavailable it
  still renders using the detected zone. No console errors.

---

- U2. **Emit UTC timestamps; remove server-side zone formatting**

**Goal:** Stop producing local-time strings server-side; hand raw UTC to the client and delete the
hardcoded-zone code (including the `et_with_utc` filter added earlier this session).

**Requirements:** R1, R5

**Dependencies:** U1

**Files:**
- Modify: `src/lik_ui/app.py` (remove `_EASTERN`, `_et_with_utc`, the `et_with_utc` filter registration,
  and the now-unused `datetime`/`timezone`/`ZoneInfo` imports; add a tiny `utc_iso` filter that returns
  `dt.astimezone(timezone.utc).isoformat()` so `data-utc` is unambiguously UTC regardless of the psycopg
  connection zone)
- Modify: `src/lik_ui/chat.py` (remove `_auto_delete_local`; stop setting `auto_delete_local`; pass the
  raw `auto_delete_at` through to templates. Keep `AUTO_DELETE_WARN_WINDOW` and `delete_soon`. The
  `EASTERN` constant is removed in U4, which retires its last use in the POST handler.)
- Modify: `src/lik_ui/templates/settings.html` (next-run cell → `<time data-utc="{{ r.next_run_at | utc_iso }}"
  data-format="datetime">{{ ... }} UTC</time>`)
- Modify: `src/lik_ui/templates/sessions.html` (deletes cell → date-format `<time>`, drop the literal `ET`)
- Modify: `src/lik_ui/templates/chat.html` (shared-session note → date-format `<time>`, reword
  "(end of day ET)" to a zone-neutral phrase; the reschedule form's *current auto-delete date* display
  becomes a date-format `<time>`. The reschedule control itself is replaced in U4.)
- Modify: `tests/test_settings.py`, `tests/test_chat.py` (update assertions to the new UTC/`data-utc` output)

**Approach:**
- Templates carry a plain UTC fallback in the element body so no-JS users still see a sensible value; U1
  rewrites it. Prefer `<time datetime>`/`data-utc` semantics over embedding the local string server-side.
- Keep `delete_soon` server-side — it is a pure UTC comparison and needs no zone.

**Patterns to follow:** existing Jinja filter registration in [app.py:31](src/lik_ui/app.py#L31)
(`templates.env.filters[...] = ...`).

**Test scenarios:**
- Happy path: rendered Settings page for a schedule contains a `data-utc` element with the run instant in
  UTC ISO and no `America/New_York`/`ET`-labeled server string. Covers R1, R5.
- Happy path: sessions list and chat page emit `data-utc` date elements for `auto_delete_at`; no `ET`
  literal remains.
- Edge case: a schedule with `next_run_at` returned by psycopg in a non-UTC connection zone still serializes
  to a UTC-offset ISO via `utc_iso` (assert the `+00:00`/`Z` offset).
- Regression: grep-style assertion (or template assertion) that no response body contains the old
  `strftime('%Y-%m-%d %H:%M UTC')` ET-derived phrasing tied to a hardcoded zone.

**Verification:**
- `rg "America/New_York|EASTERN|_et_with_utc|auto_delete_local" src/lik_ui/` returns nothing in Python.
- Pages render correct local times with JS on, UTC fallback with JS off.

---

- U3. **Time-zone selector on the Settings page**

**Goal:** Give the user a control to choose their zone, persisted by `tz.js`.

**Requirements:** R2, R3

**Dependencies:** U1

**Files:**
- Modify: `src/lik_ui/templates/settings.html` (add a "Time zone" section containing an empty
  `<select id="tz-select">` and a short helper line)
- Modify: `src/lik_ui/static/tz.js` (define the curated list; populate `#tz-select`; mark the stored option
  selected; on `change`, `setZone(...)` and re-run `applyAll()`)
- Modify: `tests/test_settings.py` (assert the selector and `tz.js` include are present)

**Approach:**
- Curated list defined once in `tz.js`: `Auto (detected)` → value `"auto"`, plus
  `America/New_York`, `America/Chicago`, `America/Denver`, `America/Los_Angeles`, `UTC` with friendly
  labels. JS builds the `<option>`s so there is no duplicate list in HTML.
- Selecting "Auto" stores `"auto"`; `getEffectiveZone()` then resolves via `Intl`.

**Patterns to follow:** the theme control placement/labelling in [base.html:34](src/lik_ui/templates/base.html#L34);
Settings sections in [settings.html](src/lik_ui/templates/settings.html); test shape in
[tests/test_theme_toggle.py](tests/test_theme_toggle.py).

**Test scenarios:**
- Happy path: `GET /settings` (authenticated) renders `id="tz-select"` and includes `tz.js`. Covers R2.
- Edge case: the selector renders even when the user has no vault/sessions (it is independent of that state).

**Verification:**
- On Settings, changing the dropdown immediately reformats visible timestamps and survives a page reload.

---

- U4. **Reschedule auto-delete by relative duration (zone-independent write)**

**Goal:** Replace the zone-dependent "keep until `<date>`" picker with a "keep for `<count> <days|weeks>`"
duration so the write needs no time zone, and retire the last `EASTERN` reference.

**Requirements:** R1, R6

**Dependencies:** U2 (so `EASTERN`/`_auto_delete_local` are gone and the display is already `data-utc`)

**Files:**
- Modify: `src/lik_ui/chat.py` (rewrite the `POST /chat/{session_id}/auto-delete` handler: parse a count +
  unit via the shared cadence helper, reject invalid input, store `now(UTC) + interval` via
  `set_session_auto_delete_at`; remove the `datetime.strptime` date logic and the `EASTERN` constant)
- Modify: `src/lik_ui/account.py` (optional: rename/generalize `parse_cadence` or add a thin alias so its
  reuse for auto-delete reads clearly — or import it as-is; decide during implementation without
  duplicating the units/guardrail constants)
- Modify: `src/lik_ui/templates/chat.html` (replace the `<input type="date">` with a count field + unit
  `<select>` mirroring the scheduled-run cadence picker; keep showing the current auto-delete date as a
  read-only `data-utc` `<time>`; reword the helper text — "push it out", not "pick a date")
- Modify: `tests/test_chat.py` (reschedule tests now POST count+unit and assert `now()+interval` storage)

**Approach:**
- Reuse [account.py `parse_cadence`](src/lik_ui/account.py#L22) (`CADENCE_UNITS = ("weeks","days")`,
  `MAX_CADENCE_COUNT = 52`): a valid submission is a whole count in range and a known unit → `timedelta`.
  The handler stores `datetime.now(timezone.utc) + interval`. Because the minimum interval is one day, the
  result is always in the future — preserving today's invariant that a session can be pushed out but never
  turned off, with no separate "future date" check.
- No zone anywhere in this path: the picker, the parse, and the store are all zone-free. `tz.js` is not
  involved.
- The current auto-delete date shown next to the control is display only and rendered via the U2
  `data-utc` mechanism (so it reflects the user's effective zone).

**Execution note:** Add the failing server test for the new count+unit request contract first, then rewrite
the handler.

**Patterns to follow:** the scheduled-run cadence picker markup in
[settings.html:78-83](src/lik_ui/templates/settings.html#L78-L83) and its handler
[account.py `create_scheduled_run`](src/lik_ui/account.py#L89) (count+unit → `parse_cadence` →
reject-on-invalid); owner-scoped `set_session_auto_delete_at`.

**Test scenarios:**
- Happy path: POST `count=2, unit=weeks` stores `auto_delete_at ≈ now() + 14 days` (assert within a small
  tolerance of `now()+interval`, in UTC). Covers R6.
- Happy path: POST `count=1, unit=days` stores `now() + 1 day` and remains strictly in the future.
- Edge case: `count` at the boundary (`1` and `MAX_CADENCE_COUNT`) succeeds; `0`, negative, non-integer, or
  an unknown unit is rejected with a 400 and nothing is stored.
- Integration: the POST is owner-scoped — a non-owner's POST changes nothing (mirrors the existing
  `set_session_auto_delete_at` owner check).

**Verification:**
- On a session, choosing "2 weeks" updates the displayed auto-delete date to ~14 days out (shown in the
  user's zone); no `America/New_York`/`EASTERN` reference remains in `chat.py`.

---

## System-Wide Impact

- **Interaction graph:** `base.html` now loads `tz.js` globally; every page with a `data-utc` element is
  reformatted client-side. `tz.js` touches no forms.
- **Error propagation:** the auto-delete write rejects invalid count/unit with a 400 (same shape as the
  scheduled-run create), storing nothing on bad input.
- **State lifecycle risks:** `auto_delete_at` remains a UTC instant swept by the pruner — unchanged. Only its
  *display* moves to the client zone and the *reschedule input* becomes a duration.
- **API surface parity:** all timestamp display sites (next run, sessions-list delete date, chat shared-note,
  chat current-delete date) must go through the same `data-utc` mechanism; a missed site would silently
  render UTC-labeled fallback forever (no JS formatting) — the U2 grep check guards this.
- **Integration coverage:** shared-session viewers in a different zone than the owner may see the auto-delete
  date shift by a calendar day (it is one fixed UTC instant shown in each viewer's zone). This is correct and
  expected once the zone is per-user; note it in the shared-session wording.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| No-JS users lose all local formatting | Server emits a readable UTC fallback in each element body; parity with dark mode, which is also JS-only. |
| A timestamp display site is missed | U2 verification greps for `America/New_York`/`ET`/old filters; every known site enumerated in Context. |
| Shared-session date appears to shift for far-off viewers | Documented as expected; wording made zone-neutral. |
| Reschedule UX change confuses users (duration vs date) | Mirror the familiar scheduled-run cadence picker exactly (same units/labels); helper text explains "push out by N days/weeks". |
| DST wall-time math done wrong | Eliminated by design — Option E does no wall-time→UTC conversion anywhere (`now() + interval` only). |

---

## Documentation / Operational Notes

- Two user-facing changes may warrant a FAQ touch-up in [faq.md](src/lik_ui/faq.md): the new time-zone
  setting and the reschedule control changing from a date to a duration. Confirm with the user at PR time
  (per the project's FAQ rule).
- No prod DB migration (no schema change).

---

## Sources & References

- Related code: [static/theme.js](src/lik_ui/static/theme.js), [chat.py](src/lik_ui/chat.py),
  [app.py](src/lik_ui/app.py), [settings.html](src/lik_ui/templates/settings.html),
  [sessions.html](src/lik_ui/templates/sessions.html), [chat.html](src/lik_ui/templates/chat.html)
- Test precedent: [tests/test_theme_toggle.py](tests/test_theme_toggle.py)
