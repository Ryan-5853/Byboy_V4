from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from .schemas import LLMConfig


DEFAULT_CONFIG_FILE = Path(__file__).with_name("models.yaml")


def load_llm_config(path: str | Path | None = None) -> LLMConfig:
    config_path = Path(path).expanduser() if path is not None else DEFAULT_CONFIG_FILE
    config_path = config_path.resolve()
    raw = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"LLM config must contain a mapping: {config_path}")
    return LLMConfig.model_validate(_expand_env(data))


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value
