from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field

from tool_call import ToolSpec

from ._safe_path import require_allowed_glob, resolve_workspace_path


class FileInfoConfig(BaseModel):
    """Hard limits for filesystem.file_info.

    The model may choose the target path at runtime, but it cannot choose the
    workspace boundary or the glob policy. Those are fixed here by the workflow
    config and checked before any metadata is returned.
    """

    workspace_root: str
    allowed_globs: list[str] = Field(default_factory=list)
    max_hash_bytes: int = Field(default=20_000_000, ge=1, le=500_000_000)


class FileInfoArgs(BaseModel):
    path: str = Field(min_length=1)
    include_hash: bool = False


def execute(args: FileInfoArgs, config: FileInfoConfig) -> dict[str, object]:
    """Return safe metadata for one workspace path.

    This is intentionally metadata-only. It does not read file contents except
    when include_hash=true, and even then it refuses files above max_hash_bytes.
    """

    target = resolve_workspace_path(config.workspace_root, args.path)
    if target.is_file():
        require_allowed_glob(target, config.workspace_root, config.allowed_globs)
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {args.path}")

    root = Path(config.workspace_root).expanduser().resolve()
    stat = target.stat()
    info: dict[str, object] = {
        "path": target.relative_to(root).as_posix(),
        "exists": True,
        "type": "directory" if target.is_dir() else "file",
        "size_bytes": stat.st_size,
        "mtime": stat.st_mtime,
    }
    if target.is_file():
        info["suffix"] = target.suffix
        if args.include_hash:
            if stat.st_size > config.max_hash_bytes:
                raise ValueError(
                    f"File too large to hash: {stat.st_size} > {config.max_hash_bytes}"
                )
            info["sha256"] = _sha256(target)
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_pydantic_tool(config: FileInfoConfig):
    def file_info(path: str, include_hash: bool = False) -> dict[str, object] | str:
        """Return metadata for a workspace file or directory."""
        try:
            args = FileInfoArgs.model_validate({"path": path, "include_hash": include_hash})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR filesystem.file_info failed for {path}: {type(exc).__name__}: {exc}"

    return file_info


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="filesystem.file_info",
        description="Return metadata for a file or directory inside the configured workspace.",
        config_model=FileInfoConfig,
        args_model=FileInfoArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
