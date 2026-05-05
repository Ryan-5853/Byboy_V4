from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class ParseJsonConfig(BaseModel):
    max_input_chars: int = Field(default=100000, ge=1, le=5_000_000)


class ParseJsonArgs(BaseModel):
    text: str = Field(min_length=1)


def execute(args: ParseJsonArgs, config: ParseJsonConfig) -> Any:
    if len(args.text) > config.max_input_chars:
        raise ValueError(f"JSON input exceeds max_input_chars: {len(args.text)}")
    return json.loads(args.text)


def build_pydantic_tool(config: ParseJsonConfig):
    def parse_json(text: str) -> Any:
        """Parse JSON text into structured data."""
        try:
            args = ParseJsonArgs.model_validate({"text": text})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR data.parse_json failed: {type(exc).__name__}: {exc}"

    return parse_json


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="data.parse_json",
        description="Parse JSON text into structured data.",
        config_model=ParseJsonConfig,
        args_model=ParseJsonArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
