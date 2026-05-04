from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import wraps
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
            self._log("tool_execute_start", name, args=args, kwargs=kwargs)
            result = function(*args, **kwargs)
            self._log("tool_execute_end", name, result=result)
            return result

        return wrapped

    def _log(self, event: str, name: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.log(event, name, **fields)
