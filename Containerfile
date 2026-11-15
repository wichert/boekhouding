FROM node:22-alpine AS frontend

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend ./frontend
RUN npm run build

FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python \
    PATH="/app/.venv/bin:$PATH" \
    BIND_HOST=0.0.0.0 \
    BIND_PORT=8000

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY boekhouding ./boekhouding
COPY --from=frontend /app/boekhouding/static/app ./boekhouding/static/app
RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2).close()"]

CMD ["boekhouding", "serve"]
