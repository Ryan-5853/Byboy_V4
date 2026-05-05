from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class ExtractJsonConfig(BaseModel):
    """Hard limits for extracting JSON snippets from unstructured text."""

    max_input_chars: int = Field(default=200000, ge=1, le=5_000_000)
    max_results: int = Field(default=10, ge=1, le=100)


class ExtractJsonArgs(BaseModel):
    text: str = Field(min_length=1)
    mode: Literal["first", "all"] = "first"


def execute(args: ExtractJsonArgs, config: ExtractJsonConfig) -> Any:
    """Extract JSON object/array snippets from text.

    This is useful when a model or webpage wraps JSON in Markdown fences or
    explanatory prose. It uses Python's JSON decoder instead of brittle regex
    slicing, so nested braces and escaped strings are handled correctly.
    """

    if len(args.text) > config.max_input_chars:
        raise ValueError(f"Input exceeds max_input_chars: {len(args.text)} > {config.max_input_chars}")

    decoder = json.JSONDecoder()
    results: list[Any] = []
    for index, char in enumerate(args.text):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(args.text[index:])
        except json.JSONDecodeError:
            continue
        results.append(value)
        if args.mode == "first" or len(results) >= config.max_results:
            break

    if args.mode == "first":
        if not results:
            raise ValueError("No JSON object or array found in text")
        return results[0]
    return results


def build_pydantic_tool(config: ExtractJsonConfig):
    def extract_json(text: str, mode: str = "first") -> Any:
        """Extract JSON object/array snippets from unstructured text."""
        try:
            args = ExtractJsonArgs.model_validate({"text": text, "mode": mode})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR data.extract_json failed: {type(exc).__name__}: {exc}"

    return extract_json


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="data.extract_json",
        description="Extract JSON object or array snippets from unstructured text.",
        config_model=ExtractJsonConfig,
        args_model=ExtractJsonArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
