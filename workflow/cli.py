from __future__ import annotations

import argparse
from pathlib import Path

from .workflow import TutorSelectWorkflow, WorkflowError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflow",
        description="Tutor selection workflow powered by the framework layer.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="工程根目录路径，默认自动使用当前仓库根目录。",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆盖本次命令所有 subagent 的模型别名；后端详情仍由 framework/llm_select/models.yaml 管理。",
    )
    parser.add_argument(
        "--per-step-model",
        action="store_true",
        help="从 config/workflow.yaml 的 step_model_aliases 读取每一步的模型别名。",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-profile", help="读取 workflow/User/ 输入并生成 workflow/User/profile.md")
    sub.add_parser("init-school", help="读取 workspace/school_info.json 并生成导师名单")

    explore = sub.add_parser("explore", help="探索导师主页并生成页面访问策略")
    explore.add_argument("project_id", nargs="?")
    explore.add_argument("--sample-size", type=int, default=5)

    condense = sub.add_parser("condense-pattern", help="精简页面访问策略")
    condense.add_argument("project_id", nargs="?")

    gen_prompts = sub.add_parser("gen-prompts", help="批量生成导师分析 prompt")
    gen_prompts.add_argument("project_id", nargs="?")

    test = sub.add_parser("test", help="单测一个导师 prompt")
    test.add_argument("prompt_file")
    test.add_argument("--project-id", default=None)

    batch = sub.add_parser("batch", help="按序号范围批量分析导师")
    batch.add_argument("range_from", type=int)
    batch.add_argument("range_to", type=int)
    batch.add_argument("--project-id", default=None)
    batch.add_argument("--parallel", type=int, default=1)
    batch.add_argument("--batch-size", type=int, default=10)

    full = sub.add_parser("full", help="全量分析导师")
    full.add_argument("--project-id", default=None)
    full.add_argument("--parallel", type=int, default=1)
    full.add_argument("--batch-size", type=int, default=10)

    report = sub.add_parser("report", help="汇总 full 输出")
    report.add_argument("project_id", nargs="?")

    audit = sub.add_parser("audit", help="审计最近的分析结果")
    audit.add_argument("project_id", nargs="?")
    audit.add_argument("--batch-count", type=int, default=3)

    sub.add_parser("status", help="查看项目状态")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workflow = TutorSelectWorkflow(Path(args.root).expanduser() if args.root else None)
    try:
        if args.command == "build-profile":
            workflow.build_profile(model_alias=args.model, per_step_model=args.per_step_model)
        elif args.command == "init-school":
            workflow.init_school(model_alias=args.model, per_step_model=args.per_step_model)
        elif args.command == "explore":
            workflow.explore(
                args.project_id,
                model_alias=args.model,
                per_step_model=args.per_step_model,
                sample_size=args.sample_size,
            )
        elif args.command == "condense-pattern":
            workflow.condense_pattern(
                args.project_id,
                model_alias=args.model,
                per_step_model=args.per_step_model,
            )
        elif args.command == "gen-prompts":
            workflow.gen_prompts(args.project_id)
        elif args.command == "test":
            workflow.run_eval(
                "test",
                prompt_file=args.prompt_file,
                project_id=args.project_id,
                model_alias=args.model,
                per_step_model=args.per_step_model,
            )
        elif args.command == "batch":
            workflow.run_eval(
                "batch",
                range_from=args.range_from,
                range_to=args.range_to,
                project_id=args.project_id,
                parallel=args.parallel,
                batch_size=args.batch_size,
                model_alias=args.model,
                per_step_model=args.per_step_model,
            )
        elif args.command == "full":
            workflow.run_eval(
                "full",
                project_id=args.project_id,
                parallel=args.parallel,
                batch_size=args.batch_size,
                model_alias=args.model,
                per_step_model=args.per_step_model,
            )
        elif args.command == "report":
            workflow.report(args.project_id)
        elif args.command == "audit":
            workflow.audit(
                args.project_id,
                batch_count=args.batch_count,
                model_alias=args.model,
                per_step_model=args.per_step_model,
            )
        elif args.command == "status":
            workflow.status()
        else:
            parser.error(f"unknown command: {args.command}")
    except WorkflowError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 1
    return 0
