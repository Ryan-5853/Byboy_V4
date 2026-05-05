from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, Field


class ConfiguredTool(BaseModel):
    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    tool_name: str
    output: Any


ToolExecutor = Callable[[BaseModel, BaseModel], Any]
PydanticToolFactory = Callable[[BaseModel], Callable[..., Any]]


class EmptyToolConfig(BaseModel):
    pass


class EmptyToolArgs(BaseModel):
    pass


class ToolSpec(BaseModel):
    """Declarative contract every tool module must expose."""

    name: str
    description: str
    config_model: type[BaseModel] = EmptyToolConfig
    args_model: type[BaseModel] = EmptyToolArgs
    execute: ToolExecutor
    pydantic_tool_factory: PydanticToolFactory

    model_config = {"arbitrary_types_allowed": True}

    def build_pydantic_callable(self, config: BaseModel | Mapping[str, Any]) -> Callable[..., Any]:
        if isinstance(config, BaseModel):
            validated_config = config
        else:
            validated_config = self.config_model.model_validate(config)
        return self.pydantic_tool_factory(validated_config)
