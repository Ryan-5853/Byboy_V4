from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from browser_runtime import capture_requests_with_playwright
from tool_call import ToolSpec


class CaptureRequestsConfig(BaseModel):
    """Hard limits for capturing browser network requests."""

    backend: Literal["playwright"] = "playwright"
    browser_name: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    timeout_seconds: float = Field(default=45, gt=0, le=240)
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    allowed_domains: list[str] = Field(default_factory=list)
    viewport_width: int = Field(default=1440, ge=320, le=4000)
    viewport_height: int = Field(default=1080, ge=200, le=4000)
    user_agent: str | None = None
    locale: str | None = None
    block_resource_types: list[str] = Field(default_factory=lambda: ["image", "media", "font"])
    allowed_resource_types: list[str] = Field(
        default_factory=lambda: ["xhr", "fetch", "document"]
    )
    include_response_body: bool = False
    max_response_body_chars: int = Field(default=4000, ge=0, le=200000)
    max_entries: int = Field(default=40, ge=1, le=300)


class CaptureRequestsArgs(BaseModel):
    url: str = Field(min_length=1)
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "domcontentloaded"
    wait_for_selector: str | None = Field(default=None, max_length=300)


def execute(args: CaptureRequestsArgs, config: CaptureRequestsConfig) -> dict[str, object]:
    """Capture rendered page network requests (XHR/fetch/document)."""

    if config.backend != "playwright":
        raise ValueError(f"Unsupported browser backend: {config.backend}")
    return capture_requests_with_playwright(
        url=args.url,
        browser_name=config.browser_name,
        headless=config.headless,
        timeout_seconds=config.timeout_seconds,
        wait_until=args.wait_until,
        wait_for_selector=args.wait_for_selector,
        viewport_width=config.viewport_width,
        viewport_height=config.viewport_height,
        user_agent=config.user_agent,
        locale=config.locale,
        block_resource_types=config.block_resource_types,
        allowed_resource_types=config.allowed_resource_types,
        include_response_body=config.include_response_body,
        max_response_body_chars=config.max_response_body_chars,
        max_entries=config.max_entries,
        allowed_schemes=config.allowed_schemes,
        allowed_domains=config.allowed_domains,
    )


def build_pydantic_tool(config: CaptureRequestsConfig):
    def capture_requests(
        url: str,
        wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "domcontentloaded",
        wait_for_selector: str | None = None,
    ) -> dict[str, object] | str:
        """Capture network requests while rendering a page in a real browser."""

        try:
            args = CaptureRequestsArgs.model_validate(
                {
                    "url": url,
                    "wait_until": wait_until,
                    "wait_for_selector": wait_for_selector,
                }
            )
            return execute(args, config)
        except Exception as exc:
            return (
                f"TOOL_ERROR browser.capture_requests failed for {url}: "
                f"{type(exc).__name__}: {exc}"
            )

    return capture_requests


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="browser.capture_requests",
        description="Render a URL and capture XHR/fetch/document network requests.",
        config_model=CaptureRequestsConfig,
        args_model=CaptureRequestsArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
