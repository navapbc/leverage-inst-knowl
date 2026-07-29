FROM python:3.12-slim

# Bring in the uv binary (build-time only) to export the committed lockfile. The runtime stays
# plain `python -m` below — uv is not on the runtime path, only the base image's python.
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /bin/uv

WORKDIR /app

# Install the exact dependency set recorded in uv.lock, not a live re-resolution of the `>=`
# constraints in pyproject.toml. `--frozen` fails the build if the lock is stale vs pyproject, so a
# dependency bump is always a reviewed lock diff — never a silent side effect of the build date.
# (This is the fix for the mcp-2.0 incident: an unpinned build resolved a breaking major and the
# container crashed on import. See pyproject.toml for the belt-and-suspenders `mcp<2` cap.)
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

# Install the app itself without re-touching dependencies — they are already pinned-installed above.
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

# Serve the long-lived HTTP transport by default; bind all interfaces so the listener
# is reachable through Docker's published port (the host side publishes 127.0.0.1 only,
# and the server restricts the accepted Host header to loopback — see server.py).
ENV LIK_TRANSPORT=streamable-http
ENV LIK_HTTP_HOST=0.0.0.0

# Default to the fail-closed env so an unconfigured run of this image rejects every
# call (real Google OIDC isn't built yet — see auth.py). docker compose overrides this
# to LIK_ENV=local for testing; a deploy keeps prod until OIDC lands. One image, env
# supplied at run time.
ENV LIK_ENV=prod

EXPOSE 8000
CMD ["python", "-m", "lik_mcp"]
