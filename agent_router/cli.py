from __future__ import annotations

import argparse
import json
from pathlib import Path

from .router import AgentRouter
from .schemas import RouterRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent_router",
        description="Route a prompt/config task to a pydantic-ai subagent.",
    )
    parser.add_argument("--prompt", required=True, help="Path to the task prompt file.")
    parser.add_argument("--config", required=True, help="Path to the subagent config file.")
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Template variable used to format the prompt file. Can be repeated.",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Base directory for resolving relative prompt/config paths.",
    )
    parser.add_argument(
        "--llm-config",
        default=None,
        help="Path to llm_select model alias config. Defaults to llm_select/models.yaml.",
    )
    return parser


def parse_vars(values: list[str]) -> dict[str, str]:
    variables: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--var expects KEY=VALUE, got: {value}")
        key, item = value.split("=", 1)
        variables[key] = item
    return variables


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request = RouterRequest(
        prompt_file=Path(args.prompt),
        config_file=Path(args.config),
        variables=parse_vars(args.var),
    )
    router = AgentRouter(
        base_dir=Path(args.base_dir) if args.base_dir else None,
        llm_config_file=Path(args.llm_config) if args.llm_config else None,
    )
    result = router.run_sync(request)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0
