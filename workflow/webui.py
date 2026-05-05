#!/usr/bin/env python3
"""webui.py — 导师筛选系统 Web UI（Python 标准库，零依赖）"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
FRAMEWORK_ROOT = os.path.join(PROJECT_ROOT, "framework")
if FRAMEWORK_ROOT not in sys.path:
    sys.path.insert(0, FRAMEWORK_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from workflow.workflow import TutorSelectWorkflow, WorkflowError

HOST = "0.0.0.0"
PORT = int(os.environ.get("WEBUI_PORT", "8897"))

# 后台任务状态
_running_tasks = {}  # task_id -> {thread, cmd, label, lines, exit_code, done}
_current_task_id = None  # 当前最后一个启动的任务 ID
_eval_task_active = False  # eval 任务是否在运行中
MAX_TASK_LINES = 2000
STATUS_TAIL_LINES = 300
HEARTBEAT_INTERVAL_SECONDS = 15
WORKFLOW = TutorSelectWorkflow(PROJECT_ROOT)


# ── 后台任务执行器 ──


def _safe_load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except json.JSONDecodeError as e:
        return None, f"invalid_json: {e}"
    except Exception as e:
        return None, str(e)


def _safe_count_json_list(path):
    data, error = _safe_load_json(path)
    if error:
        return 0, error
    if isinstance(data, list):
        return len(data), None
    return 0, "not_a_list"


def _sanitize_school_config_data(data):
    if not isinstance(data, dict):
        return data
    cleaned = dict(data)
    cleaned.pop("project_id", None)
    cleaned.pop("tutor_count", None)
    return cleaned


def get_projects_payload():
    try:
        status = WORKFLOW.status()
        return {
            "active_project_id": status.get("active_project_id"),
            "projects": status.get("available_projects", []),
        }
    except Exception as e:
        return {"active_project_id": None, "projects": [], "error": str(e)}


def set_active_project(project_id):
    try:
        info = WORKFLOW.activate_project(project_id)
        return {"success": True, "project": info}
    except WorkflowError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def background_runner(task_id, argv, label):
    """在后台线程执行命令，逐行捕获输出"""
    global _eval_task_active
    _running_tasks[task_id] = {
        "cmd": label,
        "lines": [],
        "line_count": 0,
        "error_lines": [],
        "exit_code": None,
        "done": False,
        "started_at": time.time(),
    }
    try:
        task_env = {
            **os.environ,
            "PYTHONPATH": (
                FRAMEWORK_ROOT
                + os.pathsep
                + PROJECT_ROOT
                + os.pathsep
                + os.environ.get("PYTHONPATH", "")
            ),
        }

        proc = subprocess.Popen(
            argv,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=task_env,
        )
        output_queue = queue.Queue()

        def reader(stream, stream_name):
            try:
                for line in stream:
                    output_queue.put((stream_name, line.rstrip("\n")))
            finally:
                try:
                    stream.close()
                except:
                    pass

        threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True).start()

        last_heartbeat = 0.0
        while True:
            had_data = False
            while True:
                try:
                    stream_name, line = output_queue.get_nowait()
                except queue.Empty:
                    break
                had_data = True
                _append_task_line(task_id, line, stream_name=stream_name)

            # 检测暂停信号
            if _eval_task_active and os.path.isfile(
                EVAL_PAUSE_FILE
                if "EVAL_PAUSE_FILE" in globals()
                else os.path.join(PROJECT_ROOT, "workspace", ".eval_pause")
            ):
                _append_task_line(task_id, "[⏹ 检测到暂停信号]")
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except:
                        proc.kill()
                except:
                    pass
                break

            if proc.poll() is not None:
                drain_until = time.time() + 1.0
                while time.time() < drain_until:
                    try:
                        stream_name, line = output_queue.get(timeout=0.05)
                        _append_task_line(task_id, line, stream_name=stream_name)
                    except queue.Empty:
                        break
                break

            if not had_data:
                now = time.time()
                if now - last_heartbeat > HEARTBEAT_INTERVAL_SECONDS:
                    elapsed = int(now - _running_tasks[task_id].get("started_at", now))
                    _append_task_line(task_id, f"[⏳ 推理中... {elapsed}s]")
                    last_heartbeat = now
                time.sleep(0.2)

        _running_tasks[task_id]["exit_code"] = proc.returncode
        # 只在当前 task 是自己时清空 _eval_task_active（防止被恢复的旧 task 覆盖）
        if _eval_task_active and ("全量分析" in label or "恢复" in label):
            # 检查有没有新任务已经启动
            last = _current_task_id
            if last == task_id:
                _eval_task_active = False
    except Exception as e:
        _append_task_line(task_id, f"ERROR: {type(e).__name__}: {e}", stream_name="stderr")
        _running_tasks[task_id]["exit_code"] = -1
    finally:
        _running_tasks[task_id]["done"] = True


def _append_task_line(task_id, line, stream_name="stdout"):
    task = _running_tasks.get(task_id)
    if not task:
        return
    text = str(line)
    if stream_name == "stderr" and text:
        text = "[stderr] " + text
    task["line_count"] = task.get("line_count", 0) + 1
    task["lines"].append(text)
    if _looks_like_error_line(text):
        task.setdefault("error_lines", []).append(text)
        task["error_lines"] = task["error_lines"][-80:]
    if len(task["lines"]) > MAX_TASK_LINES:
        task["lines"] = task["lines"][-MAX_TASK_LINES:]


def _looks_like_error_line(line):
    markers = [
        "ERROR",
        "Traceback",
        "Exception",
        "WorkflowError",
        "ModelHTTPError",
        "ModelAPIError",
        "UsageLimitExceeded",
        "context_overflow",
        "✗",
        "失败",
        "错误",
        "[stderr]",
    ]
    return any(marker in line for marker in markers)


def start_task(cmd, label):
    """启动后台任务，返回 task_id"""
    task_id = f"task-{int(time.time()*1000)}"
    global _current_task_id
    _current_task_id = task_id
    venv_python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    py = venv_python if os.path.isfile(venv_python) else (sys.executable or "python3")
    known = {
        "build-profile": [py, "-m", "workflow", "--per-step-model", "build-profile"],
        "init-school": [py, "-m", "workflow", "--per-step-model", "init-school"],
        "explore": [py, "-m", "workflow", "--per-step-model", "explore"],
        "condense": [py, "-m", "workflow", "--per-step-model", "condense-pattern"],
        "gen-prompts": [py, "-m", "workflow", "--per-step-model", "gen-prompts"],
        "full": [py, "-m", "workflow", "--per-step-model", "full"],
        "report": [py, "-m", "workflow", "--per-step-model", "report"],
        "status": [py, "-m", "workflow", "--per-step-model", "status"],
    }
    if cmd not in known:
        _running_tasks[task_id] = {"cmd": cmd, "lines": ["未知命令"], "exit_code": -1, "done": True}
        return task_id

    if cmd == "full":
        global _eval_task_active
        _eval_task_active = True
    t = threading.Thread(target=background_runner, args=(task_id, known[cmd], label), daemon=True)
    t.start()
    return task_id


def get_task_status(task_id):
    """返回任务状态"""
    t = _running_tasks.get(task_id)
    if not t:
        return {"done": True, "exit_code": -1, "lines": ["任务未找到"]}
    lines = t["lines"][-STATUS_TAIL_LINES:]
    line_count = t.get("line_count", len(t["lines"]))
    tail_start = max(0, line_count - len(lines))
    return {
        "done": t["done"],
        "exit_code": t["exit_code"],
        "cmd": t["cmd"],
        "lines": lines,
        "line_count": line_count,
        "tail_start": tail_start,
        "error_lines": t.get("error_lines", [])[-40:],
    }


# ── 状态 / 工具函数 ──


def get_project_status():
    try:
        s = WORKFLOW.status()
    except Exception as e:
        s = {
            "school": None,
            "academy": None,
            "project_id": None,
            "active_project_id": None,
            "homepage_url": None,
            "tutor_count": 0,
            "done_count": 0,
            "prompt_count": 0,
            "has_profile": False,
            "has_favor": False,
            "project_ready": False,
            "file_checks": {},
            "available_projects": [],
            "warnings": [str(e)],
        }
    else:
        s["warnings"] = []

    pf = os.path.join(ROOT, "User", "profile.md")
    s["profile_lines"] = 0
    if os.path.isfile(pf):
        with open(pf, encoding="utf-8") as f:
            s["profile_lines"] = len(f.readlines())
    s["pid"] = s.get("project_id")
    s["url"] = s.get("homepage_url")
    return s


def list_tutor_outputs():
    s = get_project_status()
    pid = s.get("pid")
    if not pid:
        return []
    odir = os.path.join(PROJECT_ROOT, "workspace", pid, "output", "full")
    if not os.path.isdir(odir):
        return []
    results = []
    for fn in sorted(os.listdir(odir)):
        if fn.endswith(".json"):
            fp = os.path.join(odir, fn)
            try:
                d, error = _safe_load_json(fp)
                if error or not isinstance(d, dict):
                    continue
                results.append({
                    "id": d.get("序号", ""),
                    "name": d.get("导师姓名", ""),
                    "score": d.get("总分", 0),
                    "rank": d.get("优先级", ""),
                    "direction": d.get("方向匹配_20", 0),
                    "engineering": d.get("工程系统匹配_20", 0),
                    "style": d.get("导师风格与氛围_20", 0),
                    "admission": d.get("录取可行性_15", 0),
                    "experience": d.get("经历匹配_15", 0),
                    "info_complete": d.get("主页完整度_5", 0),
                    "email_worthy": d.get("套磁可写性_5", 0),
                    "summary": d.get("本轮初筛说明", ""),
                })
            except Exception:
                pass
    return results


def get_token_summary():
    # pydantic-ai runs are now launched through agent_router, not OpenClaw
    # sessions. Keep the original frontend card shape and report best-effort
    # aggregate usage from completed task lines when present.
    total_inp, total_out, total_tok = 0, 0, 0
    token_re = re.compile(r"[\"']?(input|output|total)_tokens[\"']?:\s*(\d+)")
    for task in _running_tasks.values():
        for line in task.get("lines", []):
            for key, value in token_re.findall(line):
                amount = int(value)
                if key == "input":
                    total_inp += amount
                elif key == "output":
                    total_out += amount
                elif key == "total":
                    total_tok += amount
    return {
        "input": total_inp,
        "output": total_out,
        "total": total_tok or total_inp + total_out,
        "sessions": len(_running_tasks),
    }

# ── 模型选择 ──

WORKFLOW_CONFIG_FILE = os.path.join(ROOT, "config", "workflow.yaml")
LLM_CONFIG_FILE = os.path.join(FRAMEWORK_ROOT, "llm_select", "models.yaml")

# 步骤名映射 — 前端显示名 → workflow.yaml key
STEP_KEYS = [
    ("build-profile", "build-profile"),
    ("init-school", "init-school"),
    ("explore", "explore"),
    ("condense", "condense-pattern"),
    ("gen-prompts", "gen-prompts"),
    ("full", "eval"),
    ("report", "audit"),
]


def get_model_config():
    """读取 workflow.yaml 中的每步骤模型别名配置"""
    try:
        cfg = _read_workflow_config()
        step_aliases = cfg.get("step_model_aliases", {})
        return {config_key: step_aliases.get(config_key, "") for _, config_key in STEP_KEYS}
    except:
        return {}


def save_model_config(cfg):
    """保存 workflow.yaml 中的每步骤模型别名配置"""
    import tempfile
    os.makedirs(os.path.dirname(WORKFLOW_CONFIG_FILE), exist_ok=True)
    tmp = tempfile.mktemp(suffix=".tmp", dir=os.path.dirname(WORKFLOW_CONFIG_FILE))
    try:
        workflow_cfg = _read_workflow_config()
        step_aliases = workflow_cfg.setdefault("step_model_aliases", {})
        for _, config_key in STEP_KEYS:
            if config_key in cfg:
                step_aliases[config_key] = cfg.get(config_key, "") or ""
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(workflow_cfg, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, WORKFLOW_CONFIG_FILE)
        return {"success": True}
    except Exception as e:
        try:
            os.unlink(tmp)
        except:
            pass
        return {"error": str(e)}


def get_available_models():
    """从 framework/llm_select/models.yaml 配置读取可用模型别名列表"""
    result = []
    try:
        with open(LLM_CONFIG_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        models = cfg.get("models", {})
        for alias, item in models.items():
            if not isinstance(item, dict):
                continue
            provider = item.get("provider", "")
            name = item.get("name", alias)
            base_url = item.get("base_url") or ""
            label = f"{alias} → {name}"
            if provider:
                label += f" [{provider}]"
            result.append({
                "id": alias,
                "name": label,
                "context": item.get("context_window", base_url or "?"),
            })
    except Exception as e:
        sys.stderr.write(f"  [webui] models error: {e}\n")
        sys.stderr.flush()

    def sort_key(x):
        if x["id"] == _default_model_id():
            return (0, x["id"])
        if "local" in x["id"]:
            return (1, x["id"])
        return (2, x["id"])
    result.sort(key=sort_key)
    return result


def _default_model_id():
    """从 workflow.yaml 或 framework/llm_select/models.yaml 读取默认模型别名"""
    try:
        cfg = _read_workflow_config()
        if cfg.get("default_model_alias"):
            return cfg.get("default_model_alias", "")
        with open(LLM_CONFIG_FILE, encoding="utf-8") as f:
            llm_cfg = yaml.safe_load(f) or {}
        return llm_cfg.get("default_alias", "")
    except:
        return ""


def get_step_models():
    """获取所有步骤的模型配置"""
    cfg = get_model_config()
    result = {}
    for ui_key, config_key in STEP_KEYS:
        result[ui_key] = cfg.get(config_key, "")
    return result


def set_step_model(ui_key, model_id):
    """设置某个步骤的模型"""
    cfg = get_model_config()
    for uk, ck in STEP_KEYS:
        if uk == ui_key:
            cfg[ck] = model_id
            break
    else:
        return {"error": f"unknown step: {ui_key}"}
    return save_model_config(cfg)


def _read_workflow_config():
    if not os.path.isfile(WORKFLOW_CONFIG_FILE):
        return {
            "default_model_alias": _read_llm_default_alias(),
            "step_model_aliases": {},
        }
    with open(WORKFLOW_CONFIG_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {"default_model_alias": _read_llm_default_alias(), "step_model_aliases": {}}
    data.setdefault("default_model_alias", _read_llm_default_alias())
    data.setdefault("step_model_aliases", {})
    return data


def _read_llm_default_alias():
    try:
        with open(LLM_CONFIG_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("default_alias", "")
    except:
        return ""


def get_tutor_detail(seq):
    s = get_project_status()
    pid = s.get("pid")
    if not pid:
        return {"error": "no project"}
    odir = os.path.join(PROJECT_ROOT, "workspace", pid, "output", "full")
    for fn in os.listdir(odir):
        if fn.endswith(".json") and any(fn.startswith(f"tutor_{seq}_") for seq in [seq, f"{seq}_", f"tutor_{seq}"]):
            d, error = _safe_load_json(os.path.join(odir, fn))
            if error:
                return {"error": f"invalid result json: {error}"}
            return d
    # 宽松匹配
    for fn in os.listdir(odir):
        if fn.endswith(".json"):
            with open(os.path.join(odir, fn)) as f:
                try:
                    d = json.load(f)
                    if str(d.get("序号", "")) == str(seq):
                        return d
                except:
                    pass
    return {"error": "not found"}


# ── 可编辑文件 ──

EDITABLE_FILES = [
    {"key": "profile", "path": "User/profile.md", "label": "📄 profile.md（个人档案）", "syntax": "markdown"},
    {"key": "favor", "path": "User/tutor_favor.json", "label": "⭐ tutor_favor.json（导师偏好）", "syntax": "json"},
    {"key": "school-config", "path": "workspace/school_info.json", "label": "🏫 school_info.json（初始化配置）", "syntax": "json"},
    {"key": "tutors", "path": None, "dynamic": True, "dynamic_kind": "tutors",
     "label": "👥 当前学院 tutors_data.json", "syntax": "json"},
]


def _resolve_file(key):
    for ef in EDITABLE_FILES:
        if ef["key"] != key:
            continue
        if ef.get("dynamic"):
            status = get_project_status()
            pid = status.get("pid")
            if pid and ef.get("dynamic_kind") == "tutors":
                p = os.path.join(PROJECT_ROOT, "workspace", pid, "tutors_data.json")
                if os.path.isfile(p):
                    return p
            return None
        absolute = os.path.join(PROJECT_ROOT, ef["path"]) if ef["path"].startswith("workspace/") else os.path.join(ROOT, ef["path"])
        return absolute if os.path.isfile(absolute) else None
    return None


def list_editable_files():
    """返回可编辑文件列表（含状态）"""
    result = []
    for ef in EDITABLE_FILES:
        fp = _resolve_file(ef["key"])
        result.append({
            "key": ef["key"],
            "label": ef["label"],
            "syntax": ef["syntax"],
            "exists": fp is not None,
        })
    return {"files": result}


def read_editable_file(key):
    fp = _resolve_file(key)
    if not fp:
        return {"error": "文件不存在"}
    try:
        if key == "school-config":
            data, error = _safe_load_json(fp)
            if error:
                return {"error": f"读取失败: {error}"}
            content = json.dumps(_sanitize_school_config_data(data), ensure_ascii=False, indent=2)
        else:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
        return {"key": key, "content": content, "path": fp}
    except Exception as e:
        return {"error": f"读取失败: {e}"}


def save_editable_file(key, content):
    fp = _resolve_file(key)
    if not fp:
        return {"error": "文件不存在"}
    try:
        # 如果是 JSON 文件，先验证合法性
        for ef in EDITABLE_FILES:
            if ef["key"] == key and ef["syntax"] == "json":
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as e:
                    return {"error": f"JSON 格式错误: {e}"}
                if key == "school-config":
                    parsed = _sanitize_school_config_data(parsed)
                    content = json.dumps(parsed, ensure_ascii=False, indent=2)
                break
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        return {"key": key, "success": True, "path": fp}
    except Exception as e:
        return {"error": f"保存失败: {e}"}


# ── Eval 进度 / 暂停恢复 ──

EVAL_PAUSE_FILE = os.path.join(PROJECT_ROOT, "workspace", ".eval_pause")
EVAL_RESUME_FILE = os.path.join(PROJECT_ROOT, "workspace", ".eval_resume")


def get_eval_progress():
    """读取 eval_state.json 返回进度"""
    status = get_project_status()
    pid = status.get("pid")
    if not pid:
        return {"total": 0, "done": 0, "running": 0, "unanalyzed": 0, "all_done": True, "paused": False, "active": _eval_task_active}
    state_file = os.path.join(PROJECT_ROOT, "workspace", pid, "state", "eval_state.json")
    if not os.path.isfile(state_file):
        return {"total": 0, "done": 0, "running": 0, "unanalyzed": 0, "all_done": True, "paused": False, "active": _eval_task_active}

    paused = os.path.isfile(EVAL_PAUSE_FILE)
    state, error = _safe_load_json(state_file)
    if error or not isinstance(state, dict):
        return {"total": 0, "done": 0, "running": 0, "unanalyzed": 0, "all_done": True, "paused": paused, "active": _eval_task_active, "warning": f"eval_state.json: {error or 'invalid_state'}"}
    summary = state.get("summary", {})
    total = summary.get("total", 0)
    done = summary.get("done", 0)
    running = summary.get("running", 0)
    unanalyzed = total - done - running
    all_done = done >= total if total > 0 else True
    return {
        "total": total,
        "done": done,
        "running": running,
        "unanalyzed": max(0, unanalyzed),
        "all_done": all_done,
        "paused": paused,
        "active": _eval_task_active,
        "percent": round(done / total * 100, 1) if total > 0 else 0,
    }


def start_eval():
    """清除暂停标记，前端随后通过 runCmd 启动任务"""
    for f in [EVAL_PAUSE_FILE, EVAL_RESUME_FILE]:
        try:
            os.unlink(f)
        except:
            pass
    return {"success": True}


def pause_eval():
    """发送暂停信号：写暂停标记文件"""
    global _eval_task_active
    try:
        with open(EVAL_PAUSE_FILE, "w") as f:
            f.write("pause\n")
        _eval_task_active = False
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


def resume_eval():
    """发送恢复信号：清除暂停标记"""
    try:
        with open(EVAL_RESUME_FILE, "w") as f:
            f.write("resume\n")
        try:
            os.unlink(EVAL_PAUSE_FILE)
        except:
            pass
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


# ── HTTP Handler ──


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/status":
            self.json_response(get_project_status())
        elif path == "/api/results":
            self.json_response(list_tutor_outputs())
        elif path == "/api/tokens":
            self.json_response(get_token_summary())
        elif path == "/api/run":
            cmd = params.get("cmd", [None])[0]
            label = params.get("label", [cmd])[0]
            if cmd:
                task_id = start_task(cmd, label)
                self.json_response({"task_id": task_id})
            else:
                self.json_response({"error": "missing cmd"})
        elif path == "/api/run-status":
            task_id = params.get("task_id", [None])[0]
            if task_id:
                self.json_response(get_task_status(task_id))
            else:
                self.json_response({"error": "missing task_id"})
        elif path == "/api/current-task":
            self.json_response({"task_id": _current_task_id})
        elif path == "/api/editable-files":
            self.json_response(list_editable_files())
        elif path == "/api/eval-progress":
            self.json_response(get_eval_progress())
        elif path == "/api/projects":
            self.json_response(get_projects_payload())
        elif path == "/api/available-models":
            self.json_response({"models": get_available_models(), "step_models": get_step_models(), "default_model": _default_model_id()})
        elif path == "/api/read-file":
            key = params.get("key", [None])[0]
            if key:
                self.json_response(read_editable_file(key))
            else:
                self.json_response({"error": "missing key"})
        elif path.startswith("/api/tutor/"):
            seq = path.split("/")[-1]
            self.json_response(get_tutor_detail(seq))
        elif path == "/" or path == "":
            self.serve_index()
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            cmd = data.get("cmd", "")
            label = data.get("label", cmd)
            if cmd:
                task_id = start_task(cmd, label)
                self.json_response({"task_id": task_id})
            else:
                self.json_response({"error": "missing cmd"})
        elif path == "/api/save-file":
            key = data.get("key", "")
            content = data.get("content", "")
            if key:
                result = save_editable_file(key, content)
                self.json_response(result)
            else:
                self.json_response({"error": "missing key"})
        elif path == "/api/eval-start":
            self.json_response(start_eval())
        elif path == "/api/eval-pause":
            self.json_response(pause_eval())
        elif path == "/api/eval-resume":
            self.json_response(resume_eval())
        elif path == "/api/active-project":
            project_id = data.get("project_id", "")
            if project_id:
                self.json_response(set_active_project(project_id))
            else:
                self.json_response({"error": "missing project_id"})
        elif path == "/api/set-step-model":
            step = data.get("step", "")
            model_id = data.get("model", "")
            if step:
                self.json_response(set_step_model(step, model_id))
            else:
                self.json_response({"error": "missing step"})
        else:
            self.send_error(404)

    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def serve_index(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(INDEX_HTML.encode())

    def log_message(self, format, *args):
        msg = args[0] if args else ""
        sys.stderr.write(f"[WEBUI] {msg}\n")


# ── 内嵌 HTML ──


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>导师筛选系统</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
body{background:#f5f7fa;color:#333;padding:20px;max-width:1200px;margin:0 auto}
h1{font-size:22px;margin-bottom:16px}
.card{background:#fff;border-radius:10px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h2{font-size:15px;color:#555;margin-bottom:10px;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.stat{text-align:center;padding:10px;background:#f8f9fb;border-radius:8px}
.stat .v{font-size:20px;font-weight:700;color:#2563eb}
.stat .l{font-size:11px;color:#888;margin-top:2px}
.btn{padding:7px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;transition:.2s}
.btn-primary{background:#2563eb;color:#fff}.btn-primary:hover{background:#1d4ed8}
.btn-secondary{background:#e5e7eb;color:#333}.btn-secondary:hover{background:#d1d5db}
.btn-danger{background:#ef4444;color:#fff}.btn-danger:hover{background:#dc2626}
.btn:disabled{opacity:.5;cursor:not-allowed;position:relative}
.btn:disabled::after{content:' ⏳'}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
#outputBox{background:#1e293b;color:#e2e8f0;padding:14px;border-radius:8px;font-family:monospace;font-size:13px;line-height:1.5;max-height:350px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;margin-top:10px;display:none}
#outputBox .t-info{color:#60a5fa}#outputBox .t-ok{color:#34d399}#outputBox .t-err{color:#f87171}#outputBox .t-warn{color:#fbbf24}#outputBox .t-tok{color:#c084fc}
#progressBar{height:4px;background:#e5e7eb;border-radius:2px;margin-top:8px;overflow:hidden;display:none}
#progressBarIn{height:100%;background:#2563eb;border-radius:2px;transition:width .5s;width:0%}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid #eee}
th{color:#666;font-weight:600;position:sticky;top:0;background:#f8f9fb;font-size:12px}
tr:hover{background:#f8f9fb}
.rank-S{color:#059669;font-weight:700}.rank-A{color:#2563eb;font-weight:600}.rank-B{color:#ca8a04;font-weight:600}.rank-C{color:#ea580c}.rank-D{color:#dc2626}
.score{font-weight:600}
.token-bar{height:5px;background:#e5e7eb;border-radius:3px;overflow:hidden;margin-top:4px}
.token-bar-in{height:100%;background:#2563eb;border-radius:3px;transition:width 1s}
.loading{text-align:center;padding:20px;color:#999;font-size:13px}
.tag{padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600}
.tag-green{background:#d1fae5;color:#065f46}.tag-blue{background:#dbeafe;color:#1e40af}.tag-yellow{background:#fef3c7;color:#92400e}.tag-red{background:#fee2e2;color:#991b1b}.tag-gray{background:#f3f4f6;color:#6b7280}
</style>
</head>
<body>
<h1>🔧 导师筛选系统</h1>

<div class="card">
  <h2>📊 项目状态 <span id="statusTime" style="font-weight:normal;font-size:12px;color:#999;margin-left:8px"></span></h2>
  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
    <label for="activeProjectSelect" style="font-size:13px;color:#555;font-weight:600">当前激活学院</label>
    <select id="activeProjectSelect" style="min-width:280px;padding:6px 10px;border-radius:6px;border:1px solid #d1d5db;background:#fff"></select>
    <span id="activeProjectMeta" style="font-size:12px;color:#777"></span>
  </div>
  <div id="statusLoading" class="loading">加载中...</div>
  <div id="statusContent" style="display:none">
    <div class="grid" id="statGrid"></div>
    <div id="fileChecks" style="margin-top:8px;font-size:12px;color:#666"></div>
  </div>
</div>

<div class="card">
  <h2>🎯 操作</h2>
  <div class="actions" style="flex-direction:column;gap:6px">
    <div style="display:flex;align-items:center;gap:8px">
      <button class="btn btn-primary" data-cmd="build-profile" style="min-width:150px">📄 构建个人档案</button>
      <select data-step="build-profile" class="step-model-select" style="font-size:11px;padding:3px 6px;border-radius:5px;border:1px solid #c7d2fe;background:#fff;max-width:220px"></select>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <button class="btn btn-primary" data-cmd="init-school" style="min-width:150px">🏫 初始化学校</button>
      <select data-step="init-school" class="step-model-select" style="font-size:11px;padding:3px 6px;border-radius:5px;border:1px solid #c7d2fe;background:#fff;max-width:220px"></select>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <button class="btn btn-secondary" data-cmd="explore" style="min-width:150px">🔍 页面探索</button>
      <select data-step="explore" class="step-model-select" style="font-size:11px;padding:3px 6px;border-radius:5px;border:1px solid #c7d2fe;background:#fff;max-width:220px"></select>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <button class="btn btn-secondary" data-cmd="condense" style="min-width:150px">📝 精简策略</button>
      <select data-step="condense" class="step-model-select" style="font-size:11px;padding:3px 6px;border-radius:5px;border:1px solid #c7d2fe;background:#fff;max-width:220px"></select>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <button class="btn btn-secondary" data-cmd="gen-prompts" style="min-width:150px">📋 生成 Prompt</button>
      <select data-step="gen-prompts" class="step-model-select" style="font-size:11px;padding:3px 6px;border-radius:5px;border:1px solid #c7d2fe;background:#fff;max-width:220px"></select>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <button class="btn btn-secondary" data-cmd="report" style="min-width:150px">📊 汇总报告</button>
      <select data-step="report" class="step-model-select" style="font-size:11px;padding:3px 6px;border-radius:5px;border:1px solid #c7d2fe;background:#fff;max-width:220px"></select>
    </div>
  </div>

  <!-- 全量分析专用控制 -->
  <div id="evalControl" style="margin-top:10px;padding:10px;background:#f0f4ff;border-radius:8px;border:1px solid #c7d2fe">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <span style="font-weight:600;font-size:13px">▶ 全量分析</span>
      <span id="evalProgressText" style="font-size:13px;color:#555"></span>
      <div id="evalProgressBar" style="flex:1;min-width:120px;height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden">
        <div id="evalProgressBarIn" style="height:100%;background:#2563eb;border-radius:4px;transition:width .5s;width:0%"></div>
      </div>
      <span id="evalPercent" style="font-size:12px;font-weight:600;color:#2563eb;min-width:40px">0%</span>
      <select data-step="full" class="step-model-select" style="font-size:12px;padding:4px 8px;border-radius:6px;border:1px solid #c7d2fe;background:#fff;max-width:200px"></select>
      <button id="evalStartBtn" class="btn btn-primary" style="font-size:12px;padding:4px 12px">▶ 开始</button>
      <button id="evalPauseBtn" class="btn btn-secondary" style="font-size:12px;padding:4px 12px;display:none">⏸ 暂停</button>
      <button id="evalResumeBtn" class="btn btn-primary" style="font-size:12px;padding:4px 12px;display:none">▶ 恢复</button>
    </div>
  </div>

  <div id="progressBar"><div id="progressBarIn"></div></div>
  <div id="outputBox"></div>
</div>

<div class="card">
  <h2>🧾 Token 用量</h2>
  <div id="tokenDisplay" class="loading">加载中...</div>
</div>

<div class="card">
  <h2>📝 文件编辑</h2>
  <div id="fileEditorLoading" class="loading">加载中...</div>
  <div id="fileEditorContent" style="display:none">
    <div id="fileTabs" style="display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap"></div>
    <div style="display:flex;gap:8px">
      <textarea id="fileEditor" spellcheck="false"
        style="flex:1;min-height:250px;background:#1e293b;color:#e2e8f0;padding:10px;border-radius:6px;font-family:monospace;font-size:12px;line-height:1.5;border:1px solid #334155;resize:vertical"></textarea>
    </div>
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
      <button id="saveFileBtn" class="btn btn-primary">💾 保存</button>
      <span id="saveStatus" style="font-size:12px;color:#666"></span>
    </div>
  </div>
</div>

<div class="card">
  <h2>🏆 评分结果 <span id="sortArea" style="font-weight:normal;font-size:12px;margin-left:8px">
    排序: <select id="sortSelect" style="padding:1px 4px;font-size:12px">
      <option value="score-desc">总分↓</option><option value="score-asc">总分↑</option>
      <option value="direction-desc">方向↓</option><option value="name">姓名</option>
    </select>
  </span></h2>
  <div id="resultsLoading" class="loading">加载中...</div>
  <div id="resultsContent" style="display:none">
    <div style="max-height:500px;overflow-y:auto;font-size:12px">
      <table><thead><tr>
        <th>#</th><th>导师</th><th>总分</th><th>等级</th><th>方向</th><th>工程</th><th>录取</th><th></th>
      </tr></thead><tbody id="resultsTable"></tbody></table>
    </div>
    <div id="tutorDetail" style="margin-top:10px;display:none">
      <h3 style="font-size:13px;color:#555;margin-bottom:4px">📄 导师详情</h3>
      <div id="tutorDetailContent" style="background:#1e293b;color:#e2e8f0;padding:12px;border-radius:6px;font-family:monospace;font-size:12px;line-height:1.5;max-height:400px;overflow:auto;white-space:pre-wrap"></div>
    </div>
  </div>
</div>

<script>
async function api(url, opts) {
  if (opts) {
    return (await fetch(url, opts)).json();
  } else {
    return (await fetch(url)).json();
  }
}

function escape(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

function lineClass(l) {
  return !l ? ''
    : l.includes('ERROR')||l.includes('Traceback')||l.includes('[stderr]')||l.includes('✗')||l.includes('失败')||l.includes('错误') ? 't-err'
    : l.includes('✓')||l.includes('完成') ? 't-ok'
    : l.includes('INFO')||l.includes('[agent:') ? 't-info'
    : l.includes('tok')||l.includes('Token')||l.includes('输入')||l.includes('输出')||l.includes('[usage]') ? 't-tok'
    : l.includes('WARN')||l.includes('⚠') ? 't-warn' : '';
}

function renderLines(lines) {
  return (lines || []).map(l => '<span class="' + lineClass(l) + '">' + escape(l) + '</span>\n').join('');
}

function appendTaskLines(box, st, lastCount) {
  const lines = st.lines || [];
  const tailStart = st.tail_start || Math.max(0, (st.line_count || lines.length) - lines.length);
  const lineCount = st.line_count || lines.length;
  let start = Math.max(0, lastCount - tailStart);
  if (start > lines.length) start = 0;
  const newLines = lines.slice(start);
  if (newLines.length) {
    box.innerHTML += renderLines(newLines);
    box.scrollTop = box.scrollHeight;
  }
  return lineCount;
}

let currentTaskId = null;
let taskPoller = null;

// 刷新后恢复未完成的任务
async function resumeIncompleteTask() {
  const r = await api("/api/current-task");
  if (!r.task_id) return;
  const st = await api("/api/run-status?task_id=" + r.task_id);
  if (st && st.lines && !st.done) {
    // 有正在运行的任务，恢复显示
    currentTaskId = r.task_id;
    const box = document.getElementById("outputBox");
    const bar = document.getElementById("progressBar");
    const barIn = document.getElementById("progressBarIn");
    box.style.display = "block";
    bar.style.display = "block";
    const btns = document.querySelectorAll("button");
    btns.forEach(b => b.disabled = true);
    let lastLen = st.line_count || st.lines.length;
    box.innerHTML = renderLines(st.lines) + "\n<span class=\"t-info\">\u2190 刷新后恢复</span>\n";
    barIn.style.width = Math.min(90, 5 + lastLen * 2) + "%";
    // 继续轮询
    taskPoller = setInterval(async () => {
      const s = await api("/api/run-status?task_id=" + currentTaskId);
      const nextLen = appendTaskLines(box, s, lastLen);
      if (nextLen !== lastLen) {
        lastLen = nextLen;
        barIn.style.width = Math.min(90, 5 + lastLen * 2) + "%";
      }
      if (s.done) {
        clearInterval(taskPoller);
        taskPoller = null;
        barIn.style.width = "100%";
        setTimeout(() => { bar.style.display = "none"; }, 800);
        btns.forEach(b => b.disabled = false);
        if (s.exit_code !== 0) {
          if (s.error_lines && s.error_lines.length) {
            box.innerHTML += "\n<span class=\"t-err\">===== 错误摘要 =====</span>\n" + renderLines(s.error_lines);
          }
          box.innerHTML += "\n<span class=\"t-err\">✗ exit: " + s.exit_code + "</span>";
        } else {
          box.innerHTML += "\n<span class=\"t-ok\">✓ 完成</span>";
        }
        refreshStatus();
        refreshTokens();
        refreshResults();
      }
    }, 1000);
  }
}

// ── 模型选择（per-step） ──

async function initStepModelSelects() {
  const r = await api('/api/available-models');
  if (!r.models || r.models.length === 0) return;

  const stepModels = r.step_models || {};
  const defaultModel = r.default_model || '';

  // 构建 option HTML
  const defaultOption = '<option value="">默认 (' + getModelShortName(defaultModel) + ')</option>';
  const optionsHtml = r.models.map(m =>
    '<option value="' + m.id + '">' + m.name + ' (' + m.context + ')' + '</option>'
  ).join('');

  // 初始化所有 per-step 选择器
  document.querySelectorAll('.step-model-select').forEach(sel => {
    const step = sel.dataset.step;
    const currentModel = stepModels[step] || '';
    sel.innerHTML = defaultOption + optionsHtml;
    // 选中当前配置的模型
    if (currentModel) {
      sel.value = currentModel;
    }
    // 选择变更时自动持久化到 model_config.json
    sel.onchange = async () => {
      await api('/api/set-step-model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({step: step, model: sel.value}),
      });
    };
  });
}

function getModelShortName(fullId) {
  if (!fullId) return '系统默认';
  const parts = fullId.split('/');
  return parts[parts.length - 1] || fullId;
}

// ── 文件编辑 ──

let fileEditorData = {}; // key -> {content, syntax}
let currentFileKey = null;

async function refreshProjectSelector() {
  const r = await api('/api/projects');
  const sel = document.getElementById('activeProjectSelect');
  const meta = document.getElementById('activeProjectMeta');
  if (!sel) return;
  const projects = r.projects || [];
  if (!projects.length) {
    sel.innerHTML = '<option value="">暂无项目</option>';
    sel.disabled = true;
    meta.textContent = '';
    return;
  }
  sel.disabled = false;
  sel.innerHTML = projects.map(p => {
    const label = (p.school_name || p.project_id || '未命名项目') + (p.academy_name ? ' / ' + p.academy_name : '');
    return '<option value="' + escape(p.project_id) + '">' + escape(label) + '</option>';
  }).join('');
  sel.value = r.active_project_id || projects[0].project_id;
  const active = projects.find(p => p.project_id === sel.value) || projects[0];
  meta.textContent = active ? ('导师 ' + (active.tutor_count || 0) + ' 位') : '';
  sel.onchange = async () => {
    const result = await api('/api/active-project', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({project_id: sel.value}),
    });
    if (result.error) {
      meta.textContent = '切换失败：' + result.error;
      return;
    }
    await refreshProjectSelector();
    await refreshStatus();
    await refreshResults();
    await refreshEvalProgress();
    await initFileEditor();
  };
}

async function initFileEditor() {
  const r = await api('/api/editable-files');
  if (!r.files || r.files.length === 0) {
    document.getElementById('fileEditorLoading').textContent = '暂无可编辑文件';
    return;
  }
  document.getElementById('fileTabs').innerHTML = '';
  document.getElementById('fileEditorLoading').style.display = 'none';
  document.getElementById('fileEditorContent').style.display = 'block';

  const tabs = document.getElementById('fileTabs');
  const editor = document.getElementById('fileEditor');

  // 记录所有文件的 key
  fileEditorData = {};

  for (const f of r.files) {
    fileEditorData[f.key] = { exists: f.exists, syntax: f.syntax, label: f.label };

    const tab = document.createElement('button');
    tab.className = 'btn ' + (f.exists ? 'btn-secondary' : 'btn-secondary');
    tab.style.cssText = 'font-size:12px;padding:4px 10px;' + (f.exists ? '' : 'opacity:0.6');
    tab.textContent = f.exists ? f.label : f.label + ' (暂无)';
    tab.onclick = async () => {
      if (!f.exists) return;
      await switchFile(f.key);
    };
    tabs.appendChild(tab);
  }

  // 默认打开第一个存在的文件
  const first = r.files.find(x => x.exists);
  if (first) {
    await switchFile(first.key);
  }
}

async function switchFile(key) {
  const r = await api('/api/read-file?key=' + key);
  if (r.error) {
    document.getElementById('saveStatus').textContent = '⚠ ' + r.error;
    return;
  }
  currentFileKey = key;
  const editor = document.getElementById('fileEditor');
  editor.value = r.content;
  document.getElementById('saveStatus').textContent = '';

  // 高亮当前 tab
  const tabs = document.getElementById('fileTabs');
  tabs.querySelectorAll('button').forEach((btn, i) => {
    btn.className = 'btn ' + (btn.textContent.startsWith(fileEditorData[key]?.label) ? 'btn-primary' : 'btn-secondary');
  });
}

async function saveCurrentFile() {
  if (!currentFileKey) return;
  const editor = document.getElementById('fileEditor');
  const content = editor.value;
  const btn = document.getElementById('saveFileBtn');
  const status = document.getElementById('saveStatus');

  btn.disabled = true;
  status.textContent = '⏳ 保存中...';

  const r = await api('/api/save-file', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({key: currentFileKey, content: content}),
  });

  if (r.error) {
    status.textContent = '✗ ' + r.error;
  } else {
    status.textContent = '✓ 已保存';
    setTimeout(() => { status.textContent = ''; }, 3000);
    // 刷新项目状态和评分结果
    refreshStatus();
    refreshResults();
    refreshTokens();
  }

  btn.disabled = false;
}

// ── 全量分析控制 ──

async function refreshEvalProgress() {
  const p = await api('/api/eval-progress');
  // 同时获取项目总导师数（作为 fallback 进度分母）
  const st = await api('/api/status');
  const bar = document.getElementById('evalProgressBarIn');
  const text = document.getElementById('evalProgressText');
  const pct = document.getElementById('evalPercent');
  const startBtn = document.getElementById('evalStartBtn');
  const pauseBtn = document.getElementById('evalPauseBtn');
  const resumeBtn = document.getElementById('evalResumeBtn');

  // 真实导师数优先用 eval state 的 total，fallback 到项目数据
  let total = p.total || st.tutor_count || 0;
  let done = p.done || 0;
  let running = p.running || 0;
  let paused = p.paused || false;
  let allDone = p.all_done || (total > 0 && done >= total);

  // eval_state 未完全初始化时用项目真实导师数
  if (total === 1 && st.tutor_count > 10) {
    total = st.tutor_count;
  }

  if (total === 0) {
    text.textContent = '暂无数据';
    bar.style.width = '0%';
    pct.textContent = '';
    startBtn.style.display = '';
    startBtn.textContent = "▶ 开始";
    startBtn.disabled = false;
    pauseBtn.style.display = "none";
    resumeBtn.style.display = "none";;
    pauseBtn.style.display = 'none';
    resumeBtn.style.display = 'none';
    return;
  }

  const percent = total > 0 ? Math.round(done / total * 1000) / 10 : 0;
  bar.style.width = percent + '%';
  pct.textContent = percent + '%';

  // active 直接从后端获取，服务端跟踪 task 运行状态
  const active = p.active === true;

  if (done >= total) {
    startBtn.style.display = '';
    startBtn.textContent = "▶ 重新开始";
    startBtn.disabled = false;
    pauseBtn.style.display = "none";
    resumeBtn.style.display = "none";;
    pauseBtn.style.display = 'none';
    resumeBtn.style.display = 'none';
    text.textContent = '已完成 ' + done + '/' + total + ' ✓';
  } else if (paused) {
    startBtn.style.display = 'none';
    pauseBtn.style.display = 'none';
    resumeBtn.style.display = '';
    resumeBtn.disabled = false;
    text.textContent = '已暂停 — ' + done + '/' + total + ' (⏸)';
  } else if (active) {
    startBtn.style.display = 'none';
    pauseBtn.style.display = '';
    pauseBtn.disabled = false;
    resumeBtn.style.display = 'none';
    text.textContent = '分析中... ' + done + '/' + total;
  } else {
    startBtn.style.display = '';
    startBtn.disabled = false;
    startBtn.textContent = '▶ 继续分析';
    pauseBtn.style.display = 'none';
    resumeBtn.style.display = 'none';
    text.textContent = '已分析 ' + done + '/' + total + '（就绪）';
  }
}

async function startEval() {
  // 清除暂停标记
  await api('/api/eval-start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: '{}',
  });
  // 通过 runCmd 启动真正的后台任务
  await runCmd('full', '全量分析导师');
}

async function pauseEval() {
  // 立即停止输出框轮询
  if (taskPoller) {
    clearInterval(taskPoller);
    taskPoller = null;
  }
  await api('/api/eval-pause', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: '{}',
  });
  document.getElementById('evalProgressText').textContent = '⏸ 暂停中...';
  setTimeout(refreshEvalProgress, 1500);
}

async function resumeEval() {
  // 清除暂停标记
  await api('/api/eval-resume', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: '{}',
  });
  // 通过 runCmd 启动后台任务（run_eval.sh 自动断点续跑）
  await runCmd('full', '全量分析导师');
}

// ── 执行命令 ──

async function runCmd(cmd, label) {
  const btns = document.querySelectorAll('button');
  btns.forEach(b => b.disabled = true);

  const box = document.getElementById('outputBox');
  const bar = document.getElementById('progressBar');
  const barIn = document.getElementById('progressBarIn');
  box.style.display = 'block';
  box.innerHTML = '<span class="t-info">▶ 启动: ' + escape(label) + '...</span>\n';
  bar.style.display = 'block';
  barIn.style.width = '5%';

  // 启动任务
  const r = await api('/api/run?cmd=' + encodeURIComponent(cmd) + '&label=' + encodeURIComponent(label));
  currentTaskId = r.task_id;

  // 轮询状态
  let lastLen = 0;
  taskPoller = setInterval(async () => {
    const st = await api('/api/run-status?task_id=' + currentTaskId);
    // 追加新行
    const nextLen = appendTaskLines(box, st, lastLen);
    if (nextLen !== lastLen) {
      lastLen = nextLen;
      // 进度动画
      barIn.style.width = Math.min(90, 5 + lastLen * 2) + '%';
    }
    if (st.done) {
      clearInterval(taskPoller);
      taskPoller = null;
      barIn.style.width = '100%';
      setTimeout(() => { bar.style.display = 'none'; }, 800);
      btns.forEach(b => b.disabled = false);
      if (st.exit_code !== 0) {
        if (st.error_lines && st.error_lines.length) {
          box.innerHTML += '\n<span class="t-err">===== 错误摘要 =====</span>\n' + renderLines(st.error_lines);
        }
        box.innerHTML += '\n<span class="t-err">✗ exit: ' + st.exit_code + '</span>';
      } else {
        box.innerHTML += '\n<span class="t-ok">✓ 完成</span>';
      }
      // 刷新数据
      refreshStatus();
      refreshTokens();
      refreshResults();
    }
  }, 1000);
}

// ── 状态 ──

async function refreshStatus() {
  const s = await api('/api/status');
  document.getElementById('statusLoading').style.display = 'none';
  document.getElementById('statusContent').style.display = 'block';
  document.getElementById('statusTime').textContent = '🕐 ' + new Date().toLocaleTimeString();

  const stats = [
    {v: (s.school || '未初始化') + (s.academy ? ' / ' + s.academy : ''), l: '当前学院'},
    {v: s.tutor_count, l: '导师总数'},
    {v: s.done_count + '/' + s.tutor_count, l: '已评分'},
    {v: s.prompt_count + '/' + s.tutor_count, l: 'Prompt'},
    {v: s.profile_lines + ' 行', l: '个人档案'},
  ];
  document.getElementById('statGrid').innerHTML = stats.map(x =>
    '<div class="stat"><div class="v">' + escape(String(x.v)) + '</div><div class="l">' + x.l + '</div></div>'
  ).join('');

  const fc = document.getElementById('fileChecks');
  const files = Object.entries(s.file_checks);
  if (files.length) {
    fc.innerHTML = files.map(([k,v]) =>
      '<span style="margin-right:10px">' + (v ? '✅' : '❌') + ' ' + k + '</span>'
    ).join('');
  } else fc.innerHTML = '';
}

async function refreshTokens() {
  const t = await api('/api/tokens');
  const el = document.getElementById('tokenDisplay');
  if (t.error) { el.innerHTML = '❌ ' + t.error; return; }
  const pct = t.total > 0 ? Math.min(100, (t.total / 256000) * 100) : 0;
  el.innerHTML =
    '<div style="display:flex;justify-content:space-between;font-size:12px">' +
    '<span>输入: ' + t.input.toLocaleString() + ' tok</span>' +
    '<span>输出: ' + t.output.toLocaleString() + ' tok</span>' +
    '<span>合计: ' + t.total.toLocaleString() + ' tok</span>' +
    '</div>' +
    '<div class="token-bar"><div class="token-bar-in" style="width:' + pct + '%"></div></div>' +
    '<div style="font-size:11px;color:#999;margin-top:2px">' + t.sessions + ' 个会话 · 上下文: ' + pct.toFixed(1) + '%</div>';
}

async function refreshResults() {
  const r = await api('/api/results');
  const loading = document.getElementById('resultsLoading');
  const content = document.getElementById('resultsContent');
  if (!r.length) {
    loading.textContent = '暂无评分结果';
    content.style.display = 'none';
    return;
  }
  loading.style.display = 'none';
  content.style.display = 'block';

  const s = document.getElementById('sortSelect').value;
  if (s === 'score-desc') r.sort((a,b) => b.score - a.score);
  else if (s === 'score-asc') r.sort((a,b) => a.score - b.score);
  else if (s === 'direction-desc') r.sort((a,b) => b.direction - a.direction);
  else if (s === 'name') r.sort((a,b) => a.name.localeCompare(b.name));

  const rc = {S:'rank-S',A:'rank-A',B:'rank-B',C:'rank-C',D:'rank-D'};
  const rt = {S:'tag-green',A:'tag-blue',B:'tag-yellow',C:'tag-orange',D:'tag-red'};

  document.getElementById('resultsTable').innerHTML = r.map(x =>
    '<tr><td>' + x.id + '</td>' +
    '<td><strong>' + escape(x.name) + '</strong></td>' +
    '<td class="score ' + (rc[x.rank]||'') + '">' + (x.score||'?') + '</td>' +
    '<td><span class="tag ' + (rt[x.rank]||'tag-gray') + '">' + (x.rank||'?') + '</span></td>' +
    '<td>' + (x.direction||'-') + '</td>' +
    '<td>' + (x.engineering||'-') + '</td>' +
    '<td>' + (x.admission||'-') + '</td>' +
    '<td><button class="btn btn-secondary" style="padding:2px 8px;font-size:11px" onclick="showDetail(\'' + escape(x.id) + '\')">详情</button></td></tr>'
  ).join('');
}

async function showDetail(seq) {
  const d = await api('/api/tutor/' + seq);
  const el = document.getElementById('tutorDetail');
  const ct = document.getElementById('tutorDetailContent');
  ct.textContent = JSON.stringify(d, null, 2);
  el.style.display = 'block';
}

// ── 初始化 ──

document.addEventListener('DOMContentLoaded', async () => {
  // 刷新后恢复未完成的任务
  resumeIncompleteTask();
  document.querySelectorAll('button[data-cmd]').forEach(btn => {
    btn.addEventListener('click', () => runCmd(btn.dataset.cmd, btn.textContent.trim()));
  });
  document.getElementById('sortSelect').addEventListener('change', refreshResults);
  document.getElementById('saveFileBtn').addEventListener('click', saveCurrentFile);
  document.getElementById('evalStartBtn').addEventListener('click', startEval);
  document.getElementById('evalPauseBtn').addEventListener('click', pauseEval);
  document.getElementById('evalResumeBtn').addEventListener('click', resumeEval);
  await refreshProjectSelector();
  await refreshStatus();
  await refreshTokens();
  await refreshResults();
  await initFileEditor();
  await initStepModelSelects();
  // Eval 进度轮询
  await refreshEvalProgress();
  setInterval(refreshEvalProgress, 3000);
  setInterval(refreshTokens, 30000);
  setInterval(refreshStatus, 60000);
});
</script>
</body>
</html>
"""


# ── 启动 ──


def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"\n  🌐 导师筛选系统 Web UI")
    print(f"  ┌───────────────────────────────────┐")
    print(f"  │  地址: http://localhost:{PORT}        │")
    print(f"  │  按 Ctrl+C 停止                    │")
    print(f"  └───────────────────────────────────┘\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  停止")
        server.server_close()


if __name__ == "__main__":
    main()
