from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ModelProvider = Literal["openai-compatible", "openai", "openai-chat", "known"]


class ModelConfig(BaseModel):
    provider: ModelProvider = "openai-compatible"
    name: str
    base_url: str | None = None
    api_key: str | None = None
    system_prompt_role: str | None = None
    context_window: int | None = None
    context_window_tokens: int | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    default_alias: str | None = None
    models: dict[str, ModelConfig] = Field(default_factory=dict)
