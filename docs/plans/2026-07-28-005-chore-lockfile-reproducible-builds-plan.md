---
title: "chore: Reproducible container builds via a committed dependency lockfile"
type: refactor
status: active
date: 2026-07-28
---

# Reproducible container builds via a committed dependency lockfile

## Summary

Both service images build their dependency set from `uv.lock` instead of resolving `>=` constraints
live at `docker build` time. Each Dockerfile exports the committed lock to a pinned
`requirements.txt` and `pip install`s that exact set; a pre-push build-and-boot smoke gate in the
deploy workflow then proves the freshly built image imports and serves its health endpoint before
it is ever pushed to Lightsail. The lockfiles already exist and are committed — the gap is that the
builds ignore them.

---

## Problem Frame

Both service images (`lik-mcp`, `lik-ui`) install dependencies fresh and unpinned at `docker build`
time (`pip install .` over `>=`-only constraints — see [lik-mcp/Dockerfile](lik-mcp/Dockerfile#L4-L6)
and [lik-ui/Dockerfile](lik-ui/Dockerfile#L5-L8)). Each build resolves whatever is "latest" that
day, so an image is not reproducible and a dependency's major release can silently break a deploy.

This already caused a prod incident: a lik-mcp rebuild resolved `mcp 2.0.0`, which removed
`mcp.server.fastmcp` (imported at startup). The container crashed on import, failed the Lightsail
`/mcp` health check, and the deploy rolled back. It was hotfixed by capping `mcp[cli]>=1.2.0,<2`
(PR #55) — but every other dependency (`psycopg`, `pydantic`, `pydantic-settings`, `starlette`,
`uvicorn`, and `anthropic`/`fastapi`/`httpx`/`pyjwt` in lik-ui) is still unbounded and can recur.

Two facts discovered while planning sharpen the scope:

1. **The lockfiles already exist and are committed** (`lik-mcp/uv.lock`, `lik-ui/uv.lock`,
   `scripts/uv.lock`) — the repo adopted `uv` for tooling. The Dockerfiles simply never reference
   them. The fix is to make the build consume the lock, not to introduce locking from scratch.
2. **There is no CI that runs tests or boots the image on a PR.** The only safety net today is the
   Lightsail post-deploy health check plus automatic rollback (which is exactly what caught the mcp
   2.0 crash). So "green in CI implies boots in prod" has no CI behind it yet — the smoke gate this
   plan adds is the first automated boot check, and it runs inside the existing deploy workflow.

---

## Requirements

- R1. Both service images install the **exact dependency versions recorded in `uv.lock`**, not a
  live re-resolution of `>=` constraints.
- R2. A **stale lock** (lock out of sync with `pyproject.toml`) fails the build loudly rather than
  silently resolving something else.
- R3. A freshly built image that **fails to import or serve its health endpoint** fails the deploy
  workflow **before** the image is pushed to Lightsail — a broken build never consumes a prod
  deploy cycle.
- R4. Bumping a dependency is a **reviewable, intentional change** (a committed lock diff), not a
  side effect of the build date.
- R5. The change applies to **both** `lik-mcp` and `lik-ui`, and the local `docker compose` build
  path keeps working.

---

## Scope Boundaries

- Not adding a general PR test/CI workflow (running `pytest` on PRs). The smoke gate proves
  boot-ability, not correctness. Surfaced as an open question below, but out of this plan's scope.
- Not migrating `mcp` to the 2.x API — the `mcp[cli]>=1.2.0,<2` cap stays until that migration is
  done separately. A lockfile does not make the cap redundant (see Key Technical Decisions).
- Not pinning the base image digest (`python:3.12-slim` / `python:3.14-slim`). Tracked as an open
  question; deps are the demonstrated failure mode, base image is not.
- Not switching the container runtime to `uv run`/`uv sync` — `uv` is used only at build time to
  export a pinned `requirements.txt`; the runtime stays plain `python -m ...` (see Key Technical
  Decisions).

### Deferred to Follow-Up Work

- **`scripts/` reproducibility** (`scripts/uv.lock`): `deploy-skills.yml` / `deploy-agents.yml` run
  `uv run python ...`, which respects the lock but does not `--frozen`-guard it. Lower blast radius
  (a CI-only tool, not a long-lived prod container). Could add `--frozen` in a follow-up.
- **Scheduled dependency updates** (Dependabot / Renovate / scheduled `uv lock --upgrade`). Decided
  against for now — see Key Technical Decisions; updates are on-demand.

---

## Context & Research

### Relevant Code and Patterns

- [lik-mcp/Dockerfile](lik-mcp/Dockerfile) — `FROM python:3.12-slim`, `COPY pyproject.toml`,
  `RUN pip install --no-cache-dir .`. Does not copy or reference `uv.lock`.
- [lik-ui/Dockerfile](lik-ui/Dockerfile) — `FROM python:3.14-slim`, same `pip install .` pattern.
  Note the extra `[tool.setuptools.package-data]` in [lik-ui/pyproject.toml](lik-ui/pyproject.toml#L35-L36)
  that ships templates/static/`agents.toml`/`faq.md` — the project install (`pip install --no-deps .`)
  must still pick these up.
- [.github/workflows/deploy-images.yml](.github/workflows/deploy-images.yml#L69-L71) — the `push`
  job's "Build image" step (`docker build -t <name>:<sha> ./<name>`) is where the smoke gate slots
  in, immediately after the build and before "Push to Lightsail registry".
- [lik-mcp/docker-compose.yml](lik-mcp/docker-compose.yml) / [lik-ui/docker-compose.yml](lik-ui/docker-compose.yml)
  — both wire a health-gated Postgres sidecar and the app env (`LIK_ENV=local` etc.). This is the
  known-good boot recipe the smoke gate can mirror.
- Health endpoints: lik-ui exposes an unauthenticated [`/healthz`](lik-ui/src/lik_ui/app.py#L79-L81)
  returning `{"status":"ok"}` with no DB access; lik-mcp has only `/mcp`, which returns 401 under
  prod auth (Lightsail treats `200-499` as alive — see [infra/lik_mcp.tf](infra/lik_mcp.tf#L69-L74)).
- Startup DB coupling: both apps construct a DB pool at process startup
  ([lik-ui __main__](lik-ui/src/lik_ui/__main__.py#L24), [lik-mcp db.py](lik-mcp/src/lik_mcp/db.py#L13))
  with `open=True`. Whether the process stays up without a reachable DB is an execution-time unknown
  (see Open Questions) that shapes how U3's boot check provisions (or omits) a throwaway Postgres.

### Institutional Learnings

- No `docs/solutions/` entry covers Docker/lockfile builds. The primary prior art is the incident
  itself (PR #55) and the `mcp<2` cap rationale documented inline in
  [lik-mcp/pyproject.toml](lik-mcp/pyproject.toml#L7-L11).

### External References

- `uv export` produces a pip-compatible pinned `requirements.txt` from `uv.lock`; `--frozen` makes
  it fail if the lock is out of date with `pyproject.toml` (the R2 guard). `uv` ships a distroless
  image (`ghcr.io/astral-sh/uv`) whose `/uv` binary can be `COPY --from`'d into any base image, so
  the runtime base (`python:3.x-slim`) is unchanged.

---

## Key Technical Decisions

- **Export the lock to `requirements.txt` and `pip install` it, rather than `uv sync` the runtime.**
  Chosen for the smallest faithful diff: the container keeps plain `python -m <pkg>` (no `uv run`
  wrapper, no venv path changes), and only the dependency-install line changes. `uv` is used at
  build time only, pulled in via `COPY --from=ghcr.io/astral-sh/uv`. Trade-off: two install steps
  (deps from `requirements.txt`, then the project itself with `--no-deps`) instead of one `uv sync`.
- **Keep the `mcp[cli]>=1.2.0,<2` cap even with a lockfile.** The lock pins today's resolved `mcp`,
  but the cap is a belt-and-suspenders guard: it keeps a future `uv lock --upgrade` from silently
  pulling 2.x before the API migration is done. Remove only when the code migrates to the 2.x API.
- **Pre-push build-and-boot smoke gate** (not post-deploy-only). The incident proved the post-deploy
  health check + rollback works, but a broken image still burns a full deploy/rollback cycle and
  depends on the health probe being correct. Failing in CI before the push is cheaper and louder.
- **On-demand lock updates**, documented, not automated. Bump with `uv lock --upgrade` (all) or
  `uv lock --upgrade-package <name>` (one), then commit the lock diff. Keeps the architecture
  simple; scheduled automation is deferred (see Scope Boundaries) to avoid a moving part and PR
  noise on a two-service repo.

---

## Open Questions

### Resolved During Planning

- **Do lockfiles already exist?** Yes — all three packages have a committed `uv.lock`. Work is to
  consume them at build time, not create them.
- **Where does the smoke gate go?** In `deploy-images.yml`'s `push` job, between "Build image" and
  "Push to Lightsail registry", per the resolved decision.
- **Does the runtime need `uv`?** No — `uv` is build-time only; runtime stays `python -m`.

### Deferred to Implementation

- **Does the container stay up and answer its health endpoint without a reachable DB?** Both apps
  open a DB pool at startup (`open=True`, `timeout=5`). If the process stays up (psycopg opens the
  pool lazily/in background), the smoke gate can boot the image standalone and hit the health
  endpoint with no DB. If it exits, the gate must provision a throwaway Postgres (mirroring the
  compose sidecar) on a shared Docker network. U3 must determine this empirically at implementation
  time and pick the simpler path that reliably reaches a healthy response.
- **Exact `uv export` flags** (e.g. `--no-emit-project`, `--no-dev`, extras handling) — settle
  against the real lock output so the exported `requirements.txt` excludes the project itself and
  dev deps but includes all runtime deps.

---

## Implementation Units

- U1. **lik-mcp: build from the lockfile**

**Goal:** The `lik-mcp` image installs the exact dependency set from `lik-mcp/uv.lock`, and a stale
lock fails the build.

**Requirements:** R1, R2, R4, R5

**Dependencies:** None

**Files:**
- Modify: [lik-mcp/Dockerfile](lik-mcp/Dockerfile)

**Approach:**
- `COPY --from=ghcr.io/astral-sh/uv:<pinned-tag> /uv /bin/uv` to get the `uv` binary without
  changing the `python:3.12-slim` runtime base.
- `COPY pyproject.toml uv.lock ./`, then `RUN uv export --frozen --no-dev --no-emit-project -o
  requirements.txt && pip install --no-cache-dir -r requirements.txt`. `--frozen` is the R2 guard.
- `COPY src ./src`, then `RUN pip install --no-cache-dir --no-deps .` so the project is installed
  without re-resolving deps (they are already pinned-installed).
- Keep the existing `ENV` lines and `CMD ["python", "-m", "lik_mcp"]` unchanged.
- Order layers so the `requirements.txt` install precedes `COPY src` — the dependency layer caches
  across source-only changes.

**Patterns to follow:**
- Existing `ENV`/`CMD`/`EXPOSE` block in [lik-mcp/Dockerfile](lik-mcp/Dockerfile#L8-L21) — preserve verbatim.

**Test scenarios:**
- Happy path: `docker build ./lik-mcp` succeeds and the resulting image's installed `mcp` version
  matches the pin in `lik-mcp/uv.lock` (verify with `pip show mcp` / `pip freeze` in the image).
- Edge case: `docker compose -f lik-mcp/docker-compose.yml build` still succeeds (compose uses
  `build: .`, the same Dockerfile).
- Error path: with `pyproject.toml` edited but `uv.lock` not re-locked, `uv export --frozen` fails
  the build with a clear "lock is out of date" error (proves R2).
- Integration: `python -m lik_mcp` starts inside the built image (import succeeds) — covered end to
  end by U3's boot gate.

**Verification:**
- Built image contains exactly the locked versions; a stale lock aborts the build.

---

- U2. **lik-ui: build from the lockfile**

**Goal:** Same as U1 for the `lik-ui` image, preserving the packaged non-Python assets.

**Requirements:** R1, R2, R4, R5

**Dependencies:** None (mirrors U1; can land in the same PR)

**Files:**
- Modify: [lik-ui/Dockerfile](lik-ui/Dockerfile)

**Approach:**
- Same export-then-pip pattern as U1, on the `python:3.14-slim` base.
- Confirm the final `pip install --no-cache-dir --no-deps .` still ships templates, static assets,
  `agents.toml`, and `faq.md` via `[tool.setuptools.package-data]` — a non-editable install must
  include them or the app starts with an empty roster and no FAQ.
- Keep `ENV`/`CMD ["python", "-m", "lik_ui"]`/`EXPOSE 8001` unchanged.

**Patterns to follow:**
- U1's Dockerfile shape (keep the two files structurally parallel).
- [lik-ui/pyproject.toml](lik-ui/pyproject.toml#L35-L36) `package-data` — the asset-shipping contract.

**Test scenarios:**
- Happy path: `docker build ./lik-ui` succeeds; installed `anthropic`/`fastapi`/`uvicorn` versions
  match `lik-ui/uv.lock`.
- Edge case: the built image contains `templates/*.html`, `static/*`, `agents.toml`, and `faq.md`
  under the installed `lik_ui` package (regression guard for the `--no-deps .` install).
- Error path: stale-lock build failure, as in U1.
- Integration: `/healthz` returns `{"status":"ok"}` from the built image — covered by U3.

**Verification:**
- Built image contains the locked versions and all packaged assets; boots to a served `/healthz`.

---

- U3. **Pre-push build-and-boot smoke gate in the deploy workflow**

**Goal:** A freshly built image that fails to import or serve its health endpoint fails the deploy
workflow before it is pushed to Lightsail.

**Requirements:** R3

**Dependencies:** U1, U2 (the gate exercises the lockfile-built images)

**Files:**
- Modify: [.github/workflows/deploy-images.yml](.github/workflows/deploy-images.yml)

**Approach:**
- Insert a "Smoke boot" step in the `push` job's matrix, gated by the same
  `steps.gate.outputs.skip != 'true'` condition, positioned after "Build image" and before "Push to
  Lightsail registry" so a failure aborts before any push/apply.
- Run the just-built `<name>:<sha>` image and poll its health endpoint until healthy or a timeout:
  - lik-ui → `GET /healthz`, expect `200`.
  - lik-mcp → `GET /mcp`, accept any `200-499` (matches the Lightsail success range; a `401` proves
    the app is up and routing under prod auth).
- Provision the DB per the deferred question above: prefer a standalone boot with no DB if the
  process stays up; otherwise start a throwaway `postgres` container on a shared Docker network with
  the compose env (`LIK_ENV=local`/`LIK_UI_ENV=local`, `LIK_*_DB_HOST`, etc.) mirroring
  [docker-compose.yml](lik-mcp/docker-compose.yml). Tear down containers in a final always-run step.
- On failure, dump `docker logs` for the app container to the step log (so an import crash like the
  mcp 2.0 incident is immediately legible) and exit non-zero.

**Execution note:** Validate the boot recipe locally against the real built images before wiring the
workflow — the DB-coupling question (does the health endpoint respond without a DB?) must be settled
empirically, not assumed.

**Patterns to follow:**
- The matrix/skip-gate structure and step conditionals already in
  [deploy-images.yml](.github/workflows/deploy-images.yml#L44-L71).

**Test scenarios:**
- Happy path: a good build boots and the health poll returns success within the timeout → the
  workflow proceeds to push.
- Error path (the incident): an image whose deps break import (simulate by building against a lock
  with a known-bad pin) never becomes healthy → the poll times out → the step exits non-zero, the
  logs show the ImportError, and no push/apply runs.
- Edge case: the health poll retries across the container's startup window (don't fail on the first
  not-yet-ready probe); enforce a bounded overall timeout so a hung boot fails rather than hangs.
- Edge case: when only one service is selected (`inputs.service != both`), the smoke step is skipped
  for the unselected matrix leg exactly like the surrounding steps.
- Integration: teardown runs even when the boot fails (no leaked containers/networks between runs).

**Verification:**
- A broken image fails the workflow in the `push` job with legible logs and is never pushed; a good
  image passes through unchanged.

---

- U4. **Commit the in-flight lock sync and document the update workflow**

**Goal:** The repo's committed state is internally consistent (lock matches the capped
`pyproject.toml`) and the on-demand update procedure is written down.

**Requirements:** R2, R4

**Dependencies:** None

**Files:**
- Modify: `lik-mcp/uv.lock` (commit the working-tree change syncing the `mcp[cli]>=1.2.0,<2`
  specifier into the lock metadata)
- Modify/Create: a short "Dependencies & reproducible builds" note — extend the existing
  [lik-mcp README](lik-mcp/README.md) / [lik-ui README](lik-ui/README.md) if present, else add a
  brief section where contributors will find it.

**Approach:**
- Commit the already-present `lik-mcp/uv.lock` diff so `uv export --frozen` (U1) does not fail on a
  lock/pyproject mismatch at build time.
- Document: builds install from `uv.lock`; to change a dependency, run `uv lock --upgrade` (all) or
  `uv lock --upgrade-package <name>` (one), then commit the lock diff and let the deploy smoke gate
  boot-check it. Note that the `mcp<2` cap is intentional and must stay until the 2.x migration.

**Test scenarios:**
- Test expectation: none — this is a lock-sync commit plus documentation, with no behavioral change.
  Correctness is proven transitively: U1's `uv export --frozen` build succeeds only if the committed
  lock and `pyproject.toml` agree.

**Verification:**
- `uv export --frozen` in `lik-mcp/` succeeds against the committed tree; the update procedure is
  documented where contributors will see it.

---

## System-Wide Impact

- **Interaction graph:** The `apply` job in `deploy-images.yml` is unaffected — the new gate lives in
  the upstream `push` job, so `apply` still only runs after a successful push. No Terraform/infra
  change.
- **Error propagation:** A dependency-break now surfaces as a red `push`-job check with an ImportError
  in the logs, instead of a post-deploy Lightsail rollback. The rollback remains as a second line of
  defense for anything the smoke gate does not exercise (e.g. real-DB-dependent startup).
- **State lifecycle risks:** The smoke gate must tear down its throwaway container(s)/network on every
  path (success and failure) to avoid leaking state or port conflicts between matrix legs / runs.
- **API surface parity:** Both Dockerfiles change in lockstep (U1/U2) and stay structurally parallel;
  the local `docker compose` build path uses the same Dockerfiles and is covered by U1/U2 tests.
- **Unchanged invariants:** Runtime entrypoints (`CMD python -m ...`), exposed ports, `ENV` defaults,
  base image tags, the `mcp<2` cap, and the `apply`-job auto-apply gate are all unchanged.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Smoke gate is flaky because the app needs a DB to reach a healthy response | Settle the DB-coupling question empirically in U3; provision a throwaway Postgres mirroring compose if standalone boot is not reliably healthy; use bounded retries with a clear timeout. |
| `uv export` flags produce a `requirements.txt` that drops runtime deps or includes the project itself | Verify the exported file against the real lock in U1 before finalizing; the U3 boot gate catches a missing runtime dep as an ImportError. |
| Non-editable `lik-ui` install stops shipping templates/`agents.toml`/`faq.md` | Explicit U2 test asserts packaged assets exist in the built image; `/healthz`→app boot in U3 exercises the real package. |
| Committed lock drifts from `pyproject.toml` again in future | `uv export --frozen` fails the build on any drift (R2); documented `uv lock --upgrade` workflow keeps the lock the source of truth. |
| Pulling `uv` from `ghcr.io/astral-sh/uv:latest` reintroduces non-reproducibility | Pin the `uv` image to a specific tag (not `latest`) in both Dockerfiles. |

---

## Documentation / Operational Notes

- U4 documents the on-demand `uv lock --upgrade` update procedure and the standing `mcp<2` cap.
- No prod DB schema change and no Terraform change — this is a build/CI-only change.
- Operational win: an intentional dependency bump is now a reviewable lock diff whose boot is
  smoke-tested in CI before it can reach prod.

---

## Sources & References

- Placeholder this plan replaces (same path): this file, prior `docs(plan)` commit `23435ec`.
- Incident + hotfix: PR #55 (`fix(lik-mcp): cap mcp below 2.0`), rationale inlined in
  [lik-mcp/pyproject.toml](lik-mcp/pyproject.toml#L7-L11).
- Triggering deploy: Actions run 30402800183 (failed twice on the mcp 2.0 crash).
- Build/CI surfaces: [lik-mcp/Dockerfile](lik-mcp/Dockerfile), [lik-ui/Dockerfile](lik-ui/Dockerfile),
  [.github/workflows/deploy-images.yml](.github/workflows/deploy-images.yml).
