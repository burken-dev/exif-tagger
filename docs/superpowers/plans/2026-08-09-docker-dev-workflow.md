# Docker-Based Dev & Testing Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable a containerized dev/testing workflow where the AI agent builds, runs, and tests code inside Docker containers via `/var/run/docker.sock`.

**Architecture:** Add a multi-stage `dev` build target in `Dockerfile`, update Playwright `conftest.py` to reuse the exposed container port (`http://localhost:9100`), and create a single management script (`scripts/docker-dev.sh`).

**Tech Stack:** Docker, Alpine Linux, Python 3.12, FastAPI, pytest, Playwright.

## Global Constraints
- Target container port: `8080` exposed to host port `9100`.
- Server access URL for tests: `http://localhost:9100`.
- All shell scripts must use `set -euo pipefail`.

---

### Task 1: Add `--target dev` Stage to Dockerfile

**Files:**
- Modify: [`Dockerfile`](file:///projects/dev/exif-tagger/Dockerfile)

**Interfaces:**
- Produces: Docker image target `dev` (`docker build --target dev -t exif-tagger:dev .`).

- [ ] **Step 1: Inspect existing Dockerfile structure**

Read lines 1-52 of [`Dockerfile`](file:///projects/dev/exif-tagger/Dockerfile).

- [ ] **Step 2: Add `AS runtime` to production stage and append `dev` stage**

Modify [`Dockerfile`](file:///projects/dev/exif-tagger/Dockerfile) to label stage 3 as `runtime` and add stage 4 as `dev`:

```dockerfile
# Stage 3: Minimal production runtime image (default)
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

RUN pip install -e . --no-cache-dir && \
    mkdir -p /data/images /app/data

EXPOSE 8080

ENTRYPOINT ["uvicorn", "src.exif_tagger.server:app", "--host", "0.0.0.0", "--port", "8080"]

# Stage 4: Self-contained dev & testing target
FROM runtime AS dev

WORKDIR /app

RUN pip install --no-cache-dir pytest pytest-cov requests

COPY config.dev.yaml ./config.dev.yaml
COPY testimages/ ./testimages/
COPY tests/ ./tests/

ENV EXIFTAGGER_CONFIG_FILE=/app/config.dev.yaml
ENV EXIFTAGGER_ROOT_DIRECTORY=/app/testimages
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): add dev target stage to Dockerfile"
```

---

### Task 2: Update Playwright E2E Fixture for Docker Container Testing

**Files:**
- Modify: [`tests/e2e/conftest.py`](file:///projects/dev/exif-tagger/tests/e2e/conftest.py:56-153)

**Interfaces:**
- Consumes: `E2E_SERVER_URL` environment variable (default: `http://localhost:9100`).
- Produces: `dev_server` fixture yielding `{"url": E2E_SERVER_URL}`.

- [ ] **Step 1: Inspect `tests/e2e/conftest.py` server fixture**

Read lines 50-155 of [`tests/e2e/conftest.py`](file:///projects/dev/exif-tagger/tests/e2e/conftest.py#L50-L155).

- [ ] **Step 2: Update `SERVER_URL` and `dev_server` fixture to respect `E2E_SERVER_URL` and container port `9100`**

Update `SERVER_URL` in [`tests/e2e/conftest.py`](file:///projects/dev/exif-tagger/tests/e2e/conftest.py):

```python
SERVER_URL = os.environ.get("E2E_SERVER_URL", "http://localhost:9100")
```

In the `dev_server` fixture, check if port from `SERVER_URL` is already open before attempting to launch local `uvicorn`.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/conftest.py
git commit -m "feat(e2e): configure conftest.py to target Docker container on port 9100"
```

---

### Task 3: Create Automation Script `scripts/docker-dev.sh`

**Files:**
- Create: [`scripts/docker-dev.sh`](file:///projects/dev/exif-tagger/scripts/docker-dev.sh)

**Interfaces:**
- Consumes: CLI commands `build`, `up`, `test`, `test-e2e`, `logs`, `down`.
- Produces: Shell interface for container execution and testing.

- [ ] **Step 1: Create `scripts/docker-dev.sh` file**

Write the following script content to [`scripts/docker-dev.sh`](file:///projects/dev/exif-tagger/scripts/docker-dev.sh):

```bash
#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="exif-tagger-dev"
IMAGE_NAME="exif-tagger:dev"
PORT="${DEV_PORT:-9100}"

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

- [ ] **Step 2: Make script executable**

Run: `chmod +x scripts/docker-dev.sh`

- [ ] **Step 3: Commit**

```bash
git add scripts/docker-dev.sh
git commit -m "feat(scripts): add docker-dev.sh management script"
```
