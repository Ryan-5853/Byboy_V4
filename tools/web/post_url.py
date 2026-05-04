from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class PostUrlConfig(BaseModel):
    max_read_chars: int = Field(default=50000, ge=1, le=2_000_000)
    timeout_seconds: float = Field(default=30, gt=0, le=180)
    follow_redirects: bool = True
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    default_headers: dict[str, str] = Field(default_factory=dict)


class PostUrlArgs(BaseModel):
    url: str = Field(min_length=1)
    data: dict[str, Any] | str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


def execute(args: PostUrlArgs, config: PostUrlConfig) -> str:
    import httpx
    import trafilatura

    scheme = urlparse(args.url).scheme.lower()
    if scheme not in config.allowed_schemes:
        allowed = ", ".join(config.allowed_schemes)
        raise ValueError(f"URL scheme not allowed: {scheme}. Allowed schemes: {allowed}")

    headers = dict(config.default_headers)
    headers.update(args.headers)
    response = httpx.post(
        args.url,
        data=args.data,
        headers=headers or None,
        timeout=config.timeout_seconds,
        follow_redirects=config.follow_redirects,
    )
    response.raise_for_status()
    text = trafilatura.extract(response.text) or response.text
    return text[: config.max_read_chars]


def build_pydantic_tool(config: PostUrlConfig):
    def post_url(
        url: str,
        data: dict[str, Any] | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """POST to a URL and return cleaned readable text."""
        try:
            args = PostUrlArgs.model_validate(
                {"url": url, "data": data, "headers": headers or {}}
            )
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR web.post_url failed for {url}: {type(exc).__name__}: {exc}"

    return post_url


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web.post_url",
        description="POST to a URL and return cleaned readable text.",
        config_model=PostUrlConfig,
        args_model=PostUrlArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )

