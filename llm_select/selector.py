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

    def get_model_settings(self, alias: str | None = None) -> dict[str, Any]:
        """Return model-level settings configured for an alias.

        These settings are owned by llm_select, not workflow prompts. They are
        later passed to pydantic-ai as model_settings; OpenAI-compatible
        backend-only parameters should live under `extra_body`.
        """

        config = self.get_config(alias)
        settings = dict(config.model_settings)
        return self._normalize_model_settings(config, settings)

    def get_context_window_tokens(self, alias: str | None = None) -> int | None:
        config = self.get_config(alias)
        if config.context_window_tokens is not None:
            return int(config.context_window_tokens)
        if config.context_window is not None:
            return int(config.context_window)
        return None

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

    def _normalize_model_settings(self, config: ModelConfig, settings: dict[str, Any]) -> dict[str, Any]:
        # Qwen 官方接口约定：enable_thinking 需要放在
        # extra_body.chat_template_kwargs.enable_thinking。
        if "qwen" not in config.name.lower():
            return settings

        extra_body = settings.get("extra_body")
        if not isinstance(extra_body, dict):
            return settings

        if "enable_thinking" not in extra_body:
            return settings

        enable_thinking = extra_body.pop("enable_thinking")
        chat_template_kwargs = extra_body.get("chat_template_kwargs")
        if not isinstance(chat_template_kwargs, dict):
            chat_template_kwargs = {}
        chat_template_kwargs["enable_thinking"] = enable_thinking
        extra_body["chat_template_kwargs"] = chat_template_kwargs
        settings["extra_body"] = extra_body
        return settings
