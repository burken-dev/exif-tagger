# ============================================================================
# exif-tagger – Multi-stage build for web dashboard service
# Stage 1: Build Web UI static bundle
# Stage 2: Build Python dependencies (fast, cached)
# Stage 3: Install system tools + runtime image
# ============================================================================

FROM node:20-alpine AS frontend-builder

WORKDIR /app/webui
COPY webui/package*.json ./
RUN npm ci || npm install
COPY webui/ ./
RUN npm run build


FROM python:3.12-alpine AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 3: Minimal production runtime image (default)
FROM python:3.12-alpine AS runtime

WORKDIR /app

ENV EXIFTAGGER_DATA_DIR=/app/data
ENV PUID=10000 PGID=10000

# Install exiftool via apk (pre-built, avoids CPAN test failures)
# su-exec drops root after entrypoint setup (see PUID/PGID handling below)
RUN apk add --no-cache perl exiftool su-exec

# Copy Python dependencies from builder stage
COPY --from=builder /install /usr/local

# Copy application source and install as package so imports resolve
COPY src/ ./src/
COPY webui/ ./webui/
COPY --from=frontend-builder /app/webui/dist ./webui/dist
COPY config.yaml.example ./config.yaml.example
COPY pyproject.toml .
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN pip install -e . --no-cache-dir && \
    mkdir -p /data/images /app/data

RUN adduser -S -D -H -h /app -u 10000 appuser && \
    chown -R appuser /app /data/images

# Expose dashboard port
EXPOSE 8080

# Run as root through the entrypoint so it can fix mount ownership,
# then it drops to $PUID:$PGID before starting the server.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "src.exif_tagger.server:app", "--host", "0.0.0.0", "--port", "8080"]

# Stage 4: Self-contained dev & testing target
FROM runtime AS dev

WORKDIR /app

RUN pip install --no-cache-dir pytest pytest-cov requests

RUN mkdir -p /app/data /data/images

COPY tests/ ./tests/

