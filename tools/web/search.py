from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urlencode, urlparse

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class SearchConfig(BaseModel):
    max_results: int = Field(default=8, ge=1, le=30)
    max_read_chars: int = Field(default=12000, ge=1, le=200000)
    timeout_seconds: float = Field(default=20, gt=0, le=120)


class SearchArgs(BaseModel):
    query: str = Field(min_length=1)


def execute(args: SearchArgs, config: SearchConfig) -> list[dict[str, str]]:
    import httpx

    url = "https://duckduckgo.com/html/?" + urlencode({"q": args.query})
    response = httpx.get(url, timeout=config.timeout_seconds, follow_redirects=True)
    response.raise_for_status()
    html = response.text[: config.max_read_chars]
    results = _parse_duckduckgo_html(html)
    return results[: config.max_results]


def _parse_duckduckgo_html(html: str) -> list[dict[str, str]]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        output = []
        for anchor in soup.select("a.result__a"):
            title = anchor.get_text(" ", strip=True)
            href = _unwrap_duckduckgo_url(anchor.get("href", ""))
            if title and href:
                snippet_node = anchor.find_parent("div", class_="result")
                snippet = ""
                if snippet_node is not None:
                    snippet_el = snippet_node.select_one(".result__snippet")
                    if snippet_el is not None:
                        snippet = snippet_el.get_text(" ", strip=True)
                output.append({"title": title, "url": href, "snippet": snippet})
        if output:
            return output
    except Exception:
        pass

    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    output = []
    for match in pattern.finditer(html):
        title = re.sub(r"<.*?>", "", match.group("title"))
        output.append(
            {
                "title": unescape(title).strip(),
                "url": _unwrap_duckduckgo_url(unescape(match.group("href"))),
                "snippet": "",
            }
        )
    return [item for item in output if item["title"] and item["url"]]


def _unwrap_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        return uddg or url
    return url


def build_pydantic_tool(config: SearchConfig):
    def search(query: str) -> list[dict[str, str]] | str:
        """Search the web and return a short result list."""
        try:
            return execute(SearchArgs.model_validate({"query": query}), config)
        except Exception as exc:
            return f"TOOL_ERROR web.search failed for {query}: {type(exc).__name__}: {exc}"

    return search


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web.search",
        description="Search the web and return a short result list.",
        config_model=SearchConfig,
        args_model=SearchArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )

