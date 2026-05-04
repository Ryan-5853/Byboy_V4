from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from tool_call import ToolSpec

from ._safe_path import is_allowed_glob, is_hidden, resolve_workspace_path


class SearchTextConfig(BaseModel):
    workspace_root: str
    max_results: int = Field(default=100, ge=1, le=5000)
    max_file_read_chars: int = Field(default=200000, ge=1, le=5_000_000)
    allowed_globs: list[str] = Field(default_factory=list)
    include_hidden: bool = False
    encoding: str = "utf-8"


class SearchTextArgs(BaseModel):
    query: str = Field(min_length=1)
    path: str = "."
    glob: str = "**/*"
    regex: bool = False
    case_sensitive: bool = False


def execute(args: SearchTextArgs, config: SearchTextConfig) -> list[dict[str, object]]:
    base = resolve_workspace_path(config.workspace_root, args.path)
    if not base.exists():
        raise FileNotFoundError(f"Path does not exist: {args.path}")

    flags = 0 if args.case_sensitive else re.IGNORECASE
    pattern = re.compile(args.query if args.regex else re.escape(args.query), flags)
    results: list[dict[str, object]] = []

    paths = [base] if base.is_file() else sorted(base.glob(args.glob))
    for path in paths:
        if len(results) >= config.max_results:
            break
        resolved = path.resolve()
        if not resolved.is_file():
            continue
        if not config.include_hidden and is_hidden(resolved, config.workspace_root):
            continue
        if not is_allowed_glob(resolved, config.workspace_root, config.allowed_globs):
            continue
        text = resolved.read_text(encoding=config.encoding, errors="replace")
        for line_number, line in enumerate(text[: config.max_file_read_chars].splitlines(), 1):
            if pattern.search(line):
                root = Path(config.workspace_root).expanduser().resolve()
                results.append(
                    {
                        "path": resolved.relative_to(root).as_posix(),
                        "line": line_number,
                        "text": line,
                    }
                )
                if len(results) >= config.max_results:
                    break
    return results


def build_pydantic_tool(config: SearchTextConfig):
    def search_text(
        query: str,
        path: str = ".",
        glob: str = "**/*",
        regex: bool = False,
        case_sensitive: bool = False,
    ) -> list[dict[str, object]]:
        """Search text files under the configured workspace."""
        args = SearchTextArgs.model_validate(
            {
                "query": query,
                "path": path,
                "glob": glob,
                "regex": regex,
                "case_sensitive": case_sensitive,
            }
        )
        return execute(args, config)

    return search_text


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="filesystem.search_text",
        description="Search text files under the configured workspace.",
        config_model=SearchTextConfig,
        args_model=SearchTextArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
