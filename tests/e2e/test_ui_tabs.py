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
