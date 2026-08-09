"""E2E test fixtures: server lifecycle and Playwright browser.

The exif-tagger app is served by the FastAPI server on port 9100 (or E2E_SERVER_URL),
which handles both the API (/api/*) and the static web UI (/, /css/style.css,
/js/app.js).  There is no separate frontend dev server needed for E2E
testing.

Usage:
    pytest tests/e2e/ -v                  # full suite (starts server auto)
    pytest tests/e2e/ -v -s               # with live stdout for debugging

The `dev_server` fixture (session-scoped) starts the FastAPI backend if
port 9100 is not already occupied.

The `browser_page` fixture (function-scoped) opens a headless Chromium page
at E2E_SERVER_URL and auto-saves screenshots at start, end, and on failure.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Chromium system library path (no-sudo workaround for minimal Docker images)
# ---------------------------------------------------------------------------
# The Playwright Chromium headless shell requires glib, nss, atk, etc.
# On a container without those system libs we extract them from Ubuntu debs
# into /tmp/chromium-libs/libs and inject the path here so the subprocess
# launched by Playwright inherits it.
_CHROMIUM_EXTRA_LIBS = "/tmp/chromium-libs/libs/usr/lib/x86_64-linux-gnu"
if os.path.isdir(_CHROMIUM_EXTRA_LIBS):
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = (
        f"{_CHROMIUM_EXTRA_LIBS}:{existing}" if existing else _CHROMIUM_EXTRA_LIBS
    )
    fonts_conf = "/tmp/chromium-libs/libs/etc/fonts/fonts.conf"
    if os.path.exists(fonts_conf):
        os.environ["FONTCONFIG_PATH"] = "/tmp/chromium-libs/libs/etc/fonts"
        os.environ["FONTCONFIG_FILE"] = fonts_conf

import pytest
import requests
from playwright.sync_api import Page, sync_playwright

# ---------------------------------------------------------------------------
# Paths and URLs
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent.parent          # repo root
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"

SERVER_URL = os.environ.get("E2E_SERVER_URL", "http://localhost:9100")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port_open(host: str, port: int) -> bool:
    """Return True if something is already listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_for_http(url: str, timeout: int = 60) -> None:
    """Poll url until it responds with any non-5xx status, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Server at {url} did not become ready within {timeout}s")


def screenshot(page: Page, name: str) -> Path:
    """Save a full-page screenshot to tests/e2e/screenshots/<name>.png.

    Returns the saved path. Safe to call from any test — directory is
    created automatically.
    """
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    path = SCREENSHOTS_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


# ---------------------------------------------------------------------------
# Server lifecycle fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def dev_server():
    """Start the FastAPI backend if not already running.

    The FastAPI server on port 8000 serves both the REST API (/api/*)
    and the static web UI (/) so there is no separate frontend server.

    Yields a dict::

        {"url": "http://localhost:8000"}

    Only processes launched by this fixture are terminated on teardown.
    Pre-existing servers are left alone.
    """
    # Build environment — merge repo .env.development on top of current env
    env = os.environ.copy()
    env_file = ROOT / ".env.development"
    if env_file.exists():
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip().strip('"'))

    env["EXIFTAGGER_CONFIG_FILE"] = str(ROOT / "config.dev.yaml")

    # Ensure image root dir referenced by config.dev.yaml exists
    Path("/tmp/exif-tagger-test-images/test-photos").mkdir(parents=True, exist_ok=True)

    procs: list[subprocess.Popen] = []

    parsed = urlparse(SERVER_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 9100

    # --- Backend (uvicorn) ---
    already_up = _port_open(host, port)
    if not already_up:
        proc = subprocess.Popen(
            [
                str(ROOT / ".venv/bin/uvicorn"),
                "src.exif_tagger.server:app",
                "--host", "0.0.0.0",
                "--port", str(port),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        procs.append(proc)

    _wait_for_http(f"{SERVER_URL}/api/status")

    yield {"url": SERVER_URL}

    for proc in procs:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# Browser + screenshot fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def browser_page(dev_server, request):
    """Yield a headless Chromium Playwright page at the app URL.

    Auto-screenshots:
    - ``<test_name>_start.png``  — immediately after page load
    - ``<test_name>_end.png``    — after the test body returns
    - ``<test_name>_FAIL.png``   — only on test failure

    Screenshots are saved to ``tests/e2e/screenshots/``.
    """
    test_name = request.node.name.replace("/", "_").replace(" ", "_").replace("[", "_").replace("]", "_")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto(dev_server["url"], wait_until="networkidle")
        screenshot(page, f"{test_name}_start")

        failed = False
        try:
            yield page
        except Exception:
            failed = True
            raise
        finally:
            if failed:
                screenshot(page, f"{test_name}_FAIL")
            screenshot(page, f"{test_name}_end")
            context.close()
            browser.close()
