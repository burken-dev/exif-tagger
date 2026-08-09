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
