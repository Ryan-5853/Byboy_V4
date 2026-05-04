from __future__ import annotations

from pydantic import BaseModel, Field

from tool_call import ToolSpec

from ._safe_path import require_allowed_glob, resolve_workspace_path


class WriteFileConfig(BaseModel):
    workspace_root: str
    allow_write: bool = False
    max_write_chars: int = Field(default=20000, ge=1, le=2_000_000)
    allowed_globs: list[str] = Field(default_factory=list)
    create_dirs: bool = False
    overwrite: bool = False
    encoding: str = "utf-8"


class WriteFileArgs(BaseModel):
    path: str = Field(min_length=1)
    content: str


def execute(args: WriteFileArgs, config: WriteFileConfig) -> dict[str, object]:
    if not config.allow_write:
        raise PermissionError("filesystem.write_file requires allow_write=true in tool config.")
    if len(args.content) > config.max_write_chars:
        raise ValueError(
            f"Content exceeds max_write_chars: {len(args.content)} > {config.max_write_chars}"
        )

    path = resolve_workspace_path(config.workspace_root, args.path)
    require_allowed_glob(path, config.workspace_root, config.allowed_globs)
    if path.exists() and not config.overwrite:
        raise FileExistsError(f"File already exists and overwrite=false: {args.path}")
    if not path.parent.exists():
        if not config.create_dirs:
            raise FileNotFoundError(f"Parent directory does not exist: {path.parent}")
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args.content, encoding=config.encoding)
    return {"path": args.path, "chars_written": len(args.content)}


def build_pydantic_tool(config: WriteFileConfig):
    def write_file(path: str, content: str) -> dict[str, object]:
        """Write a text file inside the configured workspace."""
        args = WriteFileArgs.model_validate({"path": path, "content": content})
        return execute(args, config)

    return write_file


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="filesystem.write_file",
        description="Write a text file inside the configured workspace.",
        config_model=WriteFileConfig,
        args_model=WriteFileArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
