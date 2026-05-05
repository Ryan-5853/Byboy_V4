from __future__ import annotations

from string import Template
from typing import Any

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class RenderTemplateConfig(BaseModel):
    """Hard limits for simple string.Template rendering."""

    max_template_chars: int = Field(default=100000, ge=1, le=2_000_000)
    max_value_chars: int = Field(default=50000, ge=1, le=1_000_000)


class RenderTemplateArgs(BaseModel):
    template: str = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)
    safe: bool = True


def execute(args: RenderTemplateArgs, config: RenderTemplateConfig) -> str:
    """Render a small template with model-provided values.

    This deliberately uses Python's string.Template rather than eval, f-string
    execution, or Jinja. The tool performs text substitution only.
    """

    if len(args.template) > config.max_template_chars:
        raise ValueError(
            f"Template exceeds max_template_chars: {len(args.template)} > {config.max_template_chars}"
        )
    values = {}
    for key, value in args.values.items():
        text = str(value)
        if len(text) > config.max_value_chars:
            raise ValueError(f"Template value too long for key {key!r}")
        values[key] = text

    template = Template(args.template)
    return template.safe_substitute(values) if args.safe else template.substitute(values)


def build_pydantic_tool(config: RenderTemplateConfig):
    def render_template(template: str, values: dict[str, Any] | None = None, safe: bool = True) -> str:
        """Render a string.Template with a dictionary of values."""
        try:
            args = RenderTemplateArgs.model_validate(
                {"template": template, "values": values or {}, "safe": safe}
            )
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR data.render_template failed: {type(exc).__name__}: {exc}"

    return render_template


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="data.render_template",
        description="Render a safe string.Template with provided values.",
        config_model=RenderTemplateConfig,
        args_model=RenderTemplateArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
