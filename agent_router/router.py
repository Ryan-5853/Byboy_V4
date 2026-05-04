from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, create_model
from pydantic_ai import Agent
from pydantic_ai.exceptions import (
    AgentRunError,
    IncompleteToolCall,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.usage import UsageLimits

import json

from context_manage import ContextManageCapability, ContextManager
from llm_select import LLMSelector

from .config_loader import load_config, load_prompt
from .plugins import PluginRegistry, build_default_registry
from .runtime_logging import RuntimeLogger
from .schemas import RouterError, RouterRequest, RouterResult, SubAgentConfig


class AgentRouter:
    """Creates one pydantic-ai subagent per workflow task."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        registry: PluginRegistry | None = None,
        llm_selector: LLMSelector | None = None,
        llm_config_file: str | Path | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.registry = registry or build_default_registry()
        self.llm_selector = llm_selector or LLMSelector(config_file=llm_config_file)
        self.llm_config_file = llm_config_file

    def run_sync(self, request: RouterRequest) -> RouterResult:
        config = load_config(request.config_file, self.base_dir)
        prompt = load_prompt(request.prompt_file, self.base_dir)
        if request.variables:
            prompt = prompt.format(**request.variables)

        agent = self._build_agent(config)
        model_name = config.model_alias or self.llm_selector.config.default_alias or ""
        enabled_tools = [tool.name for tool in config.tools]
        try:
            result = agent.run_sync(
                prompt,
                usage_limits=self._build_usage_limits(config),
            )
            return RouterResult.from_agent_result(
                result,
                agent_name=config.agent.name,
                model_name=model_name,
                enabled_tools=enabled_tools,
            )
        except Exception as exc:
            if request.raise_on_error:
                raise
            return RouterResult.from_error(
                _classify_agent_error(exc),
                agent_name=config.agent.name,
                model_name=model_name,
                enabled_tools=enabled_tools,
            )

    def _build_agent(self, config: SubAgentConfig) -> Agent[Any, Any]:
        model = self.llm_selector.get(config.model_alias)
        logger = RuntimeLogger(
            enabled=config.agent.stream_events,
            max_preview_chars=config.agent.log_preview_chars,
            log_arg_deltas=config.agent.log_arg_deltas,
            log_text_deltas=config.agent.log_text_deltas,
            log_thinking=config.agent.log_thinking,
        )
        tools = self.registry.resolve(config.tools, logger=logger if config.agent.log_tool_results else None)
        output_type, json_instruction = self._resolve_output_mode(config)
        system_prompt = config.agent.system_prompt
        if json_instruction:
            if isinstance(system_prompt, list):
                system_prompt = "\n".join(system_prompt)
            system_prompt = system_prompt + "\n\n" + json_instruction
        context_manager = ContextManager(
            config.context_management,
            llm_selector=self.llm_selector,
            llm_config_file=str(self.llm_config_file) if self.llm_config_file else None,
        )
        capabilities = []
        if config.context_management.enabled:
            capabilities.append(ContextManageCapability(context_manager))
        return Agent(
            model=model,
            output_type=output_type,
            instructions=config.agent.instructions,
            system_prompt=system_prompt,
            name=config.agent.name,
            retries=config.agent.retries,
            output_retries=config.agent.output_retries,
            tools=tools,
            model_settings=config.model_settings or None,
            tool_timeout=config.agent.tool_timeout,
            capabilities=capabilities,
            event_stream_handler=logger.event_stream_handler if config.agent.stream_events else None,
        )

    def _build_usage_limits(self, config: SubAgentConfig) -> UsageLimits:
        return UsageLimits(**config.usage_limits.model_dump(exclude_none=True))

    def _resolve_output_mode(self, config: SubAgentConfig) -> tuple[Any, str]:
        """Return (output_type, extra_json_instruction).
        When output_schema is set, we use str output type to let the model
        write free-form JSON, then parse loosely after the run.
        This avoids pydantic strict validation failures that small models
        often hit during structured generation."""
        schema = config.agent.output_schema
        if not schema:
            return str, ""
        lines = [
            "你必须输出一个合法的 JSON 对象，包含以下字段："
        ]
        for k, v in schema.items():
            lines.append(f"  - {k}: {v}")
        lines.append(
            "不要添加额外字段。先确认所有字段都有值，再输出。"
            "不要用 markdown 代码块包裹，直接输出 JSON。"
        )
        return str, "\n".join(lines)


def dump_config_schema() -> dict[str, Any]:
    return SubAgentConfig.model_json_schema()


def _classify_agent_error(exc: Exception) -> RouterError:
    message = str(exc)
    details: dict[str, Any] = {}
    category = "agent_run_error"
    recoverable = True

    if isinstance(exc, UsageLimitExceeded):
        category = "usage_limit_exceeded"
    elif isinstance(exc, IncompleteToolCall):
        category = "context_or_output_limit"
    elif isinstance(exc, ModelHTTPError):
        category = _classify_model_http_error(exc)
        details = {
            "status_code": exc.status_code,
            "model_name": exc.model_name,
            "body": exc.body,
        }
    elif isinstance(exc, ModelAPIError):
        category = "model_api_error"
        details = {"model_name": exc.model_name}
    elif isinstance(exc, UnexpectedModelBehavior):
        category = "unexpected_model_behavior"
        details = {"body": exc.body}
    elif isinstance(exc, AgentRunError):
        category = "agent_run_error"
    else:
        category = "unexpected_error"

    if _looks_like_context_overflow(message) or _looks_like_context_overflow(str(details)):
        category = "context_overflow"

    return RouterError(
        type=type(exc).__name__,
        message=message,
        category=category,
        recoverable=recoverable,
        details=details,
    )


def _classify_model_http_error(exc: ModelHTTPError) -> str:
    if exc.status_code in {400, 413, 422} and _looks_like_context_overflow(str(exc.body)):
        return "context_overflow"
    return "model_http_error"


def _looks_like_context_overflow(text: str) -> bool:
    normalized = text.lower()
    markers = [
        "context length",
        "context_length",
        "maximum context",
        "max context",
        "context window",
        "token limit",
        "too many tokens",
        "maximum number of tokens",
        "input is too long",
        "prompt is too long",
        "request too large",
    ]
    return any(marker in normalized for marker in markers)
