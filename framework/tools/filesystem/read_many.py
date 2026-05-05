from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tool_call import ToolSpec

from ._safe_path import require_allowed_glob, resolve_workspace_path


class ReadManyConfig(BaseModel):
    """Hard limits for reading several files in one tool call."""

    workspace_root: str
    max_files: int = Field(default=10, ge=1, le=100)
    max_read_chars_per_file: int = Field(default=20000, ge=1, le=2_000_000)
    max_total_chars: int = Field(default=100000, ge=1, le=5_000_000)
    allowed_globs: list[str] = Field(default_factory=list)
    encoding: str = "utf-8"


class ReadManyArgs(BaseModel):
    paths: list[str] = Field(min_length=1)


def execute(args: ReadManyArgs, config: ReadManyConfig) -> list[dict[str, object]]:
    """Read several allowed text files, returning one structured item per file."""

    if len(args.paths) > config.max_files:
        raise ValueError(f"Too many files requested: {len(args.paths)} > {config.max_files}")

    root = Path(config.workspace_root).expanduser().resolve()
    total = 0
    results: list[dict[str, object]] = []
    for raw_path in args.paths:
        target = resolve_workspace_path(config.workspace_root, raw_path)
        require_allowed_glob(target, config.workspace_root, config.allowed_globs)
        if not target.is_file():
            raise FileNotFoundError(f"File does not exist: {raw_path}")
        text = target.read_text(encoding=config.encoding, errors="replace")
        clipped = text[: config.max_read_chars_per_file]
        remaining = config.max_total_chars - total
        if remaining <= 0:
            break
        clipped = clipped[:remaining]
        total += len(clipped)
        results.append(
            {
                "path": target.relative_to(root).as_posix(),
                "content": clipped,
                "chars_returned": len(clipped),
                "truncated": len(text) > len(clipped),
            }
        )
    return results


def build_pydantic_tool(config: ReadManyConfig):
    def read_many(paths: list[str]) -> list[dict[str, object]] | str:
        """Read multiple text files from the configured workspace."""
        try:
            args = ReadManyArgs.model_validate({"paths": paths})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR filesystem.read_many failed: {type(exc).__name__}: {exc}"

    return read_many


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="filesystem.read_many",
        description="Read multiple text files from the configured workspace in one call.",
        config_model=ReadManyConfig,
        args_model=ReadManyArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
