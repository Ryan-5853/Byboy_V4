from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from browser_runtime import render_page_with_playwright
from tool_call import ToolSpec


class RenderPageConfig(BaseModel):
    """Hard limits for rendered browser reads.

    The configured backend is fixed per agent. Runtime args may choose only the
    target URL and a small number of bounded wait hints.
    """

    backend: Literal["playwright"] = "playwright"
    browser_name: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    timeout_seconds: float = Field(default=30, gt=0, le=180)
    max_html_chars: int = Field(default=200_000, ge=1, le=2_000_000)
    max_text_chars: int = Field(default=30_000, ge=1, le=500_000)
    max_links: int = Field(default=200, ge=0, le=5000)
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    allowed_domains: list[str] = Field(default_factory=list)
    viewport_width: int = Field(default=1440, ge=320, le=4000)
    viewport_height: int = Field(default=1080, ge=200, le=4000)
    user_agent: str | None = None
    locale: str | None = None
    block_resource_types: list[str] = Field(
        default_factory=lambda: ["image", "media", "font"]
    )


class RenderPageArgs(BaseModel):
    url: str = Field(min_length=1)
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "domcontentloaded"
    wait_for_selector: str | None = Field(default=None, max_length=300)


def execute(args: RenderPageArgs, config: RenderPageConfig) -> dict[str, object]:
    """Render a page in a real browser and return bounded text/html/link data."""

    if config.backend != "playwright":
        raise ValueError(f"Unsupported browser backend: {config.backend}")
    return render_page_with_playwright(
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
        max_html_chars=config.max_html_chars,
        max_text_chars=config.max_text_chars,
        max_links=config.max_links,
        allowed_schemes=config.allowed_schemes,
        allowed_domains=config.allowed_domains,
    )


def build_pydantic_tool(config: RenderPageConfig):
    def render_page(
        url: str,
        wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "domcontentloaded",
        wait_for_selector: str | None = None,
    ) -> dict[str, object] | str:
        """Render a page in a browser and return bounded text, html, and links."""

        try:
            args = RenderPageArgs.model_validate(
                {
                    "url": url,
                    "wait_until": wait_until,
                    "wait_for_selector": wait_for_selector,
                }
            )
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR browser.render_page failed for {url}: {type(exc).__name__}: {exc}"

    return render_page


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="browser.render_page",
        description="Render a URL in a real browser and return bounded text, HTML, and links.",
        config_model=RenderPageConfig,
        args_model=RenderPageArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
