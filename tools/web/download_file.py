from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from tool_call import ToolSpec
from tools.filesystem._safe_path import require_allowed_glob, resolve_workspace_path


class DownloadFileConfig(BaseModel):
    """Hard limits for downloading a URL into the workspace."""

    workspace_root: str
    allow_write: bool = False
    max_bytes: int = Field(default=10_000_000, ge=1, le=500_000_000)
    timeout_seconds: float = Field(default=60, gt=0, le=300)
    follow_redirects: bool = True
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    allowed_globs: list[str] = Field(default_factory=list)
    overwrite: bool = False


class DownloadFileArgs(BaseModel):
    url: str = Field(min_length=1)
    path: str = Field(min_length=1)


def execute(args: DownloadFileArgs, config: DownloadFileConfig) -> dict[str, object]:
    """Download bytes to a workspace path after URL and file-policy checks."""

    if not config.allow_write:
        raise PermissionError("web.download_file requires allow_write=true in tool config.")

    scheme = urlparse(args.url).scheme.lower()
    if scheme not in config.allowed_schemes:
        allowed = ", ".join(config.allowed_schemes)
        raise ValueError(f"URL scheme not allowed: {scheme}. Allowed schemes: {allowed}")

    target = resolve_workspace_path(config.workspace_root, args.path)
    require_allowed_glob(target, config.workspace_root, config.allowed_globs)
    if target.exists() and not config.overwrite:
        raise FileExistsError(f"File already exists and overwrite=false: {args.path}")

    import httpx

    response = httpx.get(
        args.url,
        timeout=config.timeout_seconds,
        follow_redirects=config.follow_redirects,
    )
    response.raise_for_status()
    content = response.content
    if len(content) > config.max_bytes:
        raise ValueError(f"Download exceeds max_bytes: {len(content)} > {config.max_bytes}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {
        "url": args.url,
        "path": args.path,
        "bytes_written": len(content),
        "content_type": response.headers.get("content-type", ""),
    }


def build_pydantic_tool(config: DownloadFileConfig):
    def download_file(url: str, path: str) -> dict[str, object] | str:
        """Download a URL into a file inside the configured workspace."""

        try:
            args = DownloadFileArgs.model_validate({"url": url, "path": path})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR web.download_file failed for {url}: {type(exc).__name__}: {exc}"

    return download_file


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="web.download_file",
        description="Download a URL into a file inside the configured workspace.",
        config_model=DownloadFileConfig,
        args_model=DownloadFileArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )

