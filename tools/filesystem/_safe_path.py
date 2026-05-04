from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path


def resolve_workspace_path(workspace_root: str, relative_path: str = ".") -> Path:
    root = Path(workspace_root).expanduser().resolve()
    target = (root / relative_path).expanduser().resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Path escapes configured workspace: {relative_path}")
    return target


def require_allowed_glob(path: Path, workspace_root: str, allowed_globs: list[str]) -> None:
    if not is_allowed_glob(path, workspace_root, allowed_globs):
        root = Path(workspace_root).expanduser().resolve()
        relative = path.resolve().relative_to(root).as_posix()
        allowed = ", ".join(allowed_globs)
        raise ValueError(f"Path is not allowed by configured globs: {relative}. Allowed: {allowed}")


def is_allowed_glob(path: Path, workspace_root: str, allowed_globs: list[str]) -> bool:
    if not allowed_globs:
        return True
    root = Path(workspace_root).expanduser().resolve()
    relative = path.resolve().relative_to(root).as_posix()
    return any(fnmatch(relative, pattern) for pattern in allowed_globs)


def is_hidden(path: Path, workspace_root: str) -> bool:
    root = Path(workspace_root).expanduser().resolve()
    relative_parts = path.resolve().relative_to(root).parts
    return any(part.startswith(".") for part in relative_parts)
