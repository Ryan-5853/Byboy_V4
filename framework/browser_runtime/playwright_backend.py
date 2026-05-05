from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from time import time
import json
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup

_BROWSER_SESSIONS: dict[str, dict[str, Any]] = {}
_MAX_BROWSER_SESSIONS = 64


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run `pip install playwright` and "
            "`python3 -m playwright install chromium`, or install from framework/requirements.txt."
        ) from exc
    return sync_playwright


def _check_url_allowed(url: str, allowed_schemes: Iterable[str], allowed_domains: Iterable[str]) -> None:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {item.lower() for item in allowed_schemes}:
        allowed = ", ".join(allowed_schemes)
        raise ValueError(f"URL scheme not allowed: {scheme}. Allowed schemes: {allowed}")
    domain_patterns = [item.lower() for item in allowed_domains]
    if domain_patterns and not any(fnmatch(host, pattern) for pattern in domain_patterns):
        allowed = ", ".join(domain_patterns)
        raise ValueError(f"URL domain not allowed: {host}. Allowed domains: {allowed}")


def _extract_text_and_links(html: str, base_url: str, max_links: int) -> tuple[str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    links: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = urljoin(base_url, str(tag["href"]).strip())
        if not href or href in seen:
            continue
        seen.add(href)
        links.append(href)
        if len(links) >= max_links:
            break
    return text, links


def _goto_with_fallback(page, url: str, wait_until: str, timeout_ms: int):
    """Navigate with a pragmatic fallback for pages that never become idle."""

    try:
        response = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        return response, wait_until
    except Exception as exc:
        if wait_until != "networkidle":
            raise
        message = str(exc).lower()
        if "timeout" not in message:
            raise
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return response, "domcontentloaded"


def _store_browser_session(
    *,
    storage_state: dict[str, Any],
    browser_name: str,
    headless: bool,
    timeout_seconds: float,
    viewport_width: int,
    viewport_height: int,
    user_agent: str | None,
    locale: str | None,
    block_resource_types: list[str],
) -> str:
    session_id = uuid4().hex
    _BROWSER_SESSIONS[session_id] = {
        "storage_state": storage_state,
        "browser_name": browser_name,
        "headless": headless,
        "timeout_seconds": timeout_seconds,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height,
        "user_agent": user_agent,
        "locale": locale,
        "block_resource_types": block_resource_types,
        "created_at": time(),
    }
    if len(_BROWSER_SESSIONS) > _MAX_BROWSER_SESSIONS:
        oldest = sorted(_BROWSER_SESSIONS.items(), key=lambda pair: pair[1]["created_at"])[
            0
        ][0]
        _BROWSER_SESSIONS.pop(oldest, None)
    return session_id


def _get_browser_session(session_id: str) -> dict[str, Any]:
    session = _BROWSER_SESSIONS.get(session_id)
    if session is None:
        raise ValueError(
            f"Unknown session_id: {session_id}. "
            "Use browser.capture_xhr first to create a reusable browser session."
        )
    return session


def export_browser_session(session_id: str) -> dict[str, Any]:
    session = _get_browser_session(session_id)
    return {
        "browser_name": session["browser_name"],
        "headless": bool(session["headless"]),
        "timeout_seconds": float(session["timeout_seconds"]),
        "viewport_width": int(session["viewport_width"]),
        "viewport_height": int(session["viewport_height"]),
        "user_agent": session.get("user_agent"),
        "locale": session.get("locale"),
        "block_resource_types": list(session.get("block_resource_types", [])),
        "storage_state": session["storage_state"],
    }


def import_browser_session(payload: dict[str, Any]) -> str:
    required = [
        "browser_name",
        "headless",
        "timeout_seconds",
        "viewport_width",
        "viewport_height",
        "storage_state",
    ]
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"Invalid session payload, missing keys: {', '.join(missing)}")
    # Ensure payload is JSON-safe and normalized.
    normalized = json.loads(json.dumps(payload))
    return _store_browser_session(
        storage_state=normalized["storage_state"],
        browser_name=str(normalized["browser_name"]),
        headless=bool(normalized["headless"]),
        timeout_seconds=float(normalized["timeout_seconds"]),
        viewport_width=int(normalized["viewport_width"]),
        viewport_height=int(normalized["viewport_height"]),
        user_agent=normalized.get("user_agent"),
        locale=normalized.get("locale"),
        block_resource_types=list(normalized.get("block_resource_types", [])),
    )


def render_page_with_playwright(
    *,
    url: str,
    browser_name: str,
    headless: bool,
    timeout_seconds: float,
    wait_until: str,
    wait_for_selector: str | None,
    viewport_width: int,
    viewport_height: int,
    user_agent: str | None,
    locale: str | None,
    block_resource_types: list[str],
    max_html_chars: int,
    max_text_chars: int,
    max_links: int,
    allowed_schemes: list[str],
    allowed_domains: list[str],
) -> dict[str, object]:
    _check_url_allowed(url, allowed_schemes, allowed_domains)
    sync_playwright = _require_playwright()
    timeout_ms = int(timeout_seconds * 1000)

    with sync_playwright() as p:
        browser_launcher = getattr(p, browser_name, None)
        if browser_launcher is None:
            raise ValueError(f"Unsupported browser_name: {browser_name}")
        browser = browser_launcher.launch(headless=headless)
        try:
            context_kwargs = {
                "viewport": {"width": viewport_width, "height": viewport_height},
            }
            if user_agent:
                context_kwargs["user_agent"] = user_agent
            if locale:
                context_kwargs["locale"] = locale
            context = browser.new_context(**context_kwargs)
            try:
                page = context.new_page()
                if block_resource_types:
                    blocked = set(block_resource_types)

                    def route_handler(route):
                        if route.request.resource_type in blocked:
                            route.abort()
                        else:
                            route.continue_()

                    page.route("**/*", route_handler)

                response, effective_wait_until = _goto_with_fallback(
                    page, url, wait_until, timeout_ms
                )
                if wait_for_selector:
                    page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
                html = page.content()
                title = page.title()
                final_url = page.url
                text, links = _extract_text_and_links(html, final_url, max_links=max_links)
                return {
                    "url": url,
                    "final_url": final_url,
                    "status": response.status if response else None,
                    "wait_until": effective_wait_until,
                    "title": title,
                    "text": text[:max_text_chars],
                    "html": html[:max_html_chars],
                    "links": links,
                    "text_truncated": len(text) > max_text_chars,
                    "html_truncated": len(html) > max_html_chars,
                }
            finally:
                context.close()
        finally:
            browser.close()


def screenshot_page_with_playwright(
    *,
    url: str,
    output_path: Path,
    browser_name: str,
    headless: bool,
    timeout_seconds: float,
    wait_until: str,
    wait_for_selector: str | None,
    viewport_width: int,
    viewport_height: int,
    user_agent: str | None,
    locale: str | None,
    block_resource_types: list[str],
    full_page: bool,
    image_type: str,
    image_quality: int | None,
    max_image_bytes: int,
    allowed_schemes: list[str],
    allowed_domains: list[str],
) -> dict[str, object]:
    _check_url_allowed(url, allowed_schemes, allowed_domains)
    sync_playwright = _require_playwright()
    timeout_ms = int(timeout_seconds * 1000)

    with sync_playwright() as p:
        browser_launcher = getattr(p, browser_name, None)
        if browser_launcher is None:
            raise ValueError(f"Unsupported browser_name: {browser_name}")
        browser = browser_launcher.launch(headless=headless)
        try:
            context_kwargs = {
                "viewport": {"width": viewport_width, "height": viewport_height},
            }
            if user_agent:
                context_kwargs["user_agent"] = user_agent
            if locale:
                context_kwargs["locale"] = locale
            context = browser.new_context(**context_kwargs)
            try:
                page = context.new_page()
                if block_resource_types:
                    blocked = set(block_resource_types)

                    def route_handler(route):
                        if route.request.resource_type in blocked:
                            route.abort()
                        else:
                            route.continue_()

                    page.route("**/*", route_handler)

                response, effective_wait_until = _goto_with_fallback(
                    page, url, wait_until, timeout_ms
                )
                if wait_for_selector:
                    page.wait_for_selector(wait_for_selector, timeout=timeout_ms)

                screenshot_kwargs: dict[str, object] = {
                    "full_page": full_page,
                    "type": image_type,
                }
                if image_type == "jpeg" and image_quality is not None:
                    screenshot_kwargs["quality"] = image_quality
                content = page.screenshot(**screenshot_kwargs)
                if len(content) > max_image_bytes:
                    raise ValueError(
                        f"Screenshot exceeds max_image_bytes: {len(content)} > {max_image_bytes}"
                    )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(content)
                return {
                    "url": url,
                    "final_url": page.url,
                    "status": response.status if response else None,
                    "wait_until": effective_wait_until,
                    "path": output_path.name,
                    "bytes_written": len(content),
                    "image_type": image_type,
                }
            finally:
                context.close()
        finally:
            browser.close()


def capture_requests_with_playwright(
    *,
    url: str,
    browser_name: str,
    headless: bool,
    timeout_seconds: float,
    wait_until: str,
    wait_for_selector: str | None,
    viewport_width: int,
    viewport_height: int,
    user_agent: str | None,
    locale: str | None,
    block_resource_types: list[str],
    allowed_resource_types: list[str],
    include_response_body: bool,
    max_response_body_chars: int,
    max_entries: int,
    allowed_schemes: list[str],
    allowed_domains: list[str],
) -> dict[str, object]:
    _check_url_allowed(url, allowed_schemes, allowed_domains)
    sync_playwright = _require_playwright()
    timeout_ms = int(timeout_seconds * 1000)
    entries: list[dict[str, object]] = []

    def should_capture(resource_type: str) -> bool:
        if not allowed_resource_types:
            return True
        return resource_type in set(allowed_resource_types)

    with sync_playwright() as p:
        browser_launcher = getattr(p, browser_name, None)
        if browser_launcher is None:
            raise ValueError(f"Unsupported browser_name: {browser_name}")
        browser = browser_launcher.launch(headless=headless)
        try:
            context_kwargs = {
                "viewport": {"width": viewport_width, "height": viewport_height},
            }
            if user_agent:
                context_kwargs["user_agent"] = user_agent
            if locale:
                context_kwargs["locale"] = locale
            context = browser.new_context(**context_kwargs)
            try:
                page = context.new_page()
                if block_resource_types:
                    blocked = set(block_resource_types)

                    def route_handler(route):
                        if route.request.resource_type in blocked:
                            route.abort()
                        else:
                            route.continue_()

                    page.route("**/*", route_handler)

                def on_response(response):
                    if len(entries) >= max_entries:
                        return
                    request = response.request
                    rtype = request.resource_type
                    if not should_capture(rtype):
                        return
                    item: dict[str, object] = {
                        "resource_type": rtype,
                        "method": request.method,
                        "url": request.url,
                        "status": response.status,
                        "ok": response.ok,
                        "content_type": response.headers.get("content-type", ""),
                        "request_headers": request.headers,
                        "request_post_data": request.post_data or "",
                    }
                    if include_response_body:
                        try:
                            body = response.text()
                            item["response_body"] = body[:max_response_body_chars]
                            item["response_body_truncated"] = len(body) > max_response_body_chars
                        except Exception as exc:
                            item["response_body_error"] = f"{type(exc).__name__}: {exc}"
                    entries.append(item)

                page.on("response", on_response)

                response, effective_wait_until = _goto_with_fallback(
                    page, url, wait_until, timeout_ms
                )
                if wait_for_selector:
                    page.wait_for_selector(wait_for_selector, timeout=timeout_ms)

                return {
                    "url": url,
                    "final_url": page.url,
                    "status": response.status if response else None,
                    "wait_until": effective_wait_until,
                    "requests": entries,
                    "captured_count": len(entries),
                    "max_entries": max_entries,
                }
            finally:
                context.close()
        finally:
            browser.close()


def capture_xhr_with_playwright(
    *,
    url: str,
    browser_name: str,
    headless: bool,
    timeout_seconds: float,
    wait_until: str,
    wait_for_selector: str | None,
    viewport_width: int,
    viewport_height: int,
    user_agent: str | None,
    locale: str | None,
    block_resource_types: list[str],
    include_response_body: bool,
    max_response_body_chars: int,
    max_entries: int,
    allowed_schemes: list[str],
    allowed_domains: list[str],
) -> dict[str, object]:
    captured = capture_requests_with_playwright(
        url=url,
        browser_name=browser_name,
        headless=headless,
        timeout_seconds=timeout_seconds,
        wait_until=wait_until,
        wait_for_selector=wait_for_selector,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        user_agent=user_agent,
        locale=locale,
        block_resource_types=block_resource_types,
        allowed_resource_types=["xhr", "fetch"],
        include_response_body=include_response_body,
        max_response_body_chars=max_response_body_chars,
        max_entries=max_entries,
        allowed_schemes=allowed_schemes,
        allowed_domains=allowed_domains,
    )
    sync_playwright = _require_playwright()
    timeout_ms = int(timeout_seconds * 1000)
    with sync_playwright() as p:
        browser_launcher = getattr(p, browser_name, None)
        if browser_launcher is None:
            raise ValueError(f"Unsupported browser_name: {browser_name}")
        browser = browser_launcher.launch(headless=headless)
        try:
            context_kwargs = {"viewport": {"width": viewport_width, "height": viewport_height}}
            if user_agent:
                context_kwargs["user_agent"] = user_agent
            if locale:
                context_kwargs["locale"] = locale
            context = browser.new_context(**context_kwargs)
            try:
                page = context.new_page()
                if block_resource_types:
                    blocked = set(block_resource_types)

                    def route_handler(route):
                        if route.request.resource_type in blocked:
                            route.abort()
                        else:
                            route.continue_()

                    page.route("**/*", route_handler)
                _goto_with_fallback(page, url, wait_until, timeout_ms)
                if wait_for_selector:
                    page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
                storage_state = context.storage_state()
            finally:
                context.close()
        finally:
            browser.close()
    session_id = _store_browser_session(
        storage_state=storage_state,
        browser_name=browser_name,
        headless=headless,
        timeout_seconds=timeout_seconds,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        user_agent=user_agent,
        locale=locale,
        block_resource_types=block_resource_types,
    )
    captured["session_id"] = session_id
    return captured


def replay_api_with_playwright(
    *,
    session_id: str,
    url: str,
    method: str,
    data: dict[str, Any] | str | None,
    headers: dict[str, str] | None,
    timeout_seconds: float,
    max_response_body_chars: int,
    allowed_schemes: list[str],
    allowed_domains: list[str],
) -> dict[str, object]:
    _check_url_allowed(url, allowed_schemes, allowed_domains)
    session = _get_browser_session(session_id)
    sync_playwright = _require_playwright()
    timeout_ms = int(timeout_seconds * 1000)
    method_upper = method.upper()
    hdrs = headers or {}
    with sync_playwright() as p:
        browser_launcher = getattr(p, str(session["browser_name"]), None)
        if browser_launcher is None:
            raise ValueError(f"Unsupported browser_name in session: {session['browser_name']}")
        browser = browser_launcher.launch(headless=bool(session["headless"]))
        try:
            context_kwargs = {
                "storage_state": session["storage_state"],
                "viewport": {
                    "width": int(session["viewport_width"]),
                    "height": int(session["viewport_height"]),
                },
            }
            if session.get("user_agent"):
                context_kwargs["user_agent"] = session["user_agent"]
            if session.get("locale"):
                context_kwargs["locale"] = session["locale"]
            context = browser.new_context(**context_kwargs)
            try:
                req = context.request
                request_kwargs: dict[str, Any] = {
                    "headers": hdrs or None,
                    "timeout": timeout_ms,
                }
                if method_upper in {"POST", "PUT", "PATCH", "DELETE"} and data is not None:
                    ctype = str(hdrs.get("Content-Type", "")).lower()
                    if isinstance(data, dict):
                        if "application/json" in ctype:
                            request_kwargs["data"] = data
                        else:
                            request_kwargs["form"] = data
                    else:
                        request_kwargs["data"] = data
                response = req.fetch(url, method=method_upper, **request_kwargs)
                body = response.text()
                return {
                    "session_id": session_id,
                    "method": method_upper,
                    "url": url,
                    "status": response.status,
                    "ok": response.ok,
                    "content_type": response.headers.get("content-type", ""),
                    "response_body": body[:max_response_body_chars],
                    "response_body_truncated": len(body) > max_response_body_chars,
                }
            finally:
                context.close()
        finally:
            browser.close()
