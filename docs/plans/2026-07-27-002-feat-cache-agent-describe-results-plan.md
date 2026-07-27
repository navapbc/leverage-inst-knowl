---
title: "feat: Cache agent describe results with a short TTL"
type: feat
status: completed
date: 2026-07-27
---

# feat: Cache agent describe results with a short TTL

## Summary

Wrap the `AgentsClient` in a `CachingAgentsClient` decorator that memoizes `describe(agent_id)`
results for a short, configurable TTL, so page loads stop issuing one Anthropic SDK `retrieve`
per configured agent. Agent definitions change rarely (only on redeploy), so a brief cache is
safe and cuts the picker's per-agent fan-out to at most one call per agent per TTL window.

---

## Problem Frame

`AnthropicAgentsClient.describe(agent_id)` issues a `beta.agents.retrieve` SDK call every time it
runs, and it runs on every load of the home picker, the connections page, and two chat paths. The
home picker loops over *every* configured agent, so its cost scales linearly with roster size —
today it's cheap with one agent, but the TODO (`lik-ui/README.md:125`) flags it as a scaling
concern as the roster grows. The returned definition (name, system prompt, model, declared
servers, skills, version) only changes on a redeploy, so the repeated fetches are almost entirely
redundant.

---

## Requirements

- R1. Repeated `describe(agent_id)` calls for the same agent within the TTL window issue at most
  one underlying SDK `retrieve`.
- R2. After the TTL expires, the next `describe` for that agent re-fetches from the SDK.
- R3. Distinct `agent_id`s are cached independently (no cross-agent bleed).
- R4. The TTL is configurable via a `LIK_UI_`-prefixed setting with a sensible short default; a
  value of `0` disables caching (always fetch), preserving today's behavior.
- R5. All four existing call sites (home, connections, chat label, chat resume) benefit without
  changing their own code.
- R6. Caching wraps only `describe`; `resolve_agent_id`, `resolve_environment_id`, and
  `describe_skill` continue to delegate straight through.

---

## Scope Boundaries

- Not caching `describe_skill` — skill-details is a per-expand user action, already flagged as a
  separate deferred concern in the README's SKILL.md TODO; fold it in later only if it becomes hot.
- No manual cache invalidation / bust endpoint — TTL expiry is the only eviction. A redeploy
  restarts the process and empties the cache anyway.
- No cross-process / shared cache (Redis, DB) — a per-process in-memory cache is sufficient; each
  app instance holding its own short-TTL copy is acceptable.
- Not changing the `describe` return shape or any call site's rendering logic.

---

## Context & Research

### Relevant Code and Patterns

- `lik-ui/src/lik_ui/agents.py` — `AgentsClient` Protocol (line 17), `AnthropicAgentsClient`
  (line 45), `build_agents_client` (line 109). The Protocol already defines the seam a wrapper
  implements.
- `lik-ui/src/lik_ui/app.py:51` / `__main__.py:36` — `agents_client` is built once and stored on
  `app.state.agents_client`; wrapping at build time propagates to all consumers.
- Call sites that benefit automatically: `app_auth.py:230` (home, loops all agents),
  `agents.py:166` (connections), `chat.py:387` and `chat.py:461` (chat).
- `lik-ui/tests/test_agents.py:20` — `FakeAgentsClient` stub with a `describe` method; ideal as the
  delegate under test for the wrapper, and easy to instrument with a call counter.
- `lik-ui/src/lik_ui/settings.py:72` — `Settings(BaseSettings)` with `env_prefix="LIK_UI_"`;
  `int`-typed fields with defaults already present (e.g. `db_port`, `http_port`), so an int TTL
  field follows the established convention.

### Institutional Learnings

- None directly applicable in `docs/solutions/` for in-process caching; the pattern is simple
  enough that local conventions (Protocol seam, `app.state` wiring) fully cover it.

---

## Key Technical Decisions

- **Wrapper (decorator) over in-method caching:** Implement `CachingAgentsClient` that holds a
  delegate `AgentsClient` plus a TTL, rather than adding cache state inside
  `AnthropicAgentsClient.describe`. Keeps the SDK client stateless/pure, matches the existing
  Protocol seam, and lets the cache be tested against `FakeAgentsClient` by counting delegated
  calls. Also means the cache is trivially disabled by not wrapping.
- **Monotonic clock for expiry:** key TTL comparisons off `time.monotonic()`, not wall-clock, so a
  system clock adjustment can't extend or prematurely expire an entry.
- **Thread-safety via a simple lock:** FastAPI runs sync route handlers in a threadpool and the
  home picker can be hit concurrently, so guard the cache dict with a `threading.Lock`. Correctness
  over cleverness — the critical section is a dict read/write, not the SDK call. (Acceptable
  alternative if it reads simpler: allow benign duplicate fetches on a race and skip the lock; the
  worst case is a couple extra `retrieve` calls. Decide during implementation, but default to the
  lock.)
- **`TTL = 0` disables caching:** gives an escape hatch and a clean way to assert pass-through
  behavior in tests.
- **Default TTL:** 60 seconds — "short" per the TODO; long enough to collapse a burst of loads,
  short enough that a redeploy's new definition surfaces within a minute even without the process
  restart that already clears the cache.

---

## Open Questions

### Resolved During Planning

- Where to cache (client vs. call site): at the client via a wrapper — one change covers all four
  call sites.
- Which methods to cache: only `describe` (R6); everything else delegates.

### Deferred to Implementation

- Exact wrapper method/attribute names and whether the lock or benign-race variant reads cleaner.
- Whether to store `(value, expires_at)` tuples or a small entry object — a mechanical choice made
  when the code is in front of you.

---

## Implementation Units

- U1. **Add `CachingAgentsClient` wrapper**

**Goal:** A decorator implementing the `AgentsClient` Protocol that memoizes `describe(agent_id)`
for a TTL and delegates every other method unchanged.

**Requirements:** R1, R2, R3, R6

**Dependencies:** None

**Files:**
- Modify: `lik-ui/src/lik_ui/agents.py`
- Test: `lik-ui/tests/test_agents.py`

**Approach:**
- New class holding a delegate `AgentsClient`, an int `ttl_seconds`, a dict cache keyed by
  `agent_id`, and a lock. `describe` returns a live cache entry if unexpired (by `time.monotonic()`),
  otherwise fetches from the delegate, stores, and returns. When `ttl_seconds == 0`, always fetch.
- `resolve_agent_id`, `resolve_environment_id`, `describe_skill` delegate directly.
- Cache the dict `describe` returns as-is; do not deep-copy — call sites treat it as read-only today
  (they only read keys). Note this assumption near the code.

**Technical design:** *(directional guidance for review, not implementation specification)*

```
class CachingAgentsClient:  # implements AgentsClient
    def __init__(delegate, ttl_seconds): store delegate, ttl, {}, Lock
    def describe(agent_id):
        if ttl == 0: return delegate.describe(agent_id)
        with lock:
            entry = cache.get(agent_id)
            if entry and entry.expires_at > monotonic(): return entry.value
        value = delegate.describe(agent_id)          # outside lock: don't hold during SDK I/O
        with lock: cache[agent_id] = (value, monotonic() + ttl)
        return value
    # resolve_agent_id / resolve_environment_id / describe_skill -> delegate.<same>(...)
```

**Patterns to follow:**
- `AgentsClient` Protocol shape in `lik-ui/src/lik_ui/agents.py:17`.
- `FakeAgentsClient` in `lik-ui/tests/test_agents.py:20` as the delegate under test.

**Test scenarios:**
- Happy path: two `describe("a")` calls within TTL → delegate's `describe` invoked once, both
  return equal data. (Instrument the fake with a call counter.)
- Edge case: TTL expiry — call `describe("a")`, advance the monotonic clock past TTL (monkeypatch
  `time.monotonic` or inject a clock), call again → delegate invoked twice. (Verifies R2.)
- Edge case: distinct ids `describe("a")` then `describe("b")` → delegate invoked once per id, no
  cross-agent bleed. (Verifies R3.)
- Edge case: `ttl_seconds=0` → every `describe` hits the delegate (pass-through). (Verifies R4
  disable path.)
- Happy path: `resolve_agent_id`, `resolve_environment_id`, `describe_skill` each delegate straight
  through and are never cached (call twice → delegate called twice). (Verifies R6.)
- Error path: delegate `describe` raising propagates and does not populate the cache (a subsequent
  call re-attempts the delegate).

**Verification:**
- New tests pass; a repeated-load scenario shows a single delegated `describe` per agent within the
  window.

---

- U2. **Wire TTL setting and wrap the client at build time**

**Goal:** Expose `LIK_UI_AGENT_DESCRIBE_TTL` and have `build_agents_client` return the caching
wrapper so all call sites benefit unchanged.

**Requirements:** R4, R5

**Dependencies:** U1

**Files:**
- Modify: `lik-ui/src/lik_ui/settings.py`
- Modify: `lik-ui/src/lik_ui/agents.py`
- Modify: `lik-ui/.env.example`
- Modify: `lik-ui/README.md` (convert the TODO on line 125 to a DONE entry, mirroring the existing
  "DONE:" sections' style)
- Test: `lik-ui/tests/test_agents.py`

**Approach:**
- Add `agent_describe_ttl: int = 60` to `Settings` with a short comment, following the existing
  int-field convention (`db_port`, `http_port`).
- In `build_agents_client`, keep the `is_stub → None` short-circuit, then wrap the
  `AnthropicAgentsClient` in `CachingAgentsClient(delegate, settings.agent_describe_ttl)` before
  returning.
- Add the `LIK_UI_AGENT_DESCRIBE_TTL` line to `.env.example` with the default and a one-line note.
- Update the README: move the line-125 block from "TODO:" to "DONE:" describing the wrapper and the
  env var (do not delete surrounding TODOs).

**Patterns to follow:**
- Settings field style at `lik-ui/src/lik_ui/settings.py:76-89`.
- `build_agents_client` structure at `lik-ui/src/lik_ui/agents.py:109`.
- Existing "DONE:" section prose style in `lik-ui/README.md` (e.g. lines 133, 171).

**Test scenarios:**
- Happy path: `build_agents_client` with a non-stub settings object returns a `CachingAgentsClient`
  whose delegate is an `AnthropicAgentsClient` and whose TTL equals `settings.agent_describe_ttl`.
  (Construct without hitting the network — mirror the `__new__`-based construction already used in
  `test_agents.py` for `AnthropicAgentsClient`, or assert on type + ttl attribute.)
- Edge case: stub settings (`is_stub`) still returns `None` (unchanged boot path).
- Edge case: default TTL is 60 when `LIK_UI_AGENT_DESCRIBE_TTL` is unset. (One assertion on the
  Settings default.)

**Verification:**
- App boots; home/connections/chat render identically; with the default TTL, a burst of home loads
  produces one `retrieve` per agent per minute rather than one per load.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Stale definition shown for up to TTL after a redeploy | Default TTL is 60s; a redeploy restarts the process and clears the cache, so the stale window in practice is near-zero. `TTL=0` disables entirely if needed. |
| Concurrent picker loads racing on the cache dict | Guard with a `threading.Lock` (default), or accept benign duplicate fetches — either way correctness holds. |
| Callers mutating the shared cached dict | Call sites are read-only today; note the assumption in code. Revisit (copy-on-return) only if a mutation is introduced. |

---

## Sources & References

- TODO: `lik-ui/README.md:125` ("TODO: cache agent `describe` results")
- Related code: `lik-ui/src/lik_ui/agents.py`, `lik-ui/src/lik_ui/settings.py`,
  `lik-ui/src/lik_ui/app_auth.py:230`, `lik-ui/src/lik_ui/chat.py:387`
