# Production image: API + built Svelte UI + yt-dlp + FFmpeg.
# Daily Windows editing still uses scripts/dev.ps1; this is the headless/Linux path.

# --- frontend ---
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- runtime ---
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Official yt-dlp + curl_cffi (browser impersonation helps YouTube).
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "yt-dlp>=2025.9.5" "curl_cffi>=0.7.0"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY --from=web /web/dist ./web/dist

ENV LONES_VDL_HOST=0.0.0.0
ENV LONES_VDL_PORT=8080
ENV LONES_VDL_WEB_DIST=/app/web/dist
ENV LONES_VDL_ARCHIVE_ROOT=/archive
ENV LONES_VDL_DATABASE_PATH=/var/lib/lones-vdl/lones_vdl.db

EXPOSE 8080
CMD ["python", "-m", "lones_vdl", "serve"]
