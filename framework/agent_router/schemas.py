from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from context_manage import ContextManageConfig


class RouterRequest(BaseModel):
    prompt_file: Path
    config_file: Path
    variables: dict[str, str] = Field(default_factory=dict)
    raise_on_error: bool = False


class AgentOptions(BaseModel):
    name: str = "subagent"
    instructions: str | None = None
    system_prompt: str | list[str] = ""
    retries: int = 1
    output_retries: int | None = None
    tool_timeout: float | None = None
    output_schema: dict[str, str] | None = None
    stream_events: bool = True
    log_tool_results: bool = True
    log_preview_chars: int = Field(default=1200, ge=0)
    log_arg_deltas: bool = False
    log_text_deltas: bool = False
    log_thinking: bool = True
    persist_logs: bool = True
    log_dir: str | None = None
    persist_full_payload: bool = False
    persist_max_chars: int = Field(default=4000, ge=200, le=200000)


class UsageLimitOptions(BaseModel):
    request_limit: int | None = 50
    tool_calls_limit: int | None = None
    input_tokens_limit: int | None = None
    output_tokens_limit: int | None = None
    total_tokens_limit: int | None = None
    count_tokens_before_request: bool = False
    request_tokens_limit: int | None = None
    response_tokens_limit: int | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_workflow_names(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        aliases = {
            "max_requests": "request_limit",
            "max_tool_calls": "tool_calls_limit",
            "max_input_tokens": "input_tokens_limit",
            "max_output_tokens": "output_tokens_limit",
            "max_total_tokens": "total_tokens_limit",
        }
        normalized = dict(value)
        for source, target in aliases.items():
            if source in normalized and target not in normalized:
                normalized[target] = normalized[source]
        unlimited_markers = {"", "none", "null", "nil", "unlimited", "false"}
        nullable_fields = {
            "request_limit",
            "tool_calls_limit",
            "input_tokens_limit",
            "output_tokens_limit",
            "total_tokens_limit",
            "request_tokens_limit",
            "response_tokens_limit",
        }
        for field_name in nullable_fields:
            item = normalized.get(field_name)
            if isinstance(item, str) and item.strip().lower() in unlimited_markers:
                normalized[field_name] = None
        return normalized


class ToolConfig(BaseModel):
    name: str
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_short_forms(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        if isinstance(value, dict):
            if "name" in value:
                normalized = dict(value)
                if "params" in normalized and "config" not in normalized:
                    normalized["config"] = normalized["params"]
                if "options" in normalized and "config" not in normalized:
                    normalized["config"] = normalized["options"]
                return normalized
            if len(value) == 1:
                name, config = next(iter(value.items()))
                return {"name": name, "config": config or {}}
        return value


class SubAgentConfig(BaseModel):
    agent: AgentOptions = Field(default_factory=AgentOptions)
    model_alias: str | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)
    usage_limits: UsageLimitOptions = Field(default_factory=UsageLimitOptions)
    context_management: ContextManageConfig = Field(default_factory=ContextManageConfig)
    tools: list[ToolConfig] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_allowed_plugins(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "allowed_plugins" in normalized and "tools" not in normalized:
            normalized["tools"] = normalized["allowed_plugins"]
        if "plugins" in normalized and "tools" not in normalized:
            normalized["tools"] = normalized["plugins"]
        if "model" in normalized and "model_alias" not in normalized:
            model_value = normalized["model"]
            if isinstance(model_value, str):
                normalized["model_alias"] = model_value
            elif isinstance(model_value, dict) and "alias" in model_value:
                normalized["model_alias"] = model_value["alias"]
            else:
                raise ValueError(
                    "agent_router config only accepts model_alias. "
                    "Backend model details belong in framework/llm_select/models.yaml."
                )
        return normalized


class RouterError(BaseModel):
    type: str
    message: str
    category: str = "agent_run_error"
    recoverable: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class RouterResult(BaseModel):
    agent_name: str
    model_name: str
    enabled_tools: list[str]
    output: Any
    usage: dict[str, Any] | None = None
    status: str = "ok"
    error: RouterError | None = None

    @classmethod
    def from_agent_result(
        cls,
        result: Any,
        *,
        agent_name: str,
        model_name: str,
        enabled_tools: list[str],
    ) -> "RouterResult":
        output = result.output
        if isinstance(output, BaseModel):
            output = output.model_dump()
        # Loose JSON parsing for models that write str output with JSON
        if isinstance(output, str):
            stripped = output.strip()
            # Remove markdown code block fences if present
            if stripped.startswith("```"):
                for fence in ("```json", "```"):
                    if stripped.startswith(fence):
                        stripped = stripped[len(fence):].strip()
                if stripped.endswith("```"):
                    stripped = stripped[:-3].strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        output = parsed
                except json.JSONDecodeError:
                    pass

        usage = None
        usage_value = getattr(result, "usage", None)
        if callable(usage_value):
            usage_value = usage_value()
        if usage_value is not None:
            if hasattr(usage_value, "model_dump"):
                usage = usage_value.model_dump()
            elif hasattr(usage_value, "__dict__"):
                usage = dict(usage_value.__dict__)

        return cls(
            agent_name=agent_name,
            model_name=model_name,
            enabled_tools=enabled_tools,
            output=output,
            usage=usage,
        )

    @classmethod
    def from_error(
        cls,
        error: RouterError,
        *,
        agent_name: str,
        model_name: str,
        enabled_tools: list[str],
        usage: dict[str, Any] | None = None,
    ) -> "RouterResult":
        return cls(
            agent_name=agent_name,
            model_name=model_name,
            enabled_tools=enabled_tools,
            output=None,
            usage=usage,
            status="error",
            error=error,
        )
