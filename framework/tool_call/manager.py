from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import wraps
import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_ai import Tool

from .exceptions import (
    ToolArgumentsError,
    ToolConfigError,
    ToolNotAllowedError,
)
from .registry import ToolRegistry, build_default_tool_registry
from .schemas import ConfiguredTool, ToolCallRequest, ToolCallResult, ToolSpec


class ToolCallManager:
    """Per-agent tool gateway.

    A manager is created from one agent's tool config. It freezes each tool's
    hard limits, rejects unauthorized calls, validates runtime arguments, and
    dispatches to the underlying tool implementation.
    """

    def __init__(
        self,
        configured_tools: Iterable[ConfiguredTool],
        *,
        registry: ToolRegistry | None = None,
        logger: Any = None,
    ) -> None:
        self.registry = registry or build_default_tool_registry()
        self.logger = logger
        self._repeat_same_call_count: dict[str, int] = {}
        self._repeat_same_call_last_error: dict[str, str] = {}
        self._allowed: dict[str, tuple[ToolSpec, BaseModel]] = {}
        for configured_tool in configured_tools:
            if configured_tool.name in self._allowed:
                raise ToolConfigError(f"Tool configured more than once: {configured_tool.name}")
            spec = self.registry.get(configured_tool.name)
            try:
                config = spec.config_model.model_validate(configured_tool.config)
            except ValidationError as exc:
                raise ToolConfigError(
                    f"Invalid config for tool {configured_tool.name}: {exc}"
                ) from exc
            self._allowed[configured_tool.name] = (spec, config)

    def call(self, name: str, arguments: Mapping[str, Any]) -> ToolCallResult:
        if name not in self._allowed:
            raise ToolNotAllowedError(f"Tool is not enabled for this agent: {name}")

        spec, config = self._allowed[name]
        try:
            args = spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolArgumentsError(f"Invalid arguments for tool {name}: {exc}") from exc

        self._log("tool_execute_start", name, args=args.model_dump())
        output = spec.execute(args, config)
        self._log("tool_execute_end", name, result=output)
        return ToolCallResult(tool_name=name, output=output)

    def call_request(self, request: ToolCallRequest) -> ToolCallResult:
        return self.call(request.name, request.arguments)

    def as_pydantic_tools(self) -> list[Tool[Any]]:
        tools: list[Tool[Any]] = []
        for name, (spec, config) in self._allowed.items():
            function = spec.build_pydantic_callable(config)
            function = self._wrap_pydantic_callable(name, function)
            tools.append(
                Tool(
                    function,
                    name=name.replace(".", "_"),
                    description=spec.description,
                )
            )
        return tools

    def allowed_tool_names(self) -> list[str]:
        return sorted(self._allowed)

    def _wrap_pydantic_callable(self, name: str, function: Any) -> Any:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            call_key = self._build_call_key(name, args, kwargs)
            if self._repeat_same_call_count.get(call_key, 0) >= 3:
                last_error = self._repeat_same_call_last_error.get(call_key, "同参数调用重复失败")
                result = self._normalize_tool_error_message(
                    name,
                    f"TOOL_ERROR {name} failed: 检测到同一toolcall已连续失败多次（3+）: {last_error}",
                )
                self._log("tool_execute_error", name, error=result, repeated_call_guard=True)
                return result

            self._log("tool_execute_start", name, args=args, kwargs=kwargs)
            try:
                result = function(*args, **kwargs)
                if isinstance(result, str) and result.startswith("TOOL_ERROR"):
                    result = self._normalize_tool_error_message(name, result)
                    self._mark_call_error(call_key, result)
                else:
                    self._clear_call_error(call_key)
                self._log("tool_execute_end", name, result=result)
                return result
            except Exception as exc:
                result = self._normalize_tool_error_message(
                    name,
                    f"TOOL_ERROR {name} failed: {type(exc).__name__}: {exc}",
                )
                self._mark_call_error(call_key, result)
                self._log("tool_execute_error", name, error=result)
                return result

        return wrapped

    def _build_call_key(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        try:
            normalized = json.dumps(
                {"name": name, "args": args, "kwargs": kwargs},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        except Exception:
            normalized = f"{name}|{args!r}|{kwargs!r}"
        return normalized

    def _mark_call_error(self, call_key: str, error: str) -> None:
        self._repeat_same_call_count[call_key] = self._repeat_same_call_count.get(call_key, 0) + 1
        self._repeat_same_call_last_error[call_key] = error

    def _clear_call_error(self, call_key: str) -> None:
        self._repeat_same_call_count.pop(call_key, None)
        self._repeat_same_call_last_error.pop(call_key, None)

    def _normalize_tool_error_message(self, name: str, message: str) -> str:
        text = message.strip()
        prefix = f"TOOL_ERROR {name}"
        detail = text
        if text.startswith(prefix):
            detail = text[len(prefix):].strip()
        elif text.startswith("TOOL_ERROR"):
            detail = text[len("TOOL_ERROR"):].strip()
        if detail.startswith("failed"):
            detail = detail[len("failed"):].strip()
        if detail.startswith(":"):
            detail = detail[1:].strip()
        guidance = self._build_guidance(name, detail)
        return (
            f"TOOL_ERROR {name}: 你的上一次toolcall失败了/被拦截了，因为 {detail}。"
            f"{guidance}"
        )

    def _build_guidance(self, name: str, detail: str) -> str:
        lower = detail.lower()
        suggestions: list[str] = []

        # 1) URL / DNS / network
        if "err_name_not_resolved" in lower or "name_not_resolved" in lower:
            suggestions.extend(
                [
                    "域名无法解析，请先检查域名拼写是否正确",
                    "尝试改用备用网址/父域名入口页再提取可访问链接",
                ]
            )
        elif "timeout" in lower:
            suggestions.extend(
                [
                    "请求超时，请减少等待条件或切换 lighter 路径",
                    "可先用 fetch_url 获取静态内容，再决定是否用 browser 渲染",
                ]
            )
        elif "httpstatuserror" in lower and "404" in lower:
            suggestions.extend(
                [
                    "目标路径不存在，请核对 URL 路径或协议（http/https）",
                    "先访问站点入口页并提取真实子链接",
                ]
            )
        elif "httpstatuserror" in lower and "400" in lower:
            suggestions.extend(
                [
                    "请求参数格式不符合接口要求，请核对字段名与编码方式",
                    "若是 POST 接口，优先尝试 form 字段而不是 JSON 字符串",
                ]
            )
        elif "httpstatuserror" in lower and ("401" in lower or "403" in lower):
            suggestions.extend(
                [
                    "接口需要鉴权或会话，请改用浏览器抓取已渲染结果或先建立会话",
                    "避免在无 cookie 的情况下直接调用受保护接口",
                ]
            )

        # 2) payload / parsing
        if "jsondecodeerror" in lower:
            suggestions.extend(
                [
                    "返回体不是有效 JSON，请改用 web.fetch_url / browser.render_page 读取原始文本",
                    "确认响应 content-type 是否为 application/json",
                ]
            )
        if "semantic failure payload" in lower or "\"msg\": \"sql error\"" in lower or "\"msg\":\"sql error\"" in lower:
            suggestions.extend(
                [
                    "服务端已明确返回业务失败（如 sql error），请不要重复相同参数",
                    "优先改参数来源（如从页面 data-tid / 抓包请求参数）或改走渲染提取路径",
                ]
            )
        if "empty response body" in lower:
            suggestions.extend(
                [
                    "响应为空，通常是编码/会话问题，请调整 data 编码或切换浏览器路径",
                    "避免重复提交同一参数，先确认接口是否可直接调用",
                ]
            )

        # 3) local filesystem / command restrictions
        if "path is not allowed by configured globs" in lower:
            suggestions.extend(
                [
                    "当前路径不在白名单，请改写到允许目录（如 workspace/...）",
                    "或调整该 agent 的 tool 配置白名单后再执行",
                ]
            )
        if "permissionerror" in lower and "command not allowed" in lower:
            suggestions.extend(
                [
                    "命令不在 allowlist，请改用允许命令或对应内置 tool",
                ]
            )
        if "requires allow_write=true" in lower:
            suggestions.extend(
                [
                    "当前 tool 未开启写权限，请在 agent config 中开启 allow_write 后重试",
                ]
            )

        # 4) malformed POST common shape
        if re.search(r"suspicious form payload shape|encoded form fields into a dict key", lower):
            suggestions.extend(
                [
                    "你把整段 form 塞进了 dict 的 key；请改成 data='id=xxx&versionId='",
                    "或使用 data={'id':'xxx','versionId':''}",
                ]
            )

        # generic fallback
        if not suggestions:
            suggestions.extend(
                [
                    "请修改参数后重新提交 toolcall",
                    "若连续失败，请改用其他工具路径完成同一任务",
                ]
            )

        # de-dup while preserving order
        deduped: list[str] = []
        seen = set()
        for item in suggestions:
            if item not in seen:
                seen.add(item)
                deduped.append(item)

        numbered = "；".join(f"{i+1}) {s}" for i, s in enumerate(deduped[:3]))
        return f"建议：{numbered}。"

    def _log(self, event: str, name: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.log(event, name, **fields)
