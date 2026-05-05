from __future__ import annotations

import json

from pydantic import BaseModel, Field

from browser_runtime import export_browser_session
from tool_call import ToolSpec
from tools.filesystem._safe_path import require_allowed_glob, resolve_workspace_path


class ExportSessionConfig(BaseModel):
    workspace_root: str
    allow_write: bool = False
    allowed_globs: list[str] = Field(default_factory=list)
    overwrite: bool = False


class ExportSessionArgs(BaseModel):
    session_id: str = Field(min_length=8)
    path: str = Field(min_length=1)


def execute(args: ExportSessionArgs, config: ExportSessionConfig) -> dict[str, object]:
    if not config.allow_write:
        raise PermissionError("browser.export_session requires allow_write=true in tool config.")
    target = resolve_workspace_path(config.workspace_root, args.path)
    require_allowed_glob(target, config.workspace_root, config.allowed_globs)
    if target.exists() and not config.overwrite:
        raise FileExistsError(f"File already exists and overwrite=false: {args.path}")
    payload = export_browser_session(args.session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    target.write_text(content, encoding="utf-8")
    return {"session_id": args.session_id, "path": args.path, "chars_written": len(content)}


def build_pydantic_tool(config: ExportSessionConfig):
    def export_session(session_id: str, path: str) -> dict[str, object] | str:
        """Export an in-memory browser session to a workspace JSON file."""
        try:
            args = ExportSessionArgs.model_validate({"session_id": session_id, "path": path})
            return execute(args, config)
        except Exception as exc:
            return (
                f"TOOL_ERROR browser.export_session failed for {path}: "
                f"{type(exc).__name__}: {exc}"
            )

    return export_session


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="browser.export_session",
        description="Export browser session state to a workspace JSON file.",
        config_model=ExportSessionConfig,
        args_model=ExportSessionArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )

