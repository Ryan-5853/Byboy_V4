from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tool_call import ToolSpec

from ._safe_path import is_allowed_glob, is_hidden, resolve_workspace_path


class ListFilesConfig(BaseModel):
    workspace_root: str
    max_results: int = Field(default=200, ge=1, le=5000)
    allowed_globs: list[str] = Field(default_factory=list)
    include_hidden: bool = False


class ListFilesArgs(BaseModel):
    path: str = "."
    glob: str = "**/*"


def execute(args: ListFilesArgs, config: ListFilesConfig) -> list[str]:
    root = Path(config.workspace_root).expanduser().resolve()
    base = resolve_workspace_path(config.workspace_root, args.path)
    if not base.exists():
        raise FileNotFoundError(f"Path does not exist: {args.path}")
    if not base.is_dir():
        raise ValueError(f"Path is not a directory: {args.path}")

    results: list[str] = []
    for path in sorted(base.glob(args.glob)):
        if len(results) >= config.max_results:
            break
        resolved = path.resolve()
        if not config.include_hidden and is_hidden(resolved, config.workspace_root):
            continue
        if resolved.is_file() and not is_allowed_glob(
            resolved, config.workspace_root, config.allowed_globs
        ):
            continue
        results.append(resolved.relative_to(root).as_posix())
    return results


def build_pydantic_tool(config: ListFilesConfig):
    def list_files(path: str = ".", glob: str = "**/*") -> list[str] | str:
        """List files under the configured workspace."""
        try:
            args = ListFilesArgs.model_validate({"path": path, "glob": glob})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR filesystem.list_files failed for {path}: {type(exc).__name__}: {exc}"

    return list_files


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="filesystem.list_files",
        description="List files under the configured workspace.",
        config_model=ListFilesConfig,
        args_model=ListFilesArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
