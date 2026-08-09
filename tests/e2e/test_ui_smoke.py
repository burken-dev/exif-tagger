"""Smoke tests: does the React app load and are all four tabs reachable?

The UI is the React application served by FastAPI at port 8000.
Structure:
  - 4 tabs: Processing, Gallery, Configuration, Schedule
  - Tab elements: <button role="tab" ...> or [role="tab"]
  - Active state: aria-selected="true" or data-state="active"
"""
from __future__ import annotations

from playwright.sync_api import Page

from tests.e2e.conftest import screenshot


def test_page_title(browser_page: Page):
    """The browser tab title contains 'EXIF Tagger'."""
    assert "EXIF Tagger" in browser_page.title()


def test_header_h1_present(browser_page: Page):
    """The <h1> header is in the DOM and reads 'EXIF Tagger Dashboard'."""
    h1 = browser_page.locator("h1").first
    h1.wait_for(state="attached")
    assert "EXIF Tagger" in (h1.text_content() or "")


def test_status_indicator_present(browser_page: Page):
    """The status indicator badge is present."""
    page_text = browser_page.content()
    assert "Status:" in page_text or "Idle" in page_text or "Running" in page_text, (
        "Status indicator text not found in HTML"
    )


def test_all_four_tabs_present(browser_page: Page):
    """All four navigation tabs are in the DOM."""
    tabs = browser_page.locator("[role='tab']").all()
    tab_texts = [t.text_content().strip() for t in tabs]
    assert len(tabs) == 4, f"Expected 4 tabs, got {len(tabs)}. Texts: {tab_texts}"
    for expected in ("Processing", "Gallery", "Configuration", "Schedule"):
        assert any(expected in t for t in tab_texts), (
            f"Tab '{expected}' not found. Tabs: {tab_texts}"
        )


def test_processing_tab_active_by_default(browser_page: Page):
    """Processing tab is selected by default on load."""
    tab = browser_page.locator("[role='tab']").filter(has_text="Processing")
    tab.wait_for(state="attached")
    state = tab.get_attribute("aria-selected") or tab.get_attribute("data-state") or ""
    assert state in ("true", "active"), f"Processing tab not active on load. State: {state!r}"


def test_click_gallery_tab(browser_page: Page):
    """Clicking Gallery tab activates it."""
    gallery_tab = browser_page.locator("[role='tab']").filter(has_text="Gallery")
    gallery_tab.wait_for(state="attached")
    gallery_tab.click()
    browser_page.wait_for_timeout(300)
    screenshot(browser_page, "smoke_gallery_tab")
    state = gallery_tab.get_attribute("aria-selected") or gallery_tab.get_attribute("data-state") or ""
    assert state in ("true", "active"), f"Gallery tab not active after click. State: {state!r}"


def test_click_config_tab(browser_page: Page):
    """Clicking Configuration tab activates it."""
    config_tab = browser_page.locator("[role='tab']").filter(has_text="Configuration")
    config_tab.wait_for(state="attached")
    config_tab.click()
    browser_page.wait_for_timeout(300)
    screenshot(browser_page, "smoke_config_tab")
    state = config_tab.get_attribute("aria-selected") or config_tab.get_attribute("data-state") or ""
    assert state in ("true", "active"), f"Config tab not active after click. State: {state!r}"


def test_click_schedule_tab(browser_page: Page):
    """Clicking Schedule tab activates it."""
    schedule_tab = browser_page.locator("[role='tab']").filter(has_text="Schedule")
    schedule_tab.wait_for(state="attached")
    schedule_tab.click()
    browser_page.wait_for_timeout(300)
    screenshot(browser_page, "smoke_schedule_tab")
    state = schedule_tab.get_attribute("aria-selected") or schedule_tab.get_attribute("data-state") or ""
    assert state in ("true", "active"), f"Schedule tab not active after click. State: {state!r}"


def test_click_processing_tab(browser_page: Page):
    """Clicking Processing tab after navigating away re-activates it."""
    browser_page.locator("[role='tab']").filter(has_text="Configuration").click()
    browser_page.wait_for_timeout(200)
    processing_tab = browser_page.locator("[role='tab']").filter(has_text="Processing")
    processing_tab.click()
    browser_page.wait_for_timeout(300)
    screenshot(browser_page, "smoke_processing_tab")
    state = processing_tab.get_attribute("aria-selected") or processing_tab.get_attribute("data-state") or ""
    assert state in ("true", "active")


def test_no_js_console_errors(browser_page: Page):
    """No JavaScript errors are emitted on initial page load."""
    errors: list[str] = []
    browser_page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    browser_page.reload(wait_until="networkidle")
    assert errors == [], f"JS console errors on load: {errors}"
