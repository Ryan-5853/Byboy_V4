from __future__ import annotations

from pydantic import BaseModel, Field

from tool_call import ToolSpec

from ._safe_path import require_allowed_glob, resolve_workspace_path


class ReadFileConfig(BaseModel):
    workspace_root: str
    max_read_chars: int = Field(default=20000, ge=1, le=2_000_000)
    allowed_globs: list[str] = Field(default_factory=list)
    encoding: str = "utf-8"


class ReadFileArgs(BaseModel):
    path: str = Field(min_length=1)


def execute(args: ReadFileArgs, config: ReadFileConfig) -> str:
    path = resolve_workspace_path(config.workspace_root, args.path)
    require_allowed_glob(path, config.workspace_root, config.allowed_globs)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {args.path}")
    content = path.read_text(encoding=config.encoding)
    return content[: config.max_read_chars]


def build_pydantic_tool(config: ReadFileConfig):
    def read_file(path: str) -> str:
        """Read a text file from the configured workspace."""
        try:
            args = ReadFileArgs.model_validate({"path": path})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR filesystem.read_file failed for {path}: {type(exc).__name__}: {exc}"

    return read_file


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="filesystem.read_file",
        description="Read a text file from the configured workspace.",
        config_model=ReadFileConfig,
        args_model=ReadFileArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
