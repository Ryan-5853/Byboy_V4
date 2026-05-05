from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import wraps
import json
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
        return (
            f"TOOL_ERROR {name}: 你的上一次toolcall失败了/被拦截了，因为 {detail}。"
            "请你修改参数后重新提交toolcall，或者改用其他方式完成同一任务。"
        )

    def _log(self, event: str, name: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.log(event, name, **fields)
