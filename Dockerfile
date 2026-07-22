# syntax=docker/dockerfile:1

FROM node:20.19.4-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY logo.png /build/logo.png
RUN npm run build


FROM python:3.12.13-alpine3.23 AS runtime

LABEL org.opencontainers.image.title="Agent4API" \
      org.opencontainers.image.description="Turn Swagger/OpenAPI operations into Tools for AI Agents" \
      org.opencontainers.image.source="https://github.com/apoet/Agent4API"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend/src \
    CHAT4OPENAPI_DATABASE_URL=sqlite:////app/data/chat4openapi.db \
    CHAT4OPENAPI_ENCRYPTION_KEY_FILE=/app/data/.chat4openapi.key

WORKDIR /app

COPY backend/ ./backend/
RUN apk add --no-cache --virtual .build-deps \
      cargo \
      gcc \
      libffi-dev \
      linux-headers \
      musl-dev \
      openssl-dev \
    && python -m pip install --no-cache-dir --upgrade pip==26.1.2 \
    && python -m pip install --no-cache-dir ./backend \
    && apk del .build-deps

COPY --from=frontend-build /build/frontend/dist/ ./frontend/dist/
COPY logo.png ./logo.png

RUN addgroup -S agent4api \
    && adduser -S -D -H -G agent4api -h /app agent4api \
    && mkdir -p /app/data \
    && chown -R agent4api:agent4api /app

USER agent4api

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["sh", "-c", "alembic -c backend/alembic.ini upgrade head && exec uvicorn chat4openapi.main:app --host 0.0.0.0 --port 8000"]
