from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from tool_call import ToolSpec


class ExtractLinksConfig(BaseModel):
    max_links: int = Field(default=50, ge=1, le=1000)
    timeout_seconds: float = Field(default=20, gt=0, le=120)
    follow_redirects: bool = True
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    same_host_only: bool = False


class ExtractLinksArgs(BaseModel):
    url: str = Field(min_length=1)


def execute(args: ExtractLinksArgs, config: ExtractLinksConfig) -> list[str]:
    import httpx

    source = urlparse(args.url)
    if source.scheme.lower() not in config.allowed_schemes:
        allowed = ", ".join(config.allowed_schemes)
        raise ValueError(f"URL scheme not allowed: {source.scheme}. Allowed schemes: {allowed}")

    response = httpx.get(
        args.url,
        timeout=config.timeout_seconds,
        follow_redirects=config.follow_redirects,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        link = urljoin(args.url, anchor["href"])
        parsed = urlparse(link)
        if parsed.scheme.lower() not in config.allowed_schemes:
            continue
        if config.same_host_only and parsed.netloc != source.netloc:
            continue
        normalized = parsed.geturl()
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
        if len(links) >= config.max_links:
            break
    return links


def build_pydantic_tool(config: ExtractLinksConfig):
    def extract_links(url: str) -> list[str] | str:
        """Fetch a page and return links found in anchor tags."""
        try:
            args = ExtractLinksArgs.model_validate({"url": url})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR web.extract_links failed for {url}: {type(exc).__name__}: {exc}"

    return extract_links


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web.extract_links",
        description="Fetch a page and return links found in anchor tags.",
        config_model=ExtractLinksConfig,
        args_model=ExtractLinksArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
