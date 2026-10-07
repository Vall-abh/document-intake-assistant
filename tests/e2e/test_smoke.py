import os
import pytest
from playwright.sync_api import sync_playwright

@pytest.mark.e2e
def test_browser_smoke():
    if os.getenv("RUN_E2E") != "1": pytest.skip("set RUN_E2E=1 to run browser tests")
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page()
        page.goto(os.getenv("E2E_BASE_URL","http://127.0.0.1:8000"))
        assert page.get_by_role("heading", name="Document Intake Assistant").is_visible()
        page.get_by_role("button", name="Preview").click()
        browser.close()
