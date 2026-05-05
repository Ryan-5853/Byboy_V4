from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from .exceptions import ToolNotFoundError
from .schemas import ToolSpec


class ToolRegistry:
    """Registry for all tools discovered from the project `tools` package."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            available = ", ".join(self.names()) or "<none>"
            raise ToolNotFoundError(
                f"Unknown tool: {name}. Available tools: {available}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    def load_package(self, package_name: str = "tools") -> None:
        package = importlib.import_module(package_name)
        for module_info in pkgutil.walk_packages(package.__path__, f"{package_name}."):
            module = importlib.import_module(module_info.name)
            self.load_module(module)

    def load_module(self, module: ModuleType) -> None:
        factory = getattr(module, "get_tool_spec", None)
        if callable(factory):
            self.register(factory())
            return
        spec = getattr(module, "TOOL_SPEC", None)
        if isinstance(spec, ToolSpec):
            self.register(spec)


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.load_package("tools")
    return registry
