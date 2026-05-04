"""Run the tutor analysis test with a real faculty page."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from agent_router import AgentRouter, RouterRequest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


PROMPT_FILE = PROJECT_ROOT / "test_tutor" / "prompt_tutor.md"
CONFIG_FILE = PROJECT_ROOT / "test_tutor" / "config_tutor.yaml"


def main() -> int:
    prompt_text = PROMPT_FILE.read_text(encoding="utf-8")
    config_raw = CONFIG_FILE.read_text(encoding="utf-8")
    config_data = yaml.safe_load(config_raw)

    with tempfile.TemporaryDirectory(prefix="bybot_tutor_") as temp_dir:
        temp_path = Path(temp_dir)
        prompt_file = temp_path / "prompt.md"
        config_file = temp_path / "config.yaml"
        prompt_file.write_text(prompt_text, encoding="utf-8")
        config_file.write_text(yaml.safe_dump(config_data, allow_unicode=True), encoding="utf-8")

        router = AgentRouter(
            base_dir=PROJECT_ROOT,
            llm_config_file=PROJECT_ROOT / "llm_select" / "models.yaml",
        )
        request = RouterRequest(
            prompt_file=prompt_file,
            config_file=config_file,
            variables={
                "homepage_url": "http://faculty.hust.edu.cn/fanhuijin/zh_CN/index.htm",
            },
        )

        print("=" * 60)
        print("Starting tutor analysis...")
        print(f"model_alias: {config_data['model_alias']}")
        print(f"tools: {[t['name'] for t in config_data['tools']]}")
        print("=" * 60)

        result = router.run_sync(request)

        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)
        if result.status == "ok":
            print(json.dumps(result.output, ensure_ascii=False, indent=2))
            if result.usage:
                print(f"\nUsage: {json.dumps(result.usage, ensure_ascii=False)}")
        else:
            print(f"STATUS: {result.status}")
            if result.error:
                print(f"ERROR [{result.error.category}]: {result.error.message}")
            if result.output:
                print(f"Partial output: {result.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
