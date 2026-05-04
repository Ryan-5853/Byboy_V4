from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
import yaml

from agent_router import AgentRouter, RouterRequest
from llm_select.config_loader import load_llm_config
from tool_call import ConfiguredTool, ToolCallManager, build_default_tool_registry


PROJECT_ROOT = Path(__file__).resolve().parent


PROMPT = """
你是一个用于测试工具调用连续性的网页研究 subagent。

任务：
1. 先读取入口网页：{entry_url}
2. 从入口网页中查找和 pydantic-ai OpenAI-compatible / OpenAI 模型配置相关的链接
3. 再读取你认为最相关的链接内容
4. 综合两次以上工具调用得到答案

要求：
- 必须先使用链接提取类工具，再使用网页读取类工具
- 你需要在 memory_trace 中按顺序记录你每一步看到了什么、为什么下一步这样做
- 如果某个网页读取返回 TOOL_ERROR，不要终止任务；记录失败原因，并从已经提取到的链接中选择另一个更可靠的链接继续尝试
- 不要假装读取了网页；如果工具调用失败，请在 answer 中说明失败点
- sources 必须包含实际读取过的 URL

最终输出结构字段：
- answer: 中文总结
- memory_trace: 多步查找过程记录
- sources: 使用过的 URL
- confidence: 0 到 1 之间的置信度
"""


CONFIG = {
    "agent": {
        "name": "web-memory-continuity-test",
        "system_prompt": (
            "你是一次性网页研究 worker。你的重点是验证多步工具调用和同一次运行内的"
            "上下文连续性。每次工具调用后的观察都要用于下一步决策。"
        ),
        "retries": 1,
        "output_retries": 1,
        "tool_timeout": 30,
        "output_schema": {
            "answer": "str",
            "memory_trace": "list[str]",
            "sources": "list[str]",
            "confidence": "float",
        },
        "stream_events": True,
        "log_tool_results": True,
        "log_preview_chars": 200,
        "log_arg_deltas": False,
        "log_text_deltas": False,
        "log_thinking": True,
    },
    "model_alias": "local-default",
    "model_settings": {
        "temperature": 0.2,
        "max_tokens": 12800,
    },
    "usage_limits": {
        "max_requests": 100,
        "max_tool_calls": 50,
        "max_total_tokens": "null",
    },
    "context_management": {
        "enabled": True,
        "threshold_ratio": 0.8,
        "max_context_tokens": 200000,
        "compact_model_alias": "local-default",
        "chars_per_token": 4.0,
        "keep_recent_messages": 0,
    },
    "tools": [
        {
            "name": "web.extract_links",
            "config": {
                "max_links": 80,
                "timeout_seconds": 20,
                "same_host_only": True,
                "allowed_schemes": ["http", "https"],
            },
        },
        {
            "name": "web.fetch_url",
            "config": {
                "max_read_chars": 12000,
                "timeout_seconds": 20,
                "follow_redirects": True,
                "allowed_schemes": ["http", "https"],
            },
        },
    ],
}


def print_header(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def log(message: str) -> None:
    print(message, flush=True)


def preflight_tool_call() -> None:
    """Smoke-test tool discovery and config authorization before the agent run."""
    print_header("tool_call preflight")
    registry = build_default_tool_registry()
    log("discovered tools:")
    for name in registry.names():
        log(f"- {name}")

    manager = ToolCallManager(
        [
            ConfiguredTool(
                name="web.extract_links",
                config={
                    "max_links": 5,
                    "timeout_seconds": 20,
                    "same_host_only": True,
                },
            )
        ],
        registry=registry,
    )
    log(f"allowed tools for preflight: {manager.allowed_tool_names()}")


def preflight_model_backend() -> None:
    """Check that the configured OpenAI-compatible backend is reachable."""
    print_header("llm backend preflight")
    llm_config = load_llm_config(PROJECT_ROOT / "llm_select" / "models.yaml")
    alias = CONFIG["model_alias"]
    model_config = llm_config.models[alias]
    log(f"model_alias: {alias}")
    log(f"model_name: {model_config.name}")
    log(f"provider: {model_config.provider}")

    if model_config.provider != "openai-compatible":
        log("backend probe skipped: provider is not openai-compatible")
        return
    if not model_config.base_url:
        raise RuntimeError(f"base_url is empty for model alias: {alias}")

    models_url = model_config.base_url.rstrip("/") + "/models"
    log(f"probing backend: GET {models_url}")
    try:
        response = httpx.get(
            models_url,
            headers={"Authorization": f"Bearer {model_config.api_key or 'sk-local'}"},
            timeout=5,
            trust_env=False,
        )
        log(f"backend status: {response.status_code}")
        log(f"backend response preview: {response.text[:300]}")
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            "Cannot reach model backend from this Python process. "
            "Make sure the model service is listening at llm_select/models.yaml base_url."
        ) from exc


def run_agent_test() -> None:
    print_header("agent_router multi-step web task")
    with tempfile.TemporaryDirectory(prefix="bybot_agent_router_") as temp_dir:
        temp_path = Path(temp_dir)
        prompt_file = temp_path / "prompt.md"
        config_file = temp_path / "config.yaml"
        prompt_file.write_text(PROMPT, encoding="utf-8")
        config_file.write_text(yaml.safe_dump(CONFIG, allow_unicode=True), encoding="utf-8")

        router = AgentRouter(
            base_dir=PROJECT_ROOT,
            llm_config_file=PROJECT_ROOT / "llm_select" / "models.yaml",
        )
        request = RouterRequest(
            prompt_file=prompt_file,
            config_file=config_file,
            variables={
                "entry_url": "https://ai.pydantic.dev/models/openai/",
            },
        )

        log(f"prompt_file: {prompt_file}")
        log(f"config_file: {config_file}")
        log(f"model_alias: {CONFIG['model_alias']}")
        log(f"configured tools: {[tool['name'] for tool in CONFIG['tools']]}")
        log("starting agent run...")

        result = router.run_sync(request)
        print_header("result")
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), flush=True)
        if result.status != "ok":
            print_header("manual takeover")
            log("agent run did not crash; inspect result.error and decide how to continue.")
            log(f"error category: {result.error.category if result.error else '<none>'}")
            log(f"error message: {result.error.message if result.error else '<none>'}")


def main() -> int:
    preflight_tool_call()
    preflight_model_backend()
    run_agent_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
