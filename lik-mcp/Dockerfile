FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Serve the long-lived HTTP transport by default; bind all interfaces so the listener
# is reachable through Docker's published port (the host side publishes 127.0.0.1 only,
# and the server restricts the accepted Host header to loopback — see server.py).
ENV LIK_TRANSPORT=streamable-http
ENV FASTMCP_HOST=0.0.0.0

# LIK_ENV is intentionally NOT baked in: the same image serves local testing
# (LIK_ENV=local, supplied by docker compose) and a future deploy (LIK_ENV=prod,
# which fails closed until real OIDC lands). Transport comes from env, not the command.
EXPOSE 8000
CMD ["python", "-m", "lik_mcp"]
