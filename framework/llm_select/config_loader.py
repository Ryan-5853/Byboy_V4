from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .schemas import LLMConfig


DEFAULT_CONFIG_FILE = Path(__file__).with_name("models.yaml")
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_llm_config(path: str | Path | None = None) -> LLMConfig:
    config_path = Path(path).expanduser() if path is not None else DEFAULT_CONFIG_FILE
    config_path = config_path.resolve()
    _load_env_chain(config_path)
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
        return _expand_env_string(value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _load_env_chain(config_path: Path) -> None:
    # Load repo-local env files automatically so cloned projects work without
    # exporting variables in every shell session.
    for parent in [config_path.parent, *config_path.parents]:
        env_file = parent / ".env"
        env_local_file = parent / ".env.local"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
        if env_local_file.is_file():
            load_dotenv(env_local_file, override=True)


def _expand_env_string(value: str) -> str:
    expanded = os.path.expandvars(value)

    def replacer(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_VAR_PATTERN.sub(replacer, expanded)
