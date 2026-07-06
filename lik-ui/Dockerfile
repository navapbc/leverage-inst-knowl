FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

# Serve on all interfaces inside the container; the real guard is the allowed-hosts
# allowlist and a loopback-only host publish (see docker-compose.yml).
ENV LIK_UI_HTTP_HOST=0.0.0.0
ENV LIK_UI_ENV=prod

EXPOSE 8001

CMD ["python", "-m", "lik_ui"]
