from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from tool_call import ToolSpec


class RunCommandConfig(BaseModel):
    """Hard limits for process.run_command.

    This tool is intentionally not a general shell. It runs a single executable
    from an allowlist, with shell=False, inside a configured workspace. This
    gives workflows OpenClaw-like access to local utilities such as pdftotext or
    pandoc without allowing arbitrary shell expansion, pipes, redirects, or
    command chaining.
    """

    workspace_root: str
    allowed_commands: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    max_output_chars: int = Field(default=50000, ge=1, le=2_000_000)
    extra_env: dict[str, str] = Field(default_factory=dict)


class RunCommandArgs(BaseModel):
    command: str = Field(min_length=1)


def execute(args: RunCommandArgs, config: RunCommandConfig) -> dict[str, object]:
    """Run an allowlisted command and return bounded stdout/stderr."""

    argv = shlex.split(args.command)
    if not argv:
        raise ValueError("Empty command")

    executable = Path(argv[0]).name
    if executable not in config.allowed_commands:
        allowed = ", ".join(config.allowed_commands) or "<none>"
        raise PermissionError(f"Command not allowed: {executable}. Allowed commands: {allowed}")

    root = Path(config.workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"workspace_root does not exist: {root}")

    # Keep the environment small and deterministic; workflows may add explicit
    # values through extra_env, but model-provided runtime args cannot mutate it.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    env.update(config.extra_env)

    completed = subprocess.run(
        argv,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=config.timeout_seconds,
        env=env,
        check=False,
    )
    stdout = completed.stdout[: config.max_output_chars]
    stderr = completed.stderr[: config.max_output_chars]
    return {
        "command": argv,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": len(completed.stdout) > len(stdout),
        "stderr_truncated": len(completed.stderr) > len(stderr),
    }


def build_pydantic_tool(config: RunCommandConfig):
    def run_command(command: str) -> dict[str, object] | str:
        """Run an allowlisted local command inside the configured workspace."""

        try:
            args = RunCommandArgs.model_validate({"command": command})
            return execute(args, config)
        except Exception as exc:
            return f"TOOL_ERROR process.run_command failed: {type(exc).__name__}: {exc}"

    return run_command


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="process.run_command",
        description="Run an allowlisted local command inside the configured workspace.",
        config_model=RunCommandConfig,
        args_model=RunCommandArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )

