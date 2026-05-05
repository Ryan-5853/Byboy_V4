from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
import json

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

    scheme = urlparse(args.url).scheme.lower()
    if scheme not in config.allowed_schemes:
        allowed = ", ".join(config.allowed_schemes)
        raise ValueError(f"URL scheme not allowed: {scheme}. Allowed schemes: {allowed}")

    headers = dict(config.default_headers)
    headers.update(args.headers)
    data = args.data

    # Common LLM mistake: passing quoted form string like "\"id=1&versionId=\"".
    if isinstance(data, str):
        stripped = data.strip()
        if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
            data = stripped[1:-1]

    # Soft validation: common malformed form payload produced by LLM retries.
    if isinstance(data, dict) and len(data) == 1:
        only_key, only_val = next(iter(data.items()))
        if isinstance(only_key, str) and "=" in only_key and (only_val == "" or only_val is None):
            raise ValueError(
                "Suspicious form payload shape. You likely encoded form fields into a dict key. "
                "Use a normal form string like 'id=xxx&versionId=' or a dict {'id':'xxx','versionId':''}."
            )

    response = httpx.post(
        args.url,
        data=data,
        headers=headers or None,
        timeout=config.timeout_seconds,
        follow_redirects=config.follow_redirects,
    )
    response.raise_for_status()
    # Some endpoints return HTTP 200 with semantic failure payload like:
    # {"msg":"sql error"}.
    # Treat this as tool failure so the model changes strategy instead of retrying forever.
    # IMPORTANT: if body is not JSON (e.g. HTML fragment), do not fail here.
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        msg = str(payload.get("msg", "")).strip().lower()
        if msg in {"sql error", "error", "failed"}:
            param_hint = ""
            if isinstance(data, dict):
                pid = str(data.get("id", "")).strip()
                if pid and not pid.isdigit():
                    param_hint = " (tip: id 可能应为页面里的数字 data-tid，而非 uuid/用户名)"
            raise ValueError(
                "Server returned semantic failure payload: "
                f"{json.dumps(payload, ensure_ascii=False)}{param_hint}"
            )

    try:
        import trafilatura

        text = trafilatura.extract(response.text) or response.text
    except Exception:
        # Degrade gracefully when trafilatura is unavailable.
        text = response.text
    text = text[: config.max_read_chars]
    if not text.strip():
        raise ValueError(
            "Empty response body. This usually means wrong form encoding, missing session/cookie, "
            "or the endpoint is not directly callable from this context. "
            "Try browser_capture_requests first, then switch strategy."
        )
    return text


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
