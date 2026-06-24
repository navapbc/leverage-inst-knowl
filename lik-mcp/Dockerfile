FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Real Google OIDC verification is not built yet; prod runs fail-closed (see auth.py).
ENV LIK_ENV=prod

# MCP over stdio.
CMD ["python", "-m", "lik_mcp"]
