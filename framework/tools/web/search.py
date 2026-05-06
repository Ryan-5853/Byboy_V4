from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from html import unescape
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from collections import deque
from typing import Literal

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class SearchConfig(BaseModel):
    max_results: int = Field(default=8, ge=1, le=30)
    max_read_chars: int = Field(default=12000, ge=1, le=200000)
    timeout_seconds: float = Field(default=20, gt=0, le=120)
    backend: Literal["auto", "searxng", "duckduckgo"] = "auto"
    searxng_url: str | None = None
    auto_start_searxng: bool = True


class SearchArgs(BaseModel):
    query: str = Field(min_length=1)


_RECENT_EMPTY_QUERIES: deque[str] = deque(maxlen=12)
_LAST_SEARXNG_START_ATTEMPT = 0.0
_SEARXNG_START_COOLDOWN_SECONDS = 60.0


def execute(args: SearchArgs, config: SearchConfig) -> list[dict[str, str]]:
    if config.backend in {"auto", "searxng"}:
        try:
            results = _execute_searxng(args, config)
            if results or config.backend == "searxng":
                return results[: config.max_results]
        except Exception:
            if config.backend == "searxng":
                raise

    return _execute_duckduckgo(args, config)


def _execute_searxng(args: SearchArgs, config: SearchConfig) -> list[dict[str, str]]:
    import httpx

    base_url = _discover_searxng_url(config)
    if not base_url and config.auto_start_searxng:
        _try_start_searxng_once()
        base_url = _discover_searxng_url(config)
    if not base_url:
        raise RuntimeError("SearXNG service not discovered")

    response = httpx.get(
        urljoin(base_url.rstrip("/") + "/", "search"),
        params={"q": args.query, "format": "json", "language": "auto", "safesearch": "0"},
        timeout=config.timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()
    data = response.json()
    raw_results = data.get("results", []) if isinstance(data, dict) else []
    output: list[dict[str, str]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()
        if title and url:
            output.append({"title": title, "url": url, "snippet": snippet})
        if len(output) >= config.max_results:
            break
    return output


def _execute_duckduckgo(args: SearchArgs, config: SearchConfig) -> list[dict[str, str]]:
    import httpx

    url = "https://duckduckgo.com/html/?" + urlencode({"q": args.query})
    response = httpx.get(url, timeout=config.timeout_seconds, follow_redirects=True)
    response.raise_for_status()
    html = response.text[: config.max_read_chars]
    results = _parse_duckduckgo_html(html)
    return results[: config.max_results]


def _discover_searxng_url(config: SearchConfig) -> str | None:
    import httpx

    candidates = []
    if config.searxng_url:
        candidates.append(config.searxng_url)
    env_url = os.environ.get("SEARXNG_URL") or os.environ.get("SEARXNG_BASE_URL")
    if env_url:
        candidates.append(env_url)
    candidates.extend(
        [
            "http://127.0.0.1:8080",
            "http://localhost:8080",
            "http://127.0.0.1:8888",
            "http://localhost:8888",
            "http://127.0.0.1:4000",
            "http://localhost:4000",
        ]
    )

    seen: set[str] = set()
    for raw in candidates:
        base_url = raw.rstrip("/")
        if not base_url or base_url in seen:
            continue
        seen.add(base_url)
        try:
            response = httpx.get(
                urljoin(base_url + "/", "search"),
                params={"q": "searxng", "format": "json"},
                timeout=min(2.0, config.timeout_seconds),
                follow_redirects=True,
            )
            if response.status_code == 200 and _looks_like_searxng_json(response):
                return base_url
        except Exception:
            continue
    return None


def _looks_like_searxng_json(response: object) -> bool:
    try:
        data = response.json()  # type: ignore[attr-defined]
    except Exception:
        return False
    return isinstance(data, dict) and isinstance(data.get("results"), list)


def _try_start_searxng_once() -> None:
    global _LAST_SEARXNG_START_ATTEMPT
    now = time.time()
    if now - _LAST_SEARXNG_START_ATTEMPT < _SEARXNG_START_COOLDOWN_SECONDS:
        return
    _LAST_SEARXNG_START_ATTEMPT = now

    for command in _searxng_start_commands():
        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except Exception:
            continue


def _searxng_start_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    if shutil.which("systemctl"):
        commands.append(["systemctl", "--user", "start", "searxng"])
        commands.append(["systemctl", "start", "searxng"])
    if shutil.which("docker"):
        for name in _docker_searxng_container_names():
            commands.append(["docker", "start", name])
    return commands


def _docker_searxng_container_names() -> list[str]:
    if not shutil.which("docker"):
        return []
    try:
        completed = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return []
    names = []
    for line in completed.stdout.splitlines():
        name = line.strip()
        if name and "searxng" in name.lower():
            names.append(name)
    if "searxng" not in names:
        names.append("searxng")
    return names


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
            normalized = SearchArgs.model_validate({"query": query})
            results = execute(normalized, config)
            if results:
                return results

            suggestion = (
                "web.search 返回空结果（0条）。这通常表示当前关键词路径不可达或过窄。"
                "请优先换信息源类型（例如 web_fetch_url / browser_render_page / browser_capture_requests），"
                "而不是继续同类关键词微调。"
            )
            if _is_similar_to_recent_empty(normalized.query):
                return (
                    "TOOL_ERROR web.search failed: "
                    "连续相似查询均为空结果。"
                    f"{suggestion}"
                )

            _RECENT_EMPTY_QUERIES.append(normalized.query)
            return (
                "TOOL_ERROR web.search failed: "
                f"{suggestion}"
            )
        except Exception as exc:
            return f"TOOL_ERROR web.search failed for {query}: {type(exc).__name__}: {exc}"

    return search


def _is_similar_to_recent_empty(query: str) -> bool:
    current = _tokenize_query(query)
    if not current:
        return False
    for previous in _RECENT_EMPTY_QUERIES:
        tokens = _tokenize_query(previous)
        if not tokens:
            continue
        overlap = len(current & tokens) / max(len(current | tokens), 1)
        if overlap >= 0.6:
            return True
    return False


def _tokenize_query(query: str) -> set[str]:
    parts = re.findall(r"[\w\u4e00-\u9fff]+", query.lower())
    return {p for p in parts if len(p) > 1}


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web.search",
        description="Search the web and return a short result list.",
        config_model=SearchConfig,
        args_model=SearchArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
