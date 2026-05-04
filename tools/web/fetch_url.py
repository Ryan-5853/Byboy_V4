from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class FetchUrlConfig(BaseModel):
    max_read_chars: int = Field(default=5000, ge=1, le=1_000_000)
    timeout_seconds: float = Field(default=20, gt=0, le=120)
    follow_redirects: bool = True
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])


class FetchUrlArgs(BaseModel):
    url: str = Field(min_length=1)


def execute(args: FetchUrlArgs, config: FetchUrlConfig) -> str:
    import httpx
    import trafilatura

    scheme = urlparse(args.url).scheme.lower()
    if scheme not in config.allowed_schemes:
        allowed = ", ".join(config.allowed_schemes)
        raise ValueError(f"URL scheme not allowed: {scheme}. Allowed schemes: {allowed}")

    response = httpx.get(
        args.url,
        timeout=config.timeout_seconds,
        follow_redirects=config.follow_redirects,
    )
    response.raise_for_status()
    text = trafilatura.extract(response.text) or response.text
    return text[: config.max_read_chars]


def build_pydantic_tool(config: FetchUrlConfig):
    def fetch_url(url: str) -> str:
        """Fetch a URL and return cleaned readable text."""
        try:
            args = FetchUrlArgs.model_validate({"url": url})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR web.fetch_url failed for {url}: {type(exc).__name__}: {exc}"

    return fetch_url


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web.fetch_url",
        description="Fetch a URL and return cleaned readable text.",
        config_model=FetchUrlConfig,
        args_model=FetchUrlArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
