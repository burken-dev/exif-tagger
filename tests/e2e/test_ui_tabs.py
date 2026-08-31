"""Per-tab UI content tests for the React application.

Selectors derived from webui/src/:
  Processing:  #folderPath, #maxImages, 'Start Processing', 'Stop Processing', 'Browse'
  Gallery:     Search input, Sync button, Tag filters
  Config:      Model inputs, Save button
  Schedule:    Create/Add Schedule button
"""

from __future__ import annotations

from playwright.sync_api import Page

from tests.e2e.conftest import screenshot


def _click_tab(page: Page, tab_name: str) -> None:
    """Activate a tab by its text name and wait for React to render."""
    tab = page.locator("[role='tab']").filter(has_text=tab_name)
    tab.wait_for(state="attached")
    tab.click()
    page.wait_for_timeout(400)


# ---------------------------------------------------------------------------
# Processing tab
# ---------------------------------------------------------------------------


def test_processing_tab_heading(browser_page: Page):
    """Processing tab shows 'Session Control' card heading."""
    screenshot(browser_page, "tab_processing_content")
    html = browser_page.content()
    assert "Session Control" in html, "Expected 'Session Control' heading in HTML"


def test_processing_folder_path_input(browser_page: Page):
    """Processing tab has the #folderPath input."""
    inp = browser_page.locator("#folderPath")
    inp.wait_for(state="attached")
    tag = browser_page.evaluate("() => document.getElementById('folderPath').tagName.toLowerCase()")
    assert tag == "input"


def test_processing_max_images_input(browser_page: Page):
    """Processing tab has the #maxImages input."""
    inp = browser_page.locator("#maxImages")
    inp.wait_for(state="attached")
    inp_type = browser_page.evaluate("() => document.getElementById('maxImages').type")
    assert inp_type == "number"


def test_processing_subfolder_override_input(browser_page: Page):
    """Subfolder path entered into #folderPath is captured by the input element."""
    inp = browser_page.locator("#folderPath")
    inp.wait_for(state="attached")
    inp.fill("vacation-photos")
    val = browser_page.evaluate("() => document.getElementById('folderPath').value")
    assert val == "vacation-photos"


def test_processing_browse_button_present(browser_page: Page):
    """Processing tab renders the Browse button."""
    btn = browser_page.locator("button").filter(has_text="Browse")
    assert btn.count() > 0, "Browse button should be present in Session Control"


def test_processing_action_buttons_present(browser_page: Page):
    """Processing tab renders Start Processing enabled and Stop Processing disabled when idle."""
    start_btn = browser_page.locator("button").filter(has_text="Start Processing")
    assert start_btn.count() > 0, "Start Processing button should be present"
    assert start_btn.first.is_visible()
    assert start_btn.first.is_enabled()

    stop_btn = browser_page.locator("button").filter(has_text="Stop Processing")
    assert stop_btn.count() > 0, "Stop Processing button should be present"
    assert stop_btn.first.is_visible()
    assert stop_btn.first.is_disabled()

    pause_btn = browser_page.locator("button").filter(has_text="Pause Processing")
    assert pause_btn.count() == 0, "Pause Processing button should not be present when idle"

    resume_btn = browser_page.locator("button").filter(has_text="Resume Processing")
    assert resume_btn.count() == 0, "Resume Processing button should not be present when idle"


def test_processing_start_button_enabled(browser_page: Page):
    """Processing tab renders the Start Processing button enabled when idle."""
    btn = browser_page.locator("button").filter(has_text="Start Processing")
    assert btn.count() > 0, "Start Processing button should be present"
    disabled = btn.first.get_attribute("disabled")
    assert disabled is None, "Start Processing button should be enabled when idle"


def test_processing_stop_button_disabled(browser_page: Page):
    """Processing tab renders the Stop Processing button disabled when idle."""
    btn = browser_page.locator("button").filter(has_text="Stop Processing")
    assert btn.count() > 0, "Stop Processing button should be present"
    disabled = btn.first.get_attribute("disabled")
    assert disabled is not None, "Stop Processing button should be disabled when idle"


def test_processing_running_state_ui(browser_page: Page):
    """When processing is running, Pause is enabled, Stop is enabled, inputs are locked."""
    import json

    status_payload = {
        "running": True,
        "paused": False,
        "processed": 3,
        "total": 10,
        "currentImage": "image_003.jpg",
        "progressPct": 30.0,
        "stopRequested": False,
        "logs": [],
        "summary": None,
    }

    browser_page.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(status_payload),
        ),
    )

    browser_page.reload(wait_until="networkidle")

    # Verify action buttons
    pause_btn = browser_page.locator("button").filter(has_text="Pause Processing")
    pause_btn.wait_for(state="visible")
    assert pause_btn.is_enabled()

    stop_btn = browser_page.locator("button").filter(has_text="Stop Processing")
    assert stop_btn.is_visible()
    assert stop_btn.is_enabled()

    start_btn = browser_page.locator("button").filter(has_text="Start Processing")
    assert start_btn.count() == 0

    resume_btn = browser_page.locator("button").filter(has_text="Resume Processing")
    assert resume_btn.count() == 0

    # Verify directory locking & input disabling
    folder_input = browser_page.locator("#folderPath")
    assert folder_input.is_disabled()

    browse_btn = browser_page.locator("button").filter(has_text="Browse")
    assert browse_btn.is_disabled()

    max_images_input = browser_page.locator("#maxImages")
    assert max_images_input.is_disabled()

    screenshot(browser_page, "tab_processing_running_state")


def test_processing_paused_state_ui(browser_page: Page):
    """When processing is paused, Resume is enabled, Stop is enabled, inputs remain locked."""
    import json

    status_payload = {
        "running": True,
        "paused": True,
        "processed": 5,
        "total": 10,
        "currentImage": "image_005.jpg",
        "progressPct": 50.0,
        "stopRequested": False,
        "logs": [],
        "summary": None,
    }

    browser_page.route(
        "**/api/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(status_payload),
        ),
    )

    browser_page.reload(wait_until="networkidle")

    # Verify action buttons
    resume_btn = browser_page.locator("button").filter(has_text="Resume Processing")
    resume_btn.wait_for(state="visible")
    assert resume_btn.is_enabled()

    stop_btn = browser_page.locator("button").filter(has_text="Stop Processing")
    assert stop_btn.is_visible()
    assert stop_btn.is_enabled()

    start_btn = browser_page.locator("button").filter(has_text="Start Processing")
    assert start_btn.count() == 0

    pause_btn = browser_page.locator("button").filter(has_text="Pause Processing")
    assert pause_btn.count() == 0

    # Verify directory locking & input disabling
    folder_input = browser_page.locator("#folderPath")
    assert folder_input.is_disabled()

    browse_btn = browser_page.locator("button").filter(has_text="Browse")
    assert browse_btn.is_disabled()

    max_images_input = browser_page.locator("#maxImages")
    assert max_images_input.is_disabled()

    # Verify status badge shows Paused
    content = browser_page.content()
    assert "Paused" in content

    screenshot(browser_page, "tab_processing_paused_state")


def test_processing_pause_and_resume_button_actions(browser_page: Page):
    """Clicking Pause Processing calls /api/pause, and clicking Resume Processing calls /api/resume."""
    import json

    pause_called = []
    resume_called = []

    current_status = {
        "running": True,
        "paused": False,
        "processed": 2,
        "total": 10,
        "currentImage": "image_002.jpg",
        "progressPct": 20.0,
        "stopRequested": False,
        "logs": [],
        "summary": None,
    }

    def handle_status(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(current_status),
        )

    def handle_pause(route):
        pause_called.append(True)
        current_status["paused"] = True
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "paused"}),
        )

    def handle_resume(route):
        resume_called.append(True)
        current_status["paused"] = False
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "resumed"}),
        )

    browser_page.route("**/api/status", handle_status)
    browser_page.route("**/api/pause", handle_pause)
    browser_page.route("**/api/resume", handle_resume)

    browser_page.reload(wait_until="networkidle")

    # Click Pause
    pause_btn = browser_page.locator("button").filter(has_text="Pause Processing")
    pause_btn.wait_for(state="visible")
    pause_btn.click()

    browser_page.wait_for_timeout(300)
    assert len(pause_called) == 1, "Expected /api/pause to be called"

    # Click Resume
    resume_btn = browser_page.locator("button").filter(has_text="Resume Processing")
    resume_btn.wait_for(state="visible")
    resume_btn.click()

    browser_page.wait_for_timeout(300)
    assert len(resume_called) == 1, "Expected /api/resume to be called"


def test_processing_clear_log_persists_on_update(browser_page: Page):
    """Clicking Clear Log clears the view and subsequent status updates do not re-add old logs, only new ones."""
    import json

    current_status = {
        "running": True,
        "paused": False,
        "processed": 2,
        "total": 10,
        "currentImage": "image_002.jpg",
        "progressPct": 20.0,
        "stopRequested": False,
        "logs": [
            {"id": 1, "text": "Starting processing batch 1", "level": "info"},
            {"id": 2, "text": "Processing image_001.jpg", "level": "info"},
        ],
        "summary": None,
    }

    def handle_status(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(current_status),
        )

    browser_page.route("**/api/status", handle_status)
    browser_page.reload(wait_until="networkidle")

    # Verify initial logs are visible
    page_content = browser_page.content()
    assert "Starting processing batch 1" in page_content
    assert "Processing image_001.jpg" in page_content

    # Click Clear Log
    clear_btn = browser_page.locator("button").filter(has_text="Clear Log")
    clear_btn.wait_for(state="visible")
    assert clear_btn.is_enabled()
    clear_btn.click()

    # Wait for React state update
    browser_page.wait_for_timeout(300)
    html_after_clear = browser_page.content()
    assert "Starting processing batch 1" not in html_after_clear
    assert "Processing image_001.jpg" not in html_after_clear
    assert "No logs captured yet" in html_after_clear

    # Wait for the next poll cycle (1000ms poll interval when running) with the same logs (ids 1 & 2)
    browser_page.wait_for_timeout(1500)
    html_after_poll = browser_page.content()
    assert "Starting processing batch 1" not in html_after_poll, "Old log row 1 should not reappear on next update"
    assert "Processing image_001.jpg" not in html_after_poll, "Old log row 2 should not reappear on next update"

    # Add a new log row (id: 3)
    current_status["logs"].append({"id": 3, "text": "Processing image_002.jpg", "level": "info"})

    # Wait for poll cycle to pick up the new log
    browser_page.wait_for_timeout(1500)
    html_after_new_log = browser_page.content()
    assert "Processing image_002.jpg" in html_after_new_log, "New log row 3 should appear in log view"
    assert "Starting processing batch 1" not in html_after_new_log, "Old log row 1 should still not be present"
    assert "Processing image_001.jpg" not in html_after_new_log, "Old log row 2 should still not be present"


# ---------------------------------------------------------------------------
# Gallery tab
# ---------------------------------------------------------------------------


def test_gallery_tab_renders_without_error(browser_page: Page):
    """Gallery tab renders without crashing."""
    _click_tab(browser_page, "Gallery")
    screenshot(browser_page, "tab_gallery_content")
    html = browser_page.content()
    assert "Something went wrong" not in html
    assert "Cannot read" not in html


def test_gallery_has_search_or_filter(browser_page: Page):
    """Gallery tab renders search or filter controls."""
    _click_tab(browser_page, "Gallery")
    html = browser_page.content()
    assert any(kw in html for kw in ["Search", "Filter", "Tag", "Folder", "images"])


# ---------------------------------------------------------------------------
# Configuration tab
# ---------------------------------------------------------------------------


def test_config_section_becomes_active(browser_page: Page):
    """Configuration tab renders settings cards."""
    _click_tab(browser_page, "Configuration")
    screenshot(browser_page, "tab_config_content")
    html = browser_page.content()
    assert "Model" in html or "Config" in html or "Directory" in html


def test_config_has_inputs(browser_page: Page):
    """Configuration tab has multiple form inputs."""
    _click_tab(browser_page, "Configuration")
    count = browser_page.evaluate("() => document.querySelectorAll('input').length")
    assert count >= 3, f"Expected at least 3 inputs on Config tab, got {count}"


# ---------------------------------------------------------------------------
# Schedule tab
# ---------------------------------------------------------------------------


def test_schedule_section_becomes_active(browser_page: Page):
    """Schedule tab renders scheduling controls."""
    _click_tab(browser_page, "Schedule")
    screenshot(browser_page, "tab_schedule_content")
    html = browser_page.content()
    assert "Schedule" in html or "Cron" in html or "Interval" in html
