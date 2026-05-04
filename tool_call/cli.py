from __future__ import annotations

import argparse
import json

from .manager import ToolCallManager
from .schemas import ConfiguredTool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tool_call",
        description="Validate and execute one configured project tool.",
    )
    parser.add_argument("--tool", required=True, help="Tool name, e.g. web.fetch_url.")
    parser.add_argument(
        "--config-json",
        default="{}",
        help="JSON object for this tool's hard-limit config.",
    )
    parser.add_argument(
        "--args-json",
        default="{}",
        help="JSON object for this tool's runtime arguments.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tool_config = json.loads(args.config_json)
    tool_args = json.loads(args.args_json)
    manager = ToolCallManager([ConfiguredTool(name=args.tool, config=tool_config)])
    result = manager.call(args.tool, tool_args)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0
