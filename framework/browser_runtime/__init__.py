"""Browser runtime adapters used by browser tools."""

from .playwright_backend import capture_requests_with_playwright
from .playwright_backend import capture_xhr_with_playwright
from .playwright_backend import export_browser_session
from .playwright_backend import import_browser_session
from .playwright_backend import replay_api_with_playwright
from .playwright_backend import render_page_with_playwright, screenshot_page_with_playwright

__all__ = [
    "capture_requests_with_playwright",
    "capture_xhr_with_playwright",
    "export_browser_session",
    "import_browser_session",
    "replay_api_with_playwright",
    "render_page_with_playwright",
    "screenshot_page_with_playwright",
]
