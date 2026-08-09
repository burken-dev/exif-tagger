# Docker-Based Development and Testing Workflow Design

## Overview
This design replaces local runtime installations in the development environment with a containerized Docker workflow. The AI agent builds and runs `exif-tagger` using multi-stage Docker targets, tests backend logic directly inside the container via `docker exec`, and executes Playwright E2E tests against the exposed container port.

## Goals
- Eliminate runtime dependency installation requirements in the local host/dev container.
- Enable fast, reproducible container build, execution, and test loops using the attached host Docker socket (`/var/run/docker.sock`).
- Standardize dev container network binding to port `9100`.
- Support self-contained test images and configuration inside the `dev` stage build target.

---

## 1. Dockerfile Multi-Stage Targets

Modify [`Dockerfile`](file:///projects/dev/exif-tagger/Dockerfile) to add a distinct `--target dev` stage while leaving the production `runtime` stage clean and lightweight.

```dockerfile
# Stage 1: Build Web UI static bundle
FROM node:20-alpine AS frontend-builder
WORKDIR /app/webui
COPY webui/package*.json ./
RUN npm ci || npm install
COPY webui/ ./
RUN npm run build

# Stage 2: Build Python dependencies
FROM python:3.12-alpine AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 3: Production Runtime Target (Default)
FROM python:3.12-alpine AS runtime
WORKDIR /app
ENV EXIFTAGGER_DATA_DIR=/app/data
RUN apk add --no-cache perl exiftool
COPY --from=builder /install /usr/local
COPY src/ ./src/
COPY webui/ ./webui/
COPY --from=frontend-builder /app/webui/dist ./webui/dist
COPY config.yaml.example ./config.yaml.example
COPY pyproject.toml .
RUN pip install -e . --no-cache-dir && mkdir -p /data/images /app/data
EXPOSE 8080
ENTRYPOINT ["uvicorn", "src.exif_tagger.server:app", "--host", "0.0.0.0", "--port", "8080"]

# Stage 4: Dev & Testing Target (--target dev)
FROM runtime AS dev
WORKDIR /app
RUN pip install --no-cache-dir pytest pytest-cov requests
COPY config.dev.yaml ./config.dev.yaml
COPY testimages/ ./testimages/
COPY tests/ ./tests/
ENV EXIFTAGGER_CONFIG_FILE=/app/config.dev.yaml
ENV EXIFTAGGER_ROOT_DIRECTORY=/app/testimages
```

---

## 2. E2E Test Fixture Configuration

Update [`tests/e2e/conftest.py`](file:///projects/dev/exif-tagger/tests/e2e/conftest.py):
- Read `E2E_SERVER_URL` environment variable (default: `http://localhost:9100`).
- Check if `http://localhost:9100` (or `E2E_SERVER_URL`) is open and responding.
- If the Docker container is already active on port `9100`, reuse it without starting a local uvicorn subprocess.

---

## 3. Automation Helper Script (`scripts/docker-dev.sh`)

Create executable [`scripts/docker-dev.sh`](file:///projects/dev/exif-tagger/scripts/docker-dev.sh):

```bash
#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="exif-tagger-dev"
IMAGE_NAME="exif-tagger:dev"
PORT="9100"

case "${1:-up}" in
  build)
    echo "=== Building Dev Image (target: dev) ==="
    docker build --target dev -t "$IMAGE_NAME" .
    ;;

  up)
    echo "=== Starting Dev Container on Port $PORT ==="
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    docker run -d --name "$CONTAINER_NAME" \
      -p "${PORT}:8080" \
      "$IMAGE_NAME"
    echo "Server available at http://localhost:${PORT}"
    ;;

  test)
    echo "=== Running Unit & API Tests in Container ==="
    docker exec "$CONTAINER_NAME" pytest tests/ --ignore=tests/e2e "${@:2}"
    ;;

  test-e2e)
    echo "=== Running E2E Playwright Tests against Container ==="
    E2E_SERVER_URL="http://localhost:${PORT}" pytest tests/e2e/ "${@:2}"
    ;;

  logs)
    docker logs -f "$CONTAINER_NAME"
    ;;

  down|stop)
    echo "=== Stopping Dev Container ==="
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    ;;

  *)
    echo "Usage: $0 {build|up|test|test-e2e|logs|down}"
    exit 1
    ;;
esac
```

---

## Verification Plan
1. **Docker socket access check**: Run `docker info` to verify socket connectivity.
2. **Build dev image**: Run `./scripts/docker-dev.sh build`.
3. **Spin up container**: Run `./scripts/docker-dev.sh up`.
4. **Execute backend test suite**: Run `./scripts/docker-dev.sh test`.
5. **Execute E2E UI test suite**: Run `./scripts/docker-dev.sh test-e2e`.
6. **Teardown**: Run `./scripts/docker-dev.sh down`.
