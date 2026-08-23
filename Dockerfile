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

# Install exiftool via apk (pre-built, avoids CPAN test failures)
RUN apk add --no-cache perl exiftool

# Copy Python dependencies from builder stage
COPY --from=builder /install /usr/local

# Copy application source and install as package so imports resolve
COPY src/ ./src/
COPY webui/ ./webui/
COPY --from=frontend-builder /app/webui/dist ./webui/dist
COPY config.yaml.example ./config.yaml.example
COPY pyproject.toml .

RUN pip install -e . --no-cache-dir && \
    mkdir -p /data/images /app/data

# Expose dashboard port
EXPOSE 8080

# Run FastAPI server via uvicorn
ENTRYPOINT ["uvicorn", "src.exif_tagger.server:app", "--host", "0.0.0.0", "--port", "8080"]

# Stage 4: Self-contained dev & testing target
FROM runtime AS dev

WORKDIR /app

RUN pip install --no-cache-dir pytest pytest-cov requests

RUN mkdir -p /app/data /data/images

COPY tests/ ./tests/

