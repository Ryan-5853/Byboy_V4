"""Browser runtime adapters used by browser tools."""

from .playwright_backend import capture_requests_with_playwright
from .playwright_backend import render_page_with_playwright, screenshot_page_with_playwright

__all__ = [
    "capture_requests_with_playwright",
    "render_page_with_playwright",
    "screenshot_page_with_playwright",
]
