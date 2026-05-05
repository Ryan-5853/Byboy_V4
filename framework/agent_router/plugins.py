from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic_ai import Tool

from tool_call import ConfiguredTool, ToolCallManager, ToolRegistry, build_default_tool_registry

from .schemas import ToolConfig


class PluginRegistry:
    """Compatibility adapter from agent_router tool config to tool_call manager."""

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self.tool_registry = tool_registry or build_default_tool_registry()

    def resolve(self, configured_tools: Iterable[ToolConfig], *, logger: Any = None) -> list[Tool[Any]]:
        manager = ToolCallManager(
            [
                ConfiguredTool(name=tool.name, config=tool.config)
                for tool in configured_tools
            ],
            registry=self.tool_registry,
            logger=logger,
        )
        return manager.as_pydantic_tools()

    def names(self) -> list[str]:
        return self.tool_registry.names()


def build_default_registry() -> PluginRegistry:
    return PluginRegistry()
