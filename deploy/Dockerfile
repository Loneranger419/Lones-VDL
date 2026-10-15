# Production-oriented image for headless Linux. Not used as the Windows edit loop.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Pin yt-dlp in a follow-up milestone; placeholder install for image shape.
RUN pip install --no-cache-dir "yt-dlp>=2024.10.0"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV LONES_VDL_HOST=0.0.0.0
ENV LONES_VDL_PORT=8080

EXPOSE 8080
CMD ["python", "-m", "lones_vdl"]
