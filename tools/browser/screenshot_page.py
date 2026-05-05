from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from browser_runtime import screenshot_page_with_playwright
from tool_call import ToolSpec
from tools.filesystem._safe_path import require_allowed_glob, resolve_workspace_path


class ScreenshotPageConfig(BaseModel):
    """Hard limits for browser screenshots written into the workspace."""

    workspace_root: str
    allow_write: bool = False
    backend: Literal["playwright"] = "playwright"
    browser_name: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    timeout_seconds: float = Field(default=30, gt=0, le=180)
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_globs: list[str] = Field(default_factory=list)
    viewport_width: int = Field(default=1440, ge=320, le=4000)
    viewport_height: int = Field(default=1080, ge=200, le=4000)
    user_agent: str | None = None
    locale: str | None = None
    block_resource_types: list[str] = Field(
        default_factory=lambda: ["media", "font"]
    )
    image_type: Literal["png", "jpeg"] = "png"
    image_quality: int | None = Field(default=None, ge=1, le=100)
    max_image_bytes: int = Field(default=10_000_000, ge=1, le=100_000_000)
    overwrite: bool = False


class ScreenshotPageArgs(BaseModel):
    url: str = Field(min_length=1)
    path: str = Field(min_length=1)
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "domcontentloaded"
    wait_for_selector: str | None = Field(default=None, max_length=300)
    full_page: bool = True


def execute(args: ScreenshotPageArgs, config: ScreenshotPageConfig) -> dict[str, object]:
    """Render a page in a browser and save a screenshot inside the workspace."""

    if not config.allow_write:
        raise PermissionError("browser.screenshot_page requires allow_write=true in tool config.")
    if config.backend != "playwright":
        raise ValueError(f"Unsupported browser backend: {config.backend}")

    target = resolve_workspace_path(config.workspace_root, args.path)
    require_allowed_glob(target, config.workspace_root, config.allowed_globs)
    if target.exists() and not config.overwrite:
        raise FileExistsError(f"File already exists and overwrite=false: {args.path}")

    result = screenshot_page_with_playwright(
        url=args.url,
        output_path=target,
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
        full_page=args.full_page,
        image_type=config.image_type,
        image_quality=config.image_quality,
        max_image_bytes=config.max_image_bytes,
        allowed_schemes=config.allowed_schemes,
        allowed_domains=config.allowed_domains,
    )
    result["path"] = args.path
    return result


def build_pydantic_tool(config: ScreenshotPageConfig):
    def screenshot_page(
        url: str,
        path: str,
        wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "domcontentloaded",
        wait_for_selector: str | None = None,
        full_page: bool = True,
    ) -> dict[str, object] | str:
        """Render a page in a browser and save a screenshot inside the workspace."""

        try:
            args = ScreenshotPageArgs.model_validate(
                {
                    "url": url,
                    "path": path,
                    "wait_until": wait_until,
                    "wait_for_selector": wait_for_selector,
                    "full_page": full_page,
                }
            )
            return execute(args, config)
        except Exception as exc:
            return (
                f"TOOL_ERROR browser.screenshot_page failed for {url}: "
                f"{type(exc).__name__}: {exc}"
            )

    return screenshot_page


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="browser.screenshot_page",
        description="Render a URL in a real browser and save a screenshot in the workspace.",
        config_model=ScreenshotPageConfig,
        args_model=ScreenshotPageArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
