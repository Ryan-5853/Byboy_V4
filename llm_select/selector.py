from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .config_loader import load_llm_config
from .schemas import LLMConfig, ModelConfig


class LLMSelector:
    """Resolve model aliases into pydantic-ai model instances."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        config_file: str | Path | None = None,
    ) -> None:
        self.config = config or load_llm_config(config_file)

    def get(self, alias: str | None = None) -> Any:
        model_config = self.get_config(alias)
        return self._build_model(model_config)

    def get_config(self, alias: str | None = None) -> ModelConfig:
        selected_alias = alias or self.config.default_alias
        if selected_alias is None:
            raise ValueError("No model alias provided and no default_alias configured.")
        try:
            return self.config.models[selected_alias]
        except KeyError as exc:
            available = ", ".join(sorted(self.config.models)) or "<none>"
            raise ValueError(
                f"Unknown model alias: {selected_alias}. Available aliases: {available}"
            ) from exc

    def _build_model(self, config: ModelConfig) -> Any:
        if config.provider in {"openai-compatible", "openai", "openai-chat"}:
            provider_config: OpenAIProvider | str
            if config.provider == "openai-compatible":
                provider_config = OpenAIProvider(
                    base_url=config.base_url,
                    api_key=config.api_key,
                )
            elif config.api_key:
                provider_config = OpenAIProvider(api_key=config.api_key)
            else:
                provider_config = config.provider
            return OpenAIChatModel(
                config.name,
                provider=provider_config,
                system_prompt_role=config.system_prompt_role,
            )
        if config.provider == "known":
            return config.name
        raise ValueError(f"Unsupported model provider: {config.provider}")
