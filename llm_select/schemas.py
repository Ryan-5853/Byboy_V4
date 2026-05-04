from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ModelProvider = Literal["openai-compatible", "openai", "openai-chat", "known"]


class ModelConfig(BaseModel):
    provider: ModelProvider = "openai-compatible"
    name: str
    base_url: str | None = None
    api_key: str | None = None
    system_prompt_role: str | None = None


class LLMConfig(BaseModel):
    default_alias: str | None = None
    models: dict[str, ModelConfig] = Field(default_factory=dict)
