# Reproducible container builds via a dependency lockfile

**Status:** placeholder — not yet planned in detail.

## Problem

Both service images (`lik-mcp`, `lik-ui`) install dependencies **fresh and unpinned** at
`docker build` time (`pip install .` over `>=`-only constraints). Each build resolves whatever is
"latest" that day, so an image is not reproducible and a dependency's major release can silently
break a deploy.

This already caused a prod incident: a lik-mcp rebuild resolved `mcp 2.0.0`, which removed
`mcp.server.fastmcp` (imported at startup). The container crashed on import, failed the Lightsail
`/mcp` health check, and the deploy rolled back. Hotfixed by capping `mcp[cli]>=1.2.0,<2`
(PR #55) — but every other dep (`psycopg`, `pydantic`, `pydantic-settings`, `starlette`,
`uvicorn`, `anthropic` in lik-ui, …) is still unbounded and can recur.

## Goal

Deploys build the **same dependency set that was tested**, so "green in CI" implies "boots in
prod", and an intentional dependency bump is a reviewable change — not a silent side effect of
the build date.

## Direction (to be detailed)

- Add a lockfile (`uv.lock`) per service, committed to the repo.
- Have the Docker build install **from the lockfile** (frozen/synced), not resolve `>=` live.
- Decide the update cadence/mechanism (e.g. `uv lock --upgrade` on demand, or scheduled with a
  build-and-boot smoke check before merge).
- Apply to **both** `lik-mcp` and `lik-ui`.
- Consider a minimal deploy-time guard: a post-deploy boot/health smoke check that fails the
  workflow loudly (the `/mcp` and lik-ui health probes already exist — make a failed rollout
  surface as a red check, which it did here, but confirm alerting).

## Out of scope / open questions

- Whether to also pin the base image digest (`python:3.12-slim`).
- Whether to keep the belt-and-suspenders `mcp < 2` cap once a lockfile exists (yes, until the
  2.x API migration is done).

## References

- Incident + hotfix: PR #55 (`fix(lik-mcp): cap mcp below 2.0`).
- Triggering deploy: Actions run 30402800183 (failed twice on the mcp 2.0 crash).
