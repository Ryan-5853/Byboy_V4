from __future__ import annotations

from pydantic import BaseModel, Field

from tool_call import ToolSpec

from ._safe_path import require_allowed_glob, resolve_workspace_path


class AppendFileConfig(BaseModel):
    """Hard limits for append-only writes.

    Append is useful for logs, audit notes, and progressive reports. It is still
    a write operation, so allow_write must be explicitly enabled by the agent
    config before the model can use it.
    """

    workspace_root: str
    allow_write: bool = False
    max_append_chars: int = Field(default=20000, ge=1, le=2_000_000)
    allowed_globs: list[str] = Field(default_factory=list)
    create_dirs: bool = True
    encoding: str = "utf-8"


class AppendFileArgs(BaseModel):
    path: str = Field(min_length=1)
    content: str
    newline: bool = True


def execute(args: AppendFileArgs, config: AppendFileConfig) -> dict[str, object]:
    if not config.allow_write:
        raise PermissionError("filesystem.append_file requires allow_write=true in tool config.")
    content = args.content + ("\n" if args.newline and not args.content.endswith("\n") else "")
    if len(content) > config.max_append_chars:
        raise ValueError(f"Append exceeds max_append_chars: {len(content)} > {config.max_append_chars}")

    target = resolve_workspace_path(config.workspace_root, args.path)
    require_allowed_glob(target, config.workspace_root, config.allowed_globs)
    if not target.parent.exists():
        if not config.create_dirs:
            raise FileNotFoundError(f"Parent directory does not exist: {target.parent}")
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding=config.encoding) as handle:
        handle.write(content)
    return {"path": args.path, "chars_appended": len(content)}


def build_pydantic_tool(config: AppendFileConfig):
    def append_file(path: str, content: str, newline: bool = True) -> dict[str, object] | str:
        """Append text to a file inside the configured workspace."""
        try:
            args = AppendFileArgs.model_validate(
                {"path": path, "content": content, "newline": newline}
            )
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR filesystem.append_file failed for {path}: {type(exc).__name__}: {exc}"

    return append_file


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="filesystem.append_file",
        description="Append text to a file inside the configured workspace.",
        config_model=AppendFileConfig,
        args_model=AppendFileArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
