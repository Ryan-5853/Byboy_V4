from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.tools import RunContext

from .manager import ContextManager

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext


@dataclass
class ContextManageCapability(AbstractCapability[Any]):
    """Official pydantic-ai capability hook for context compaction."""

    manager: ContextManager

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        return await self.manager.compact_request_context(request_context)

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return "ContextManageCapability"
