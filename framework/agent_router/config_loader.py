from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from .schemas import SubAgentConfig


def resolve_path(path: str | Path, base_dir: Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    return candidate.resolve()


def load_prompt(path: str | Path, base_dir: Path | None = None) -> str:
    prompt_path = resolve_path(path, base_dir)
    return prompt_path.read_text(encoding="utf-8")


def load_config(path: str | Path, base_dir: Path | None = None) -> SubAgentConfig:
    config_path = resolve_path(path, base_dir)
    raw = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Config must contain a mapping: {config_path}")
    expanded = _expand_env(data)
    return SubAgentConfig.model_validate(expanded)


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value
