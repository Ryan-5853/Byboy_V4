from __future__ import annotations

import csv
import json
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

from agent_router import AgentRouter, RouterRequest
from llm_select import LLMSelector

try:
    from . import prompts
except ImportError:
    import prompts


class WorkflowError(RuntimeError):
    pass


AGENT_PROMPT_INJECTION_HEADER = "用户临时纠偏提示（仅当前学院 / 当前 agent 类型生效）"

STEP_MODEL_KEYS: tuple[str, ...] = (
    "build-profile",
    "init-school",
    "verify-school",
    "repair-school",
    "explore",
    "condense-pattern",
    "gen-prompts",
    "eval",
    "audit",
)


DEFAULT_CONFIG: dict[str, Any] = {
    "default_model_alias": "local-default",
    "step_model_aliases": {},
    "usage_limits": {
        "max_requests": "unlimited",
        "max_tool_calls": "unlimited",
        "max_output_tokens": "unlimited",
        "max_total_tokens": "unlimited",
    },
    "step_usage_limits": {
        # Eval 阶段限制更紧，避免模型在无效主页情况下长时间游走。
        "eval": {
            "max_requests": 16,
            "max_tool_calls": 24,
        },
    },
    "agent_retry": {
        "max_attempts": "unlimited",
        "initial_delay_seconds": 2.0,
        "max_delay_seconds": 1800.0,
    },
    "context_management": {
        "enabled": True,
        "threshold_ratio": 0.8,
    },
    "tool_limits": {
        "max_file_read_chars": 20000,
        "max_file_write_chars": 50000,
        "max_web_read_chars": 10000,
        "max_links": 300,
        "max_search_results": 8,
        "timeout_seconds": 300,
    },
}


@dataclass(frozen=True)
class EvalTask:
    seq: str
    name: str
    prompt_file: Path


class TutorSelectWorkflow:
    def __init__(self, root: str | Path | None = None) -> None:
        workflow_dir, project_root = self._resolve_roots(root)
        self.workflow_dir = workflow_dir
        self.project_root = project_root
        self.framework_root = project_root / "framework"
        self.user_dir = workflow_dir / "User"
        self.workspace_dir = project_root / "workspace"
        self.meta_dir = workflow_dir / "meta"
        self.config_dir = workflow_dir / "config"
        self.run_dir = workflow_dir / ".runs"
        self.config = self._load_workflow_config()
        self._state_lock = threading.Lock()
        self.active_project_file = self.workspace_dir / "active_project.json"
        self.prompt_injections_file = self.config_dir / "agent_prompt_injections.json"

    def _resolve_roots(self, root: str | Path | None) -> tuple[Path, Path]:
        if root is None:
            workflow_dir = Path(__file__).resolve().parent
            return workflow_dir, workflow_dir.parent
        candidate = Path(root).expanduser().resolve()
        # Support both `--root /repo` and the old-style `--root /repo/workflow`.
        if (candidate / "User").is_dir() or (candidate / "config").is_dir():
            return candidate, candidate.parent
        return candidate / "workflow", candidate

    def build_profile(self, *, model_alias: str | None = None, per_step_model: bool = False) -> None:
        favor = self.user_dir / "tutor_favor.json"
        if not favor.is_file():
            raise WorkflowError(f"缺少必填文件: {self._rel(favor)}")
        resume = self._find_resume_file()
        if resume is None:
            raise WorkflowError("未找到任何简历文件，请放入 workflow/User/resume.*、workflow/User/cv.* 或 workflow/User/简历.*")
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self._prepare_resume_extraction(resume)

        prompt_path = self.meta_dir / "_build_profile_task.txt"
        self._write_text(prompt_path, prompts.build_profile_prompt())
        self._run_agent("build-profile", prompt_path, model_alias=model_alias, per_step_model=per_step_model)
        profile = self.user_dir / "profile.md"
        if not profile.is_file():
            raise WorkflowError("workflow/User/profile.md 未生成。请查看 subagent 日志。")
        self._log(f"✓ 个人档案已生成: {self._rel(profile)} ({len(profile.read_text(encoding='utf-8').splitlines())} 行)")

    def init_school(
        self,
        *,
        model_alias: str | None = None,
        per_step_model: bool = False,
        max_retries: int = 3,
    ) -> None:
        school_info_file = self.workspace_dir / "school_info.json"
        if not school_info_file.is_file():
            raise WorkflowError(f"缺少 {self._rel(school_info_file)}")
        school_info = self._read_json(school_info_file)
        school_name = str(school_info.get("school_name", "") or "")
        academy_name = str(school_info.get("academy_name", "") or "")
        homepage_url = str(school_info.get("homepage_url", "") or "")
        if not school_name or not academy_name:
            raise WorkflowError("school_info.json 中 school_name 和 academy_name 不能为空")

        project_id = f"{school_name}_{academy_name}"
        project_dir = self.workspace_dir / project_id
        tutors_file = project_dir / "tutors_data.json"
        project_dir.mkdir(parents=True, exist_ok=True)

        self._log(f"学校: {school_name}")
        self._log(f"学院: {academy_name}")
        self._log(f"主页: {homepage_url or '(未提供)'}")
        self._log(f"开始获取导师名单（最多重试 {max_retries} 轮）")

        extract_success = False
        verify_success = False
        for retry in range(max_retries):
            for local_try in range(3):
                self._log(f"===== 第 {retry + 1} 轮，子尝试 {local_try + 1} =====")
                task_file = project_dir / f"_extract_task_r{retry}.txt"
                self._write_text(
                    task_file,
                    prompts.init_school_extract_prompt(
                        school_name=school_name,
                        academy_name=academy_name,
                        homepage_url=homepage_url,
                        tutors_file=self._rel(tutors_file),
                        project_dir=self._rel(project_dir),
                    ),
                )
                self._run_agent(
                    "init-school",
                    task_file,
                    model_alias=model_alias,
                    per_step_model=per_step_model,
                )
                valid, message = self._validate_tutors_json(tutors_file)
                if valid:
                    extract_success = True
                    self._log(f"✓ JSON 校验通过: {message}")
                    break
                self._log(f"JSON 校验不通过，重试: {message}")

            if not extract_success:
                continue

            verify_task = project_dir / f"_verify_task_r{retry}.txt"
            self._write_text(
                verify_task,
                prompts.init_school_verify_prompt(
                    school_name=school_name,
                    academy_name=academy_name,
                    homepage_url=homepage_url,
                    tutors_file=self._rel(tutors_file),
                ),
            )
            result = self._run_agent(
                "verify-school",
                verify_task,
                model_alias=model_alias,
                per_step_model=per_step_model,
            )
            verify_text = str(result.output or "")
            if "VERIFY_PASS" in verify_text:
                verify_success = True
                self._log("✓ 校验通过")
                break
            self._log("校验未通过，进入修复阶段")
            repair_task = project_dir / f"_repair_task_r{retry}.txt"
            self._write_text(
                repair_task,
                prompts.init_school_repair_prompt(
                    school_name=school_name,
                    academy_name=academy_name,
                    homepage_url=homepage_url,
                    tutors_file=self._rel(tutors_file),
                    verify_feedback=verify_text,
                ),
            )
            repair_result = self._run_agent(
                "repair-school",
                repair_task,
                model_alias=model_alias,
                per_step_model=per_step_model,
            )
            repair_text = str(repair_result.output or "")
            repair_valid, repair_msg = self._validate_tutors_json(tutors_file)
            if "REPAIR_SUCCESS" in repair_text and repair_valid:
                verify_success = True
                self._log(f"✓ 修复成功，跳过二次校验: {repair_msg}")
                break
            self._log(f"修复未通过，回到提取阶段: {repair_msg}")
            extract_success = False

        if not (extract_success and verify_success):
            raise WorkflowError("导师名单获取失败，提取与校验无法一致通过。")

        tutors = self._read_json(tutors_file)
        tutor_count = len(tutors)
        for subdir in ["data/sample", "output/test", "output/full", "state", "meta", "prompts", "explore"]:
            (project_dir / subdir).mkdir(parents=True, exist_ok=True)
        self._write_text(
            project_dir / "school_profile.md",
            f"# {school_name} {academy_name}\n\n"
            "## 基本信息\n"
            f"- 学校: {school_name}\n"
            f"- 学院: {academy_name}\n"
            f"- 主页: {homepage_url}\n\n"
            "## 导师统计\n"
            f"- 总数: {tutor_count} 位\n",
        )
        school_info.pop("project_id", None)
        school_info.pop("tutor_count", None)
        self._write_json(school_info_file, school_info)
        self._write_project_info(
            project_dir,
            {
                "project_id": project_id,
                "school_name": school_name,
                "academy_name": academy_name,
                "homepage_url": homepage_url,
                "tutor_count": tutor_count,
            },
        )
        self._set_active_project(project_id)
        self._init_eval_state(project_dir, tutors)
        self._log(f"✓✓ 导师名单初始化完成: workspace/{project_id}/，导师 {tutor_count} 位")

    def explore(
        self,
        project_id: str | None = None,
        *,
        model_alias: str | None = None,
        per_step_model: bool = False,
        sample_size: int = 5,
    ) -> None:
        project_dir = self._project_dir(project_id)
        project_info = self._project_info(project_dir=project_dir)
        tutors_file = project_dir / "tutors_data.json"
        if not tutors_file.is_file():
            raise WorkflowError(f"导师名单不存在: {self._rel(tutors_file)}")
        tutors = self._read_json(tutors_file)
        if not isinstance(tutors, list) or not tutors:
            raise WorkflowError("tutors_data.json 不是非空导师数组")

        sample = tutors if len(tutors) <= sample_size else random.sample(tutors, sample_size)
        explore_dir = project_dir / "explore"
        explore_dir.mkdir(parents=True, exist_ok=True)
        school_name = str(project_info.get("school_name", ""))
        academy_name = str(project_info.get("academy_name", ""))
        self._log(f"项目: {project_dir.name}")
        self._log(f"随机抽取 {len(sample)} 个导师主页")

        effective_count = 0
        for idx, tutor in enumerate(sample, 1):
            name = str(tutor.get("导师姓名", "?"))
            url = str(tutor.get("主页URL", ""))
            self._log(f"===== 测试 #{idx}: {name} ({url}) =====")
            test_file = explore_dir / f"test_tutor_{idx}.md"
            task_file = explore_dir / f"_task_tutor_{idx}.txt"
            self._write_text(
                task_file,
                prompts.explore_prompt(
                    name=name,
                    url=url,
                    school_name=school_name,
                    academy_name=academy_name,
                    test_file=self._rel(test_file),
                ),
            )
            self._run_agent("explore", task_file, model_alias=model_alias, per_step_model=per_step_model)
            if self._is_effective_explore_report(test_file):
                effective_count += 1
                self._log(f"✓ 获取到有效信息: {self._rel(test_file)}")
            elif test_file.is_file():
                self._log(f"⚠ 测试文件较短或无有效信息标记: {self._rel(test_file)}")
            else:
                self._log(f"✗ 未生成 {self._rel(test_file)}")

        pattern_file = project_dir / "page_pattern.md"
        reports = self._collect_explore_reports(explore_dir)
        synth_task = explore_dir / "_synthesize_task.txt"
        self._write_text(
            synth_task,
            prompts.synthesize_pattern_prompt(
                school_name=school_name,
                academy_name=academy_name,
                total_count=len(sample),
                effective_count=effective_count,
                test_reports=reports,
                pattern_file=self._rel(pattern_file),
            ),
        )
        self._run_agent("explore", synth_task, model_alias=model_alias, per_step_model=per_step_model)
        if pattern_file.is_file():
            self._log(f"✓ 页面访问策略已生成: {self._rel(pattern_file)}")
            self.condense_pattern(project_dir.name, model_alias=model_alias, per_step_model=per_step_model)
        else:
            raise WorkflowError(f"page_pattern.md 未生成，请检查 {self._rel(synth_task)}")

    def condense_pattern(
        self,
        project_id: str | None = None,
        *,
        model_alias: str | None = None,
        per_step_model: bool = False,
    ) -> None:
        project_dir = self._project_dir(project_id)
        project_info = self._project_info(project_dir=project_dir)
        pattern_file = project_dir / "page_pattern.md"
        if not pattern_file.is_file():
            raise WorkflowError(f"页面访问策略不存在: {self._rel(pattern_file)}")
        condensed_file = project_dir / "page_pattern_condensed.md"
        task_file = project_dir / "explore" / "_condense_task.txt"
        task_file.parent.mkdir(parents=True, exist_ok=True)
        self._write_text(
            task_file,
            prompts.condense_pattern_prompt(
                school_name=str(project_info.get("school_name", "")),
                academy_name=str(project_info.get("academy_name", "")),
                pattern_file=self._rel(pattern_file),
                condensed_file=self._rel(condensed_file),
            ),
        )
        self._run_agent(
            "condense-pattern",
            task_file,
            model_alias=model_alias,
            per_step_model=per_step_model,
        )
        if not condensed_file.is_file():
            raise WorkflowError("page_pattern_condensed.md 未生成")
        self._log(f"✓ 精简版已生成: {self._rel(condensed_file)}")

    def gen_prompts(self, project_id: str | None = None) -> None:
        project_dir = self._project_dir(project_id)
        project_info = self._project_info(project_dir=project_dir)
        tutors_file = project_dir / "tutors_data.json"
        profile_file = self.user_dir / "profile.md"
        pattern_file = project_dir / "page_pattern_condensed.md"
        if not profile_file.is_file():
            raise WorkflowError("缺少标准档案: workflow/User/profile.md，请先运行 build-profile")
        if not pattern_file.is_file():
            raise WorkflowError("页面访问策略精简版不存在，请先运行 condense-pattern")
        if not tutors_file.is_file():
            raise WorkflowError("导师名单不存在，请先运行 init-school")

        tutors = self._read_json(tutors_file)
        if not isinstance(tutors, list):
            raise WorkflowError("tutors_data.json 必须是数组")
        prompts_dir = project_dir / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        access_strategy = pattern_file.read_text(encoding="utf-8")
        student_info = profile_file.read_text(encoding="utf-8")
        school_name = str(project_info.get("school_name", ""))
        academy_name = str(project_info.get("academy_name", ""))

        for idx, tutor in enumerate(tutors, 1):
            seq = str(tutor.get("序号") or idx)
            name = str(tutor.get("导师姓名", "未知"))
            url = str(tutor.get("主页URL", ""))
            safe_name = _safe_filename(name)
            prompt_file = prompts_dir / f"prompt_{seq}_{safe_name}.md"
            self._write_text(
                prompt_file,
                prompts.tutor_eval_prompt(
                    seq=seq,
                    name=name,
                    url=url,
                    school_name=school_name,
                    academy_name=academy_name,
                    access_strategy=access_strategy,
                    student_info=student_info,
                ),
            )

        self._init_eval_state(project_dir, tutors)
        self._log(f"✓ 已生成 {len(tutors)} 个 prompt 文件: {self._rel(prompts_dir)}/")

    def run_eval(
        self,
        mode: str,
        *,
        prompt_file: str | Path | None = None,
        range_from: int | None = None,
        range_to: int | None = None,
        project_id: str | None = None,
        parallel: int = 1,
        batch_size: int = 10,
        model_alias: str | None = None,
        per_step_model: bool = False,
    ) -> None:
        project_dir = self._project_dir(project_id)
        prompts_dir = project_dir / "prompts"
        state_file = project_dir / "state" / "eval_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        output_dir = project_dir / "output" / ("test" if mode == "test" else "full")
        output_dir.mkdir(parents=True, exist_ok=True)

        tasks = self._select_eval_tasks(
            mode,
            prompts_dir=prompts_dir,
            prompt_file=prompt_file,
            range_from=range_from,
            range_to=range_to,
        )
        if not tasks:
            raise WorkflowError("没有找到匹配的 prompt 文件")
        self._ensure_state_for_tasks(state_file, tasks)
        self._log(f"模式: {mode}")
        self._log(f"待处理: {len(tasks)} 位导师")
        self._log(f"并行数: {parallel}")
        self._log(f"输出目录: {self._rel(output_dir)}")

        done_count = 0
        fail_count = 0
        if parallel <= 1:
            for i, task in enumerate(tasks, 1):
                ok = self._process_eval_task(
                    task,
                    state_file=state_file,
                    output_dir=output_dir,
                    mode=mode,
                    model_alias=model_alias,
                    per_step_model=per_step_model,
                )
                done_count += int(ok)
                fail_count += int(not ok)
                if mode != "test" and i % batch_size == 0:
                    self._summarize_state(state_file)
        else:
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = [
                    executor.submit(
                        self._process_eval_task,
                        task,
                        state_file=state_file,
                        output_dir=output_dir,
                        mode=mode,
                        model_alias=model_alias,
                        per_step_model=per_step_model,
                    )
                    for task in tasks
                ]
                for future in as_completed(futures):
                    ok = future.result()
                    done_count += int(ok)
                    fail_count += int(not ok)

        summary = self._summarize_state(state_file)
        self._log("============================================")
        self._log("评估完成")
        self._log(f"总导师: {len(tasks)}")
        self._log(f"成功: {done_count}")
        self._log(f"失败: {fail_count}")
        self._log(f"状态: {summary}")
        self._log(f"输出: {self._rel(output_dir)}/")
        self._log("============================================")

    def report(self, project_id: str | None = None) -> None:
        project_dir = self._project_dir(project_id)
        output_dir = project_dir / "output" / "full"
        if not output_dir.is_dir():
            raise WorkflowError(f"输出目录不存在: {self._rel(output_dir)}")
        results = []
        for path in sorted(output_dir.glob("tutor_*.json"), key=_eval_file_sort_key):
            try:
                data = self._read_json(path)
                if isinstance(data, dict):
                    results.append(data)
            except Exception as exc:
                self._log(f"⚠ 跳过 {self._rel(path)}: {exc}")
        results.sort(key=lambda item: int(str(item.get("序号", 9999))) if str(item.get("序号", "")).isdigit() else 9999)

        analysis_json = output_dir / "analysis_results.json"
        analysis_csv = output_dir / "analysis_results.csv"
        self._write_json(analysis_json, results)
        if results:
            with analysis_csv.open("w", newline="", encoding="utf-8-sig") as handle:
                fields = list(results[0].keys())
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(results)

        self._log(f"✓ 汇总结果: {len(results)} 位导师已处理")
        groups: dict[str, list[dict[str, Any]]] = {key: [] for key in ["S", "A", "B", "C", "D"]}
        for result in results:
            groups.setdefault(str(result.get("优先级", "D")), []).append(result)
        for priority in ["S", "A", "B", "C", "D"]:
            items = sorted(groups.get(priority, []), key=lambda item: item.get("总分", 0), reverse=True)
            self._log(f"======== 优先级 {priority} ({len(items)}人) ========")
            for item in items[:20]:
                self._log(
                    f"  #{item.get('序号', '')} {item.get('导师姓名', '')} — "
                    f"{item.get('总分', 0)}分 — {str(item.get('主匹配项目', ''))[:30]}"
                )
        self._log(f"查看: {self._rel(analysis_json)}")
        if results:
            self._log(f"查看: {self._rel(analysis_csv)}")

    def audit(
        self,
        project_id: str | None = None,
        *,
        batch_count: int = 3,
        model_alias: str | None = None,
        per_step_model: bool = False,
    ) -> None:
        project_dir = self._project_dir(project_id)
        output_dir = project_dir / "output" / "full"
        files = sorted(output_dir.glob("tutor_*.json"), key=_eval_file_sort_key)
        if not files:
            raise WorkflowError("没有可审计的输出文件")
        recent_files = files[-5:]
        recent_results = []
        for path in recent_files:
            recent_results.append(f"\n--- {path.name} ---\n{path.read_text(encoding='utf-8')}\n")

        meta_dir = project_dir / "meta"
        prompt = prompts.audit_prompt(
            meta_version=(self.meta_dir / "VERSION").read_text(encoding="utf-8").strip()
            if (self.meta_dir / "VERSION").is_file()
            else "1",
            student_profile=(self.user_dir / "profile.md").read_text(encoding="utf-8")
            if (self.user_dir / "profile.md").is_file()
            else "(无)",
            scoring_criteria=(meta_dir / "scoring_criteria.md").read_text(encoding="utf-8")
            if (meta_dir / "scoring_criteria.md").is_file()
            else "(无)",
            audit_checklist=(meta_dir / "audit_checklist.md").read_text(encoding="utf-8")
            if (meta_dir / "audit_checklist.md").is_file()
            else "(无)",
            recent_results="".join(recent_results),
            file_count=len(files),
            batch_count=batch_count,
        )
        audit_task = meta_dir / "_audit_task.txt"
        meta_dir.mkdir(parents=True, exist_ok=True)
        self._write_text(audit_task, prompt)
        result = self._run_agent("audit", audit_task, model_alias=model_alias, per_step_model=per_step_model)
        audit_log = project_dir / "state" / "audit_log.md"
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        self._write_text(audit_log, str(result.output or ""))
        self._log(f"✓ 审计完成: {self._rel(audit_log)}")

    def status(self) -> dict[str, Any]:
        active_project = self._get_active_project()
        status: dict[str, Any] = {
            "school": None,
            "academy": None,
            "project_id": None,
            "active_project_id": active_project,
            "homepage_url": None,
            "tutor_count": 0,
            "done_count": 0,
            "prompt_count": 0,
            "has_profile": (self.user_dir / "profile.md").is_file(),
            "has_favor": (self.user_dir / "tutor_favor.json").is_file(),
            "project_ready": False,
            "file_checks": {},
            "available_projects": self.list_projects(),
        }
        if active_project:
            project_dir = self.workspace_dir / str(active_project)
            if project_dir.is_dir():
                project_info = self._project_info(project_dir=project_dir)
                project_id = project_info.get("project_id") or active_project
                status.update(
                    {
                        "school": project_info.get("school_name"),
                        "academy": project_info.get("academy_name"),
                        "project_id": project_id,
                        "homepage_url": project_info.get("homepage_url"),
                        "tutor_count": project_info.get("tutor_count", 0),
                    }
                )
                tutors_file = project_dir / "tutors_data.json"
                if tutors_file.is_file():
                    tutors = self._read_json(tutors_file)
                    status["tutor_count"] = len(tutors) if isinstance(tutors, list) else 0
                    status["project_ready"] = True
                output_dir = project_dir / "output" / "full"
                prompts_dir = project_dir / "prompts"
                status["done_count"] = len(list(output_dir.glob("tutor_*.json"))) if output_dir.is_dir() else 0
                status["prompt_count"] = len(list(prompts_dir.glob("prompt_*.md"))) if prompts_dir.is_dir() else 0
                for filename in [
                    "school_profile.md",
                    "page_pattern.md",
                    "page_pattern_condensed.md",
                    "tutors_data.json",
                    "access_log.md",
                    "project_info.json",
                ]:
                    status["file_checks"][filename] = (project_dir / filename).is_file()
        self._log(json.dumps(status, ensure_ascii=False, indent=2))
        return status

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        active_project = self._get_active_project()
        if not self.workspace_dir.is_dir():
            return projects
        for path in sorted(self.workspace_dir.iterdir(), key=lambda item: item.name):
            if not path.is_dir() or path.name.startswith("."):
                continue
            if not ((path / "tutors_data.json").is_file() or (path / "project_info.json").is_file()):
                continue
            info = self._project_info(project_dir=path)
            projects.append(
                {
                    "project_id": info.get("project_id") or path.name,
                    "school_name": info.get("school_name"),
                    "academy_name": info.get("academy_name"),
                    "homepage_url": info.get("homepage_url"),
                    "tutor_count": info.get("tutor_count", 0),
                    "is_active": (info.get("project_id") or path.name) == active_project,
                }
            )
        return projects

    def _run_agent(
        self,
        step: str,
        prompt_file: Path,
        *,
        model_alias: str | None,
        per_step_model: bool,
    ) -> Any:
        effective_prompt = self._prompt_file_with_injection(step, prompt_file)
        config_file = self._write_agent_config(step, effective_prompt, model_alias, per_step_model)
        self._log(f"[agent] step={step} prompt={self._rel(effective_prompt)} config={self._rel(config_file)}")
        retry_config = self._agent_retry_config(step)
        max_attempts = retry_config["max_attempts"]
        unlimited_retries = max_attempts is None
        attempt = 1
        while True:
            if attempt > 1:
                attempt_label = f"{attempt}/unlimited" if unlimited_retries else f"{attempt}/{max_attempts}"
                self._log(f"[agent-retry] step={step} attempt={attempt_label}")
            router = AgentRouter(llm_config_file=self.framework_root / "llm_select" / "models.yaml")
            result = router.run_sync(
                RouterRequest(prompt_file=effective_prompt, config_file=config_file, raise_on_error=False)
            )
            if result.status == "ok":
                if result.usage:
                    self._log(f"[usage] {json.dumps(result.usage, ensure_ascii=False)}")
                return result

            error = result.error.message if result.error else "unknown error"
            category = result.error.category if result.error else "unknown"
            if not self._should_retry_agent_error(result.error):
                raise WorkflowError(f"subagent 执行失败 step={step} category={category}: {error}")
            if (not unlimited_retries) and isinstance(max_attempts, int) and attempt >= max_attempts:
                raise WorkflowError(f"subagent 执行失败 step={step} category={category}: {error}")

            delay = self._agent_retry_delay(retry_config, attempt, result.error)
            attempt_label = f"{attempt}/unlimited" if unlimited_retries else f"{attempt}/{max_attempts}"
            self._log(
                f"[agent-retry] step={step} category={category} "
                f"attempt={attempt_label} delay={delay:.1f}s error={error}"
            )
            time.sleep(delay)
            attempt += 1

        raise WorkflowError(f"subagent 执行失败 step={step}: retry loop exhausted")

    def _agent_retry_config(self, step: str) -> dict[str, float | int | None]:
        base = dict(self.config.get("agent_retry", {}))
        step_overrides = self.config.get("step_agent_retry", {}).get(step, {})
        if isinstance(step_overrides, dict):
            base.update(step_overrides)
        max_attempts_raw = base.get("max_attempts", 3)
        max_attempts: int | None
        if isinstance(max_attempts_raw, str) and max_attempts_raw.strip().lower() in {"unlimited", "infinite", "inf"}:
            max_attempts = None
        else:
            try:
                parsed_attempts = int(max_attempts_raw)
            except (TypeError, ValueError):
                parsed_attempts = 3
            max_attempts = None if parsed_attempts <= 0 else max(1, min(1000000, parsed_attempts))
        return {
            "max_attempts": max_attempts,
            "initial_delay_seconds": _coerce_float(base.get("initial_delay_seconds"), default=2.0, minimum=0.0, maximum=60.0),
            "max_delay_seconds": _coerce_float(base.get("max_delay_seconds"), default=1800.0, minimum=1.0, maximum=1800.0),
            "cloud_route_max_delay_seconds": _coerce_float(
                base.get("cloud_route_max_delay_seconds"),
                default=60.0,
                minimum=5.0,
                maximum=1800.0,
            ),
        }

    def _agent_retry_delay(self, config: dict[str, float | int], attempt: int, error: Any = None) -> float:
        initial = float(config["initial_delay_seconds"])
        maximum = float(config["max_delay_seconds"])
        if self._looks_like_cloud_route_unavailable(error):
            maximum = min(maximum, float(config.get("cloud_route_max_delay_seconds", 60.0)))
        delay = min(maximum, initial * (2 ** max(0, attempt - 1)))
        return delay + random.uniform(0, min(1.0, delay * 0.25))

    def _looks_like_cloud_route_unavailable(self, error: Any) -> bool:
        if error is None:
            return False
        text = " ".join(
            [
                str(getattr(error, "message", "") or ""),
                json.dumps(getattr(error, "details", {}) or {}, ensure_ascii=False),
            ]
        ).lower()
        markers = [
            "model_not_found",
            "无可用渠道",
            "no available channel",
            "no available distributor",
            "distributor",
        ]
        return any(marker in text for marker in markers)

    def _should_retry_agent_error(self, error: Any) -> bool:
        if error is None:
            return True
        category = str(getattr(error, "category", "") or "")
        message = str(getattr(error, "message", "") or "").lower()
        details = getattr(error, "details", {}) or {}

        if category in {"usage_limit_exceeded", "context_overflow"}:
            return False
        if category == "context_or_output_limit":
            return True
        if category in {"model_api_error", "unexpected_model_behavior", "agent_run_error", "unexpected_error"}:
            return True
        if category == "model_http_error":
            status_code = details.get("status_code") if isinstance(details, dict) else None
            try:
                status_code = int(status_code)
            except (TypeError, ValueError):
                status_code = None
            return status_code in {408, 409, 425, 429, 500, 502, 503, 504}

        transient_markers = [
            "incomplete chunked read",
            "peer closed connection",
            "connection error",
            "connection reset",
            "read timeout",
            "timeout",
            "temporarily unavailable",
            "server disconnected",
            "remote protocol error",
        ]
        return any(marker in message for marker in transient_markers)

    def _prompt_file_with_injection(self, step: str, prompt_file: Path) -> Path:
        injection = self._prompt_injection_for(step, prompt_file)
        if not injection:
            return prompt_file
        self.run_dir.mkdir(parents=True, exist_ok=True)
        prompt = prompt_file.read_text(encoding="utf-8")
        injected_prompt = (
            f"{prompt.rstrip()}\n\n"
            "==================== "
            f"{AGENT_PROMPT_INJECTION_HEADER}"
            " ====================\n"
            "这段内容由 WebUI 注入，优先级高于上文中与其冲突的细节；"
            "只用于纠正当前学院和当前最细分 agent 类型的已知错误。\n\n"
            f"{injection.strip()}\n"
            "==================== 临时纠偏提示结束 ====================\n"
        )
        path = self.run_dir / f"{prompt_file.stem}.{step}.injected.{uuid4().hex[:8]}.txt"
        path.write_text(injected_prompt, encoding="utf-8")
        self._log(f"[agent-injection] step={step} source={self._rel(prompt_file)} effective={self._rel(path)}")
        return path

    def _prompt_injection_for(self, step: str, prompt_file: Path) -> str:
        project_id = self._project_id_for_prompt(prompt_file)
        if not project_id or not self.prompt_injections_file.is_file():
            return ""
        try:
            data = json.loads(self.prompt_injections_file.read_text(encoding="utf-8"))
        except Exception:
            return ""
        if not isinstance(data, dict):
            return ""
        project_data = data.get(project_id, {})
        if not isinstance(project_data, dict):
            return ""
        item = project_data.get(step, {})
        if not isinstance(item, dict):
            return ""
        return str(item.get("content") or "").strip()

    def _project_id_for_prompt(self, prompt_file: Path) -> str:
        try:
            rel = prompt_file.resolve().relative_to(self.workspace_dir.resolve())
            if rel.parts:
                return rel.parts[0]
        except ValueError:
            pass
        try:
            active = json.loads(self.active_project_file.read_text(encoding="utf-8"))
            if isinstance(active, dict):
                return str(active.get("active_project_id") or "")
        except Exception:
            return ""
        return ""

    def _write_agent_config(
        self,
        step: str,
        prompt_file: Path,
        model_alias: str | None,
        per_step_model: bool,
    ) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        selected_model = self._select_model_alias(step, model_alias=model_alias, per_step_model=per_step_model)
        usage_limits = dict(self.config.get("usage_limits", {}))
        step_usage = self.config.get("step_usage_limits", {}).get(step, {})
        if isinstance(step_usage, dict):
            usage_limits.update(step_usage)

        data = {
            "agent": {
                "name": f"tutor-select-{step}",
                "instructions": (
                    "你是导师筛选 workflow 的子任务执行 agent。严格按本次提示词完成文件读写和网页访问。"
                    "如果 tool 返回 TOOL_ERROR，它只是工具执行反馈，不是用户的新任务；"
                    "你必须围绕当前任务修正参数后重试，或在无法继续时简短说明失败原因，"
                    "不要因此读取无关项目文档、不要切换到其他工作流阶段。"
                ),
                "stream_events": True,
                "log_tool_results": True,
                "log_preview_chars": 2000,
                "log_arg_deltas": False,
                "log_text_deltas": False,
                "log_thinking": True,
                "log_dir": str(self.project_root / "logs" / "agent_runs"),
                "tool_timeout": float(self.config["tool_limits"].get("timeout_seconds", 45)) + 10,
            },
            "model_alias": selected_model,
            "usage_limits": usage_limits,
            "context_management": self._context_management_config(),
            "tools": self._tool_configs(step),
        }
        path = self.run_dir / f"{prompt_file.stem}.{step}.{uuid4().hex[:8]}.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._write_request_debug(path, step, prompt_file, selected_model, data)
        return path

    def _write_request_debug(
        self,
        config_file: Path,
        step: str,
        prompt_file: Path,
        model_alias: str,
        config_data: dict[str, Any],
    ) -> None:
        prompt = prompt_file.read_text(encoding="utf-8")
        model_level_settings = LLMSelector(
            config_file=self.framework_root / "llm_select" / "models.yaml"
        ).get_model_settings(model_alias)
        task_level_settings = config_data.get("model_settings", {})
        debug = {
            "step": step,
            "model_alias": model_alias,
            "backend_model_config_is_in": "framework/llm_select/models.yaml",
            "agent_instructions": config_data.get("agent", {}).get("instructions"),
            "agent_system_prompt": config_data.get("agent", {}).get("system_prompt", ""),
            "prompt_file": self._rel(prompt_file),
            "prompt_preview": prompt[:4000],
            "prompt_chars": len(prompt),
            "model_level_settings": model_level_settings,
            "task_model_settings": task_level_settings,
            "effective_model_settings": _deep_merge(model_level_settings, task_level_settings),
            "usage_limits": config_data.get("usage_limits", {}),
            "tool_names": [item["name"] for item in config_data.get("tools", [])],
        }
        config_file.with_suffix(".request.json").write_text(
            json.dumps(debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _tool_configs(self, step: str | None = None) -> list[dict[str, Any]]:
        limits = self.config.get("tool_limits", {})
        web_chars_default = int(limits.get("max_web_read_chars", 100000))
        web_chars_for_step = web_chars_default
        capture_entries_for_step = int(limits.get("max_links", 300))
        if step == "explore":
            # Explore can easily drown in huge HTML/API payloads.
            # Keep responses compact so the task goal stays in-context.
            web_chars_for_step = min(web_chars_default, 20000)
            capture_entries_for_step = min(capture_entries_for_step, 80)
        allowed_globs = [
            "workflow/User/**",
            "workspace/**",
            "workflow/meta/**",
            "workflow/config/**",
            "workflow/README.md",
            "workflow/README_WORKFLOW.md",
            "workflow/ARCHITECTURE.md",
            "workflow/SKILL.md",
        ]
        workspace_root = str(self.project_root)
        file_common = {"workspace_root": workspace_root, "allowed_globs": allowed_globs}
        tools = [
            {
                "name": "filesystem.list_files",
                "config": {
                    **file_common,
                    "max_results": 5000,
                    "include_hidden": False,
                },
            },
            {
                "name": "filesystem.read_file",
                "config": {
                    **file_common,
                    "max_read_chars": int(limits.get("max_file_read_chars", 200000)),
                },
            },
            {
                "name": "filesystem.read_many",
                "config": {
                    **file_common,
                    "max_files": 20,
                    "max_read_chars_per_file": int(limits.get("max_file_read_chars", 200000)),
                    "max_total_chars": int(limits.get("max_file_read_chars", 200000)),
                },
            },
            {
                "name": "filesystem.file_info",
                "config": {
                    **file_common,
                    "max_hash_bytes": 20_000_000,
                },
            },
            {
                "name": "filesystem.search_text",
                "config": {
                    **file_common,
                    "max_results": 500,
                    "max_file_read_chars": int(limits.get("max_file_read_chars", 200000)),
                },
            },
            {
                "name": "filesystem.write_file",
                "config": {
                    **file_common,
                    "allow_write": True,
                    "max_write_chars": int(limits.get("max_file_write_chars", 500000)),
                    "create_dirs": True,
                    "overwrite": True,
                },
            },
            {
                "name": "filesystem.append_file",
                "config": {
                    **file_common,
                    "allow_write": True,
                    "max_append_chars": int(limits.get("max_file_write_chars", 500000)),
                    "create_dirs": True,
                },
            },
            {
                "name": "data.parse_json",
                "config": {"max_input_chars": int(limits.get("max_file_read_chars", 200000))},
            },
            {
                "name": "data.extract_json",
                "config": {
                    "max_input_chars": int(limits.get("max_file_read_chars", 200000)),
                    "max_results": 20,
                },
            },
            {
                "name": "data.render_template",
                "config": {
                    "max_template_chars": int(limits.get("max_file_read_chars", 200000)),
                    "max_value_chars": 50000,
                },
            },
            {
                "name": "web.fetch_url",
                "config": {
                    "max_read_chars": web_chars_for_step,
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                },
            },
            {
                "name": "web.fetch_json",
                "config": {
                    "max_read_chars": web_chars_for_step,
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                },
            },
            {
                "name": "web.extract_links",
                "config": {
                    "max_links": int(limits.get("max_links", 300)),
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                },
            },
            {
                "name": "web.post_url",
                "config": {
                    "max_read_chars": web_chars_for_step,
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                },
            },
            {
                "name": "web.search",
                "config": _without_none({
                    "max_results": int(limits.get("max_search_results", 8)),
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                    "backend": limits.get("search_backend"),
                    "searxng_url": limits.get("searxng_url"),
                    "auto_start_searxng": limits.get("auto_start_searxng"),
                }),
            },
            {
                "name": "web.download_file",
                "config": {
                    **file_common,
                    "allow_write": True,
                    "max_bytes": 10_000_000,
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                    "overwrite": True,
                },
            },
            {
                "name": "browser.render_page",
                "config": {
                    "backend": "playwright",
                    "browser_name": "chromium",
                    "headless": True,
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                    "max_html_chars": web_chars_for_step,
                    "max_text_chars": web_chars_for_step,
                    "max_links": int(limits.get("max_links", 300)),
                    "allowed_schemes": ["http", "https"],
                    # Empty list means no domain restriction; allow dynamic
                    # school URLs across different workflows/projects.
                    "allowed_domains": [],
                    "viewport_width": 1440,
                    "viewport_height": 1080,
                    "block_resource_types": ["image", "media", "font"],
                },
            },
            {
                "name": "browser.capture_requests",
                "config": {
                    "backend": "playwright",
                    "browser_name": "chromium",
                    "headless": True,
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                    "allowed_schemes": ["http", "https"],
                    "allowed_domains": [],
                    "viewport_width": 1440,
                    "viewport_height": 1080,
                    "block_resource_types": ["image", "media", "font"],
                    "allowed_resource_types": ["xhr", "fetch", "document"],
                    "include_response_body": False,
                    "max_response_body_chars": 4000,
                    "max_entries": capture_entries_for_step,
                },
            },
            {
                "name": "browser.screenshot_page",
                "config": {
                    **file_common,
                    "allow_write": True,
                    "backend": "playwright",
                    "browser_name": "chromium",
                    "headless": True,
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                    "allowed_schemes": ["http", "https"],
                    # Empty list means no domain restriction.
                    "allowed_domains": [],
                    "allowed_globs": ["workspace/**"],
                    "image_type": "png",
                    "max_image_bytes": 10_000_000,
                    "overwrite": True,
                },
            },
        ]
        tools.append(
            {
                "name": "process.run_command",
                "config": {
                    "workspace_root": workspace_root,
                    "allowed_commands": [
                        "pdftotext",
                        "pandoc",
                        "curl",
                        "grep",
                        "head",
                        "sed",
                        "awk",
                        "cut",
                        "tr",
                        "sort",
                        "uniq",
                        "wc",
                    ],
                    "timeout_seconds": float(limits.get("timeout_seconds", 45)),
                    "max_output_chars": 50000,
                },
            }
        )
        return tools

    def _select_model_alias(self, step: str, *, model_alias: str | None, per_step_model: bool) -> str:
        if model_alias:
            return model_alias
        if per_step_model:
            return str(
                self.config.get("step_model_aliases", {}).get(step)
                or self.config.get("default_model_alias")
                or "local-default"
            )
        return str(self.config.get("default_model_alias") or "local-default")

    def _context_management_config(self) -> dict[str, Any]:
        config = dict(self.config.get("context_management", {}))
        cache_dir = str(config.get("tool_result_cache_dir") or "logs/context_cache")
        cache_path = Path(cache_dir).expanduser()
        if not cache_path.is_absolute():
            cache_path = self.project_root / cache_path
        config["tool_result_cache_dir"] = str(cache_path)
        return config

    def _process_eval_task(
        self,
        task: EvalTask,
        *,
        state_file: Path,
        output_dir: Path,
        mode: str,
        model_alias: str | None,
        per_step_model: bool,
    ) -> bool:
        if self._pause_file().is_file():
            self._log(f"[{task.seq}] {task.name} — 检测到暂停信号")
            return False
        if mode != "test" and self._get_task_status(state_file, task.seq) == "done":
            self._log(f"[{task.seq}] {task.name} — 已跳过（已完成）")
            return True

        self._set_task_status(state_file, task.seq, "running")
        output_file = output_dir / f"tutor_{task.seq}_{task.name}.json"
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            self._log(f"[{task.seq}] {task.name} — 开始分析 (第{attempt}次)")
            if attempt == 1:
                prompt_text = task.prompt_file.read_text(encoding="utf-8").replace(
                    "__OUTPUT_FILE__", self._rel(output_file)
                )
                run_prompt = self.run_dir / f"run_prompt_{task.seq}_{uuid4().hex[:8]}.md"
            else:
                valid, message = self._validate_eval_json(output_file)
                prompt_text = prompts.fix_eval_json_prompt(
                    output_file=self._rel(output_file),
                    name=task.name,
                    validate_message=message if not valid else "格式有效",
                )
                run_prompt = self.run_dir / f"fix_prompt_{task.seq}_{attempt}_{uuid4().hex[:8]}.md"
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._write_text(run_prompt, prompt_text)
            try:
                self._run_agent("eval", run_prompt, model_alias=model_alias, per_step_model=per_step_model)
            except WorkflowError as exc:
                self._log(f"[{task.seq}] {task.name} — subagent 失败: {exc}")
            valid, message = self._validate_eval_json(output_file)
            if valid:
                self._set_task_status(state_file, task.seq, "done")
                self._log(f"[{task.seq}] {task.name} — ✓ 第{attempt}次通过 JSON 校验")
                return True
            self._log(f"[{task.seq}] {task.name} — ✗ JSON 校验失败 ({attempt}/{max_retries}): {message}")

        skip_log = state_file.parent / "_skip_list.txt"
        with self._state_lock:
            with skip_log.open("a", encoding="utf-8") as handle:
                handle.write(f"seq={task.seq} name={task.name} reason=JSON校验失败\n")
        self._set_task_status(state_file, task.seq, "unanalyzed")
        return False

    def _select_eval_tasks(
        self,
        mode: str,
        *,
        prompts_dir: Path,
        prompt_file: str | Path | None,
        range_from: int | None,
        range_to: int | None,
    ) -> list[EvalTask]:
        if mode == "test":
            if prompt_file is None:
                raise WorkflowError("test 模式需要 prompt_file")
            candidate = Path(prompt_file).expanduser()
            if not candidate.is_absolute():
                candidate = prompts_dir / candidate.name if not candidate.is_file() else candidate
            candidate = candidate.resolve()
            if not candidate.is_file():
                raise WorkflowError(f"prompt 文件不存在: {candidate}")
            return [self._task_from_prompt_file(candidate)]
        if mode not in {"batch", "full"}:
            raise WorkflowError(f"未知 eval 模式: {mode}")
        tasks = [self._task_from_prompt_file(path) for path in sorted(prompts_dir.glob("prompt_*.md"), key=_prompt_sort_key)]
        if mode == "batch":
            if range_from is None or range_to is None:
                raise WorkflowError("batch 模式需要 range_from 和 range_to")
            tasks = [
                task
                for task in tasks
                if task.seq.isdigit() and range_from <= int(task.seq) <= range_to
            ]
        return tasks

    def _task_from_prompt_file(self, path: Path) -> EvalTask:
        match = re.match(r"prompt_(?P<seq>\d+)_(?P<name>.+)\.md$", path.name)
        if not match:
            return EvalTask(seq="0", name=path.stem, prompt_file=path)
        return EvalTask(seq=match.group("seq"), name=match.group("name"), prompt_file=path)

    def _ensure_state_for_tasks(self, state_file: Path, tasks: list[EvalTask]) -> None:
        with self._state_lock:
            state = self._read_json(state_file) if state_file.is_file() else {"tasks": {}, "summary": {}}
            state.setdefault("tasks", {})
            for task in tasks:
                state["tasks"].setdefault(task.seq, {"status": "unanalyzed"})
            self._update_summary_in_state(state)
            self._write_json(state_file, state)

    def _init_eval_state(self, project_dir: Path, tutors: list[dict[str, Any]]) -> None:
        state_file = project_dir / "state" / "eval_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_json(state_file) if state_file.is_file() else {"tasks": {}}
        tasks: dict[str, dict[str, str]] = {}
        for idx, tutor in enumerate(tutors, 1):
            seq = str(tutor.get("序号") or idx)
            old = existing.get("tasks", {}).get(seq, {})
            status = old.get("status") if old.get("status") in {"done", "running", "checked"} else "unanalyzed"
            tasks[seq] = {"status": status}
        state = {"tasks": tasks, "summary": {}}
        self._update_summary_in_state(state)
        self._write_json(state_file, state)

    def _get_task_status(self, state_file: Path, seq: str) -> str:
        with self._state_lock:
            state = self._read_json(state_file) if state_file.is_file() else {"tasks": {}}
            return str(state.get("tasks", {}).get(seq, {}).get("status", "unanalyzed"))

    def _set_task_status(self, state_file: Path, seq: str, status: str) -> None:
        with self._state_lock:
            state = self._read_json(state_file) if state_file.is_file() else {"tasks": {}}
            state.setdefault("tasks", {}).setdefault(seq, {})["status"] = status
            self._update_summary_in_state(state)
            self._write_json(state_file, state)

    def _summarize_state(self, state_file: Path) -> dict[str, int]:
        with self._state_lock:
            state = self._read_json(state_file) if state_file.is_file() else {"tasks": {}}
            self._update_summary_in_state(state)
            self._write_json(state_file, state)
            return dict(state["summary"])

    def _update_summary_in_state(self, state: dict[str, Any]) -> None:
        tasks = state.get("tasks", {})
        total = len(tasks)
        done = sum(1 for item in tasks.values() if item.get("status") == "done")
        running = sum(1 for item in tasks.values() if item.get("status") == "running")
        checked = sum(1 for item in tasks.values() if item.get("status") == "checked")
        unanalyzed = total - done - running - checked
        state["summary"] = {
            "total": total,
            "done": done,
            "running": running,
            "checked": checked,
            "unanalyzed": max(0, unanalyzed),
        }

    def _validate_tutors_json(self, path: Path) -> tuple[bool, str]:
        if not path.is_file():
            return False, "文件不存在"
        try:
            data = self._read_json(path)
        except json.JSONDecodeError as exc:
            return False, f"JSON格式错误: {exc}"
        if not isinstance(data, list):
            return False, "必须是 JSON 数组"
        if not data:
            return False, "导师列表为空"
        errors = []
        for i, tutor in enumerate(data, 1):
            if not isinstance(tutor, dict):
                errors.append(f"第{i}项不是对象")
                continue
            name = str(tutor.get("导师姓名", "") or "")
            url = str(tutor.get("主页URL", "") or "")
            if not name:
                errors.append(f"第{i}项缺少导师姓名")
            # 允许主页URL为空：部分导师可能没有公开个人主页。
            if url and not url.startswith("http"):
                errors.append(f"第{i}项 '{name}' 主页URL格式异常: {url[:80]}")
        if errors:
            return False, "；".join(errors[:10])
        return True, f"格式合法: {len(data)} 位导师"

    def _validate_eval_json(self, path: Path) -> tuple[bool, str]:
        if not path.is_file():
            return False, "NOFILE"
        try:
            data = self._read_json(path)
        except json.JSONDecodeError as exc:
            return False, f"INVALID: {str(exc).replace(chr(10), ' ')[:100]}"
        required = [
            "序号",
            "导师姓名",
            "研究方向摘要",
            "总分",
            "优先级",
            "方向匹配_20",
            "工程系统匹配_20",
            "导师风格与氛围_20",
            "录取可行性_15",
            "经历匹配_15",
            "主页完整度_5",
            "套磁可写性_5",
            "本轮初筛说明",
            "信息留痕",
        ]
        missing = [key for key in required if key not in data]
        if missing:
            return False, "MISSING:" + ",".join(missing)
        if not isinstance(data.get("总分"), int | float):
            return False, "BADTYPE:总分不是数字"
        return True, "OK"

    def _load_workflow_config(self) -> dict[str, Any]:
        config_file = self.config_dir / "workflow.yaml"
        if not config_file.is_file():
            config = DEFAULT_CONFIG.copy()
        else:
            data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                raise WorkflowError(f"配置文件必须是 mapping: {config_file}")
            config = _deep_merge(DEFAULT_CONFIG, data)
        step_aliases = config.setdefault("step_model_aliases", {})
        if not isinstance(step_aliases, dict):
            step_aliases = {}
            config["step_model_aliases"] = step_aliases
        for step in STEP_MODEL_KEYS:
            step_aliases.setdefault(step, None)
        return config

    def _school_info(self) -> dict[str, Any]:
        school_info_file = self.workspace_dir / "school_info.json"
        if not school_info_file.is_file():
            raise WorkflowError("缺少 workspace/school_info.json")
        return self._read_json(school_info_file)

    def _project_dir(self, project_id: str | None = None) -> Path:
        if project_id is None:
            project_id = self._get_active_project()
        if not project_id:
            raise WorkflowError("项目不存在，请先运行 init-school 或设置当前激活学院")
        project_dir = self.workspace_dir / project_id
        if not project_dir.is_dir():
            raise WorkflowError(f"项目不存在: {project_id}")
        return project_dir

    def _project_info(self, project_id: str | None = None, project_dir: Path | None = None) -> dict[str, Any]:
        if project_dir is None:
            project_dir = self._project_dir(project_id)
        info_file = project_dir / "project_info.json"
        if info_file.is_file():
            info = self._read_json(info_file)
            if isinstance(info, dict):
                info.setdefault("project_id", project_dir.name)
                return info
        derived_school, derived_academy = self._split_project_id(project_dir.name)
        legacy_info: dict[str, Any] = {
            "project_id": project_dir.name,
            "school_name": derived_school,
            "academy_name": derived_academy,
            "homepage_url": "",
            "tutor_count": 0,
        }
        tutors_file = project_dir / "tutors_data.json"
        if tutors_file.is_file():
            tutors = self._read_json(tutors_file)
            if isinstance(tutors, list):
                legacy_info["tutor_count"] = len(tutors)
        self._write_project_info(project_dir, legacy_info)
        return legacy_info

    def _write_project_info(self, project_dir: Path, info: dict[str, Any]) -> None:
        self._write_json(project_dir / "project_info.json", info)

    def _set_active_project(self, project_id: str) -> None:
        self._write_json(self.active_project_file, {"project_id": project_id})

    def _get_active_project(self) -> str | None:
        if self.active_project_file.is_file():
            data = self._read_json(self.active_project_file)
            project_id = str(data.get("project_id", "") or "")
            if project_id and (self.workspace_dir / project_id).is_dir():
                return project_id
        school_info_file = self.workspace_dir / "school_info.json"
        if school_info_file.is_file():
            school_info = self._read_json(school_info_file)
            legacy_project_id = str(school_info.get("project_id", "") or "")
            if legacy_project_id and (self.workspace_dir / legacy_project_id).is_dir():
                self._set_active_project(legacy_project_id)
                return legacy_project_id
        project_dirs = [
            path.name
            for path in sorted(self.workspace_dir.iterdir(), key=lambda item: item.name)
            if path.is_dir()
            and not path.name.startswith(".")
            and ((path / "tutors_data.json").is_file() or (path / "project_info.json").is_file())
        ] if self.workspace_dir.is_dir() else []
        if len(project_dirs) == 1:
            self._set_active_project(project_dirs[0])
            return project_dirs[0]
        return None

    def activate_project(self, project_id: str) -> dict[str, Any]:
        project_dir = self.workspace_dir / project_id
        if not project_dir.is_dir():
            raise WorkflowError(f"项目不存在: {project_id}")
        self._set_active_project(project_id)
        return self._project_info(project_dir=project_dir)

    def _split_project_id(self, project_id: str) -> tuple[str, str]:
        parts = project_id.split("_", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return project_id, ""

    def _pause_file(self) -> Path:
        return self.workspace_dir / ".eval_pause"

    def _find_resume_file(self) -> Path | None:
        candidates = []
        for pattern in ["resume.*", "cv.*", "简历.*"]:
            candidates.extend(self.user_dir.glob(pattern))
        files = [path for path in candidates if path.is_file()]
        if not files:
            return None
        return max(files, key=lambda path: path.stat().st_size)

    def _prepare_resume_extraction(self, resume: Path) -> None:
        suffix = resume.suffix.lower()
        if suffix in {".txt", ".md", ".tex", ".json"}:
            return
        output = self.meta_dir / "_resume_extracted.txt"
        if suffix == ".pdf" and shutil.which("pdftotext"):
            completed = subprocess.run(
                ["pdftotext", str(resume), "-"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                self._write_text(output, completed.stdout)
                return
        if suffix in {".docx", ".doc"} and shutil.which("pandoc"):
            completed = subprocess.run(
                ["pandoc", str(resume), "-t", "plain"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                self._write_text(output, completed.stdout)
                return
        self._log(f"⚠ 简历格式 {suffix} 未能预提取，subagent 可能无法直接读取二进制内容: {self._rel(resume)}")

    def _collect_explore_reports(self, explore_dir: Path) -> str:
        parts = []
        for path in sorted(explore_dir.glob("test_tutor_*.md"), key=_eval_file_sort_key):
            parts.append(f"\n\n---\n\n### {path.name}\n\n{path.read_text(encoding='utf-8')}")
        return "".join(parts)

    def _is_effective_explore_report(self, path: Path) -> bool:
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
        return len(text) > 200 and any(marker in text for marker in ["✅", "可获取", "有，", "信息获取策略"])

    def _read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return str(path)

    def _log(self, message: str) -> None:
        print(message, flush=True)


def _safe_filename(value: str) -> str:
    cleaned = value.replace("/", "_").replace("\\", "_").replace(" ", "")
    return re.sub(r"[\x00-\x1f]", "", cleaned) or "未知"


def _prompt_sort_key(path: Path) -> tuple[int, str]:
    match = re.match(r"prompt_(\d+)_", path.name)
    return (int(match.group(1)) if match else 999999, path.name)


def _eval_file_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"_(\d+)_", path.name)
    return (int(match.group(1)) if match else 999999, path.name)


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def _coerce_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def _without_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in base.items():
        result[key] = _deep_merge(value, {}) if isinstance(value, dict) else value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
