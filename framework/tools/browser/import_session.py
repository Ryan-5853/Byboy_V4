from __future__ import annotations

import json

from pydantic import BaseModel, Field

from browser_runtime import import_browser_session
from tool_call import ToolSpec
from tools.filesystem._safe_path import require_allowed_glob, resolve_workspace_path


class ImportSessionConfig(BaseModel):
    workspace_root: str
    allowed_globs: list[str] = Field(default_factory=list)


class ImportSessionArgs(BaseModel):
    path: str = Field(min_length=1)


def execute(args: ImportSessionArgs, config: ImportSessionConfig) -> dict[str, object]:
    target = resolve_workspace_path(config.workspace_root, args.path)
    require_allowed_glob(target, config.workspace_root, config.allowed_globs)
    payload = json.loads(target.read_text(encoding="utf-8"))
    session_id = import_browser_session(payload)
    return {"session_id": session_id, "path": args.path}


def build_pydantic_tool(config: ImportSessionConfig):
    def import_session(path: str) -> dict[str, object] | str:
        """Import browser session state from a workspace JSON file."""
        try:
            args = ImportSessionArgs.model_validate({"path": path})
            return execute(args, config)
        except Exception as exc:
            return (
                f"TOOL_ERROR browser.import_session failed for {path}: "
                f"{type(exc).__name__}: {exc}"
            )

    return import_session


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="browser.import_session",
        description="Import browser session state from a workspace JSON file.",
        config_model=ImportSessionConfig,
        args_model=ImportSessionArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )

