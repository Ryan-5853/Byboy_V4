from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class FetchJsonConfig(BaseModel):
    """Hard limits for JSON HTTP GET requests."""

    max_read_chars: int = Field(default=200000, ge=1, le=5_000_000)
    timeout_seconds: float = Field(default=30, gt=0, le=180)
    follow_redirects: bool = True
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    default_headers: dict[str, str] = Field(default_factory=dict)


class FetchJsonArgs(BaseModel):
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


def execute(args: FetchJsonArgs, config: FetchJsonConfig) -> Any:
    """Fetch JSON and parse it before returning it to the model.

    Returning parsed data prevents the model from wasting context on HTTP
    headers or huge raw strings, while max_read_chars still protects the caller
    from unexpectedly large responses.
    """

    import httpx

    scheme = urlparse(args.url).scheme.lower()
    if scheme not in config.allowed_schemes:
        allowed = ", ".join(config.allowed_schemes)
        raise ValueError(f"URL scheme not allowed: {scheme}. Allowed schemes: {allowed}")

    headers = dict(config.default_headers)
    headers.update(args.headers)
    response = httpx.get(
        args.url,
        headers=headers or None,
        timeout=config.timeout_seconds,
        follow_redirects=config.follow_redirects,
    )
    response.raise_for_status()
    text = response.text[: config.max_read_chars]
    if len(response.text) <= config.max_read_chars:
        import json

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            content_type = response.headers.get("content-type", "")
            preview = text[:200].replace("\n", " ")
            raise ValueError(
                "Response is not valid JSON. "
                f"content-type={content_type!r}, preview={preview!r}"
            ) from exc
    return _parse_truncated_json(text)


def _parse_truncated_json(text: str) -> Any:
    import json

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "JSON response exceeded max_read_chars and could not be parsed after truncation"
        ) from exc


def build_pydantic_tool(config: FetchJsonConfig):
    def fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
        """Fetch a URL and parse the response as JSON."""

        try:
            args = FetchJsonArgs.model_validate({"url": url, "headers": headers or {}})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR web.fetch_json failed for {url}: {type(exc).__name__}: {exc}"

    return fetch_json


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web.fetch_json",
        description="Fetch a URL and parse the response as JSON.",
        config_model=FetchJsonConfig,
        args_model=FetchJsonArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
