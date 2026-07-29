FROM python:3.14-slim

# Bring in the uv binary (build-time only) to export the committed lockfile. The runtime stays
# plain `python -m` below — uv is not on the runtime path, only the base image's python.
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /bin/uv

WORKDIR /app

# Install the exact dependency set recorded in uv.lock, not a live re-resolution of the `>=`
# constraints in pyproject.toml. `--frozen` fails the build if the lock is stale vs pyproject, so a
# dependency bump is always a reviewed lock diff — never a silent side effect of the build date.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

# Install the app itself without re-touching dependencies — they are already pinned-installed above.
# The `[tool.setuptools.package-data]` in pyproject.toml ships templates, static assets, agents.toml,
# and faq.md inside this non-editable install; without them the app boots with an empty roster/FAQ.
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

# Serve on all interfaces inside the container; the real guard is the allowed-hosts
# allowlist and a loopback-only host publish (see docker-compose.yml).
ENV LIK_UI_HTTP_HOST=0.0.0.0
ENV LIK_UI_ENV=prod

EXPOSE 8001

CMD ["python", "-m", "lik_ui"]
