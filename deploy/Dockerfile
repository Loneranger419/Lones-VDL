# syntax=docker/dockerfile:1
# Production image: FastAPI backend + built SvelteKit SPA + FFmpeg + Deno.
# yt-dlp is NOT baked in; the app installs/updates it under /data/ytdlp at runtime (Phase 2).

# --- frontend -------------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- runtime --------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ARG DENO_VERSION=2.9.7
ARG TARGETARCH

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

# Deno solves YouTube JS challenges (yt-dlp-ejs); FFmpeg merges/probes media.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && case "${TARGETARCH:-amd64}" in \
         amd64) deno_arch=x86_64 ;; \
         arm64) deno_arch=aarch64 ;; \
         *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /tmp/deno.zip \
         "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${deno_arch}-unknown-linux-gnu.zip" \
    && unzip -o /tmp/deno.zip -d /usr/local/bin \
    && rm /tmp/deno.zip \
    && apt-get purge -y curl unzip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-dev

COPY --from=frontend /src/frontend/build /app/frontend
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    HOME=/data/home \
    XDG_CACHE_HOME=/data/cache \
    DENO_DIR=/data/cache/deno \
    LONES_VDL_HOST=0.0.0.0 \
    LONES_VDL_PORT=8080 \
    LONES_VDL_DATA_DIR=/data \
    LONES_VDL_ARCHIVE_ROOT=/archive \
    LONES_VDL_FRONTEND_DIST=/app/frontend

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"]

ENTRYPOINT ["entrypoint.sh"]
CMD ["lones-vdl", "serve"]
