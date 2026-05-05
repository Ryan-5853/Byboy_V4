from __future__ import annotations


class ToolCallError(Exception):
    """Base exception for tool routing and execution errors."""


class ToolNotFoundError(ToolCallError):
    """Raised when a requested tool does not exist in the registry."""


class ToolNotAllowedError(ToolCallError):
    """Raised when an agent tries to call a tool not enabled in its config."""


class ToolConfigError(ToolCallError):
    """Raised when configured hard limits for a tool are invalid."""


class ToolArgumentsError(ToolCallError):
    """Raised when runtime tool arguments do not match the tool contract."""
