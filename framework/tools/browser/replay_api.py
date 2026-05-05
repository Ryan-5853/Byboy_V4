from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from browser_runtime import replay_api_with_playwright
from tool_call import ToolSpec


class ReplayApiConfig(BaseModel):
    """Replay API requests inside a previously captured browser session."""

    backend: Literal["playwright"] = "playwright"
    timeout_seconds: float = Field(default=30, gt=0, le=180)
    max_response_body_chars: int = Field(default=120_000, ge=1, le=2_000_000)
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    allowed_domains: list[str] = Field(default_factory=list)


class ReplayApiArgs(BaseModel):
    session_id: str = Field(min_length=8)
    url: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    data: dict[str, Any] | str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


def execute(args: ReplayApiArgs, config: ReplayApiConfig) -> dict[str, object]:
    if config.backend != "playwright":
        raise ValueError(f"Unsupported browser backend: {config.backend}")
    return replay_api_with_playwright(
        session_id=args.session_id,
        url=args.url,
        method=args.method,
        data=args.data,
        headers=args.headers or None,
        timeout_seconds=config.timeout_seconds,
        max_response_body_chars=config.max_response_body_chars,
        allowed_schemes=config.allowed_schemes,
        allowed_domains=config.allowed_domains,
    )


def build_pydantic_tool(config: ReplayApiConfig):
    def replay_api(
        session_id: str,
        url: str,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET",
        data: dict[str, Any] | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object] | str:
        """Replay one API call in a browser session captured by browser.capture_xhr."""

        try:
            args = ReplayApiArgs.model_validate(
                {
                    "session_id": session_id,
                    "url": url,
                    "method": method,
                    "data": data,
                    "headers": headers or {},
                }
            )
            return execute(args, config)
        except Exception as exc:
            return (
                f"TOOL_ERROR browser.replay_api failed for {url}: "
                f"{type(exc).__name__}: {exc}"
            )

    return replay_api


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="browser.replay_api",
        description="Replay API requests with the same browser session/cookies.",
        config_model=ReplayApiConfig,
        args_model=ReplayApiArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
