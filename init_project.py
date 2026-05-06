#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
TEMPLATES_ROOT = ROOT / "templates"
MERGE_KEY_CANDIDATES = ("name", "id", "key", "alias", "project_id")
READ_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1")
MOJIBAKE_MARKERS = tuple("ÃÂÐÑÒÓÔÕÖ×ÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ¶·¸¹º»¼½¾¿")


@dataclass(frozen=True)
class TemplateSpec:
    target: Path
    format: str
    merge: bool = True

    @property
    def template(self) -> Path:
        return TEMPLATES_ROOT / self.target


TEMPLATE_SPECS = [
    TemplateSpec(Path("workspace/active_project.json"), "json"),
    TemplateSpec(Path("workspace/school_info.json"), "json"),
    TemplateSpec(Path("workflow/User/tutor_favor.json"), "json"),
    TemplateSpec(Path("workflow/config/workflow.yaml"), "yaml"),
    TemplateSpec(Path("framework/llm_select/models.yaml"), "yaml"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize or update local config files from tracked templates.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing files.",
    )
    return parser.parse_args()


def load_structured(path: Path, file_format: str) -> Any:
    text = read_text_with_fallback(path)
    if file_format == "json":
        return json.loads(text)
    if file_format in {"yaml", "yml"}:
        return load_yaml_with_fallback(text)
    raise ValueError(f"Unsupported format: {file_format}")


def dump_structured(value: Any, file_format: str) -> str:
    if file_format == "json":
        return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if file_format in {"yaml", "yml"}:
        return dump_yaml_with_fallback(value)
    raise ValueError(f"Unsupported format: {file_format}")


def backup_file(path: Path, dry_run: bool) -> Path:
    suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{suffix}")
    if not dry_run:
        shutil.copy2(path, backup)
    return backup


def write_text(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_text_with_fallback(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in READ_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text(encoding="utf-8")


def load_yaml_with_fallback(text: str) -> Any:
    try:
        import yaml

        return yaml.safe_load(text)
    except ModuleNotFoundError:
        return parse_simple_yaml(text)


def dump_yaml_with_fallback(value: Any) -> str:
    try:
        import yaml

        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    except ModuleNotFoundError:
        return render_simple_yaml(value)


def parse_simple_yaml(text: str) -> Any:
    lines = text.splitlines()
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in lines:
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip(" ")
        if stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(stripped)
        if ":" not in stripped:
            raise ValueError(f"Unsupported YAML line: {raw_line}")
        key, remainder = stripped.split(":", 1)
        key = key.strip()
        remainder = remainder.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if remainder == "":
            new_map: dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent, new_map))
        else:
            current[key] = parse_yaml_scalar(remainder)

    return root


def parse_yaml_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"null", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value in {"[]", "{}"}:
        return [] if value == "[]" else {}
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def render_simple_yaml(value: Any, indent: int = 0) -> str:
    if not isinstance(value, dict):
        raise ValueError("Simple YAML renderer only supports mapping roots.")
    lines: list[str] = []
    for key, item in value.items():
        prefix = " " * indent + f"{key}:"
        if isinstance(item, dict):
            lines.append(prefix)
            lines.append(render_simple_yaml(item, indent + 2).rstrip("\n"))
        else:
            lines.append(prefix + f" {render_yaml_scalar(item)}")
    return "\n".join(lines) + "\n"


def render_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        raise ValueError("Simple YAML renderer does not support non-empty lists.")
    if isinstance(value, dict):
        if not value:
            return "{}"
        raise ValueError("Nested dict should be handled before scalar rendering.")
    text = str(value)
    if text == "" or any(ch in text for ch in ":#\n") or text.strip() != text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def select_merge_key(template_items: list[Any], local_items: list[Any]) -> str | None:
    candidates = []
    if template_items:
        candidates.append(template_items)
    if local_items:
        candidates.append(local_items)
    for key in MERGE_KEY_CANDIDATES:
        if all(
            all(isinstance(item, dict) and key in item for item in items)
            for items in candidates
        ):
            return key
    return None


def merge_values(template_value: Any, local_value: Any) -> Any:
    if isinstance(template_value, dict) and isinstance(local_value, dict):
        merged = {key: value for key, value in local_value.items() if not str(key).startswith("//")}
        for key, template_child in template_value.items():
            if key.startswith("//"):
                merged[key] = template_child
                continue
            if key in local_value:
                merged[key] = merge_values(template_child, local_value[key])
            else:
                merged[key] = template_child
        return merged

    if isinstance(template_value, list) and isinstance(local_value, list):
        merge_key = select_merge_key(template_value, local_value)
        if merge_key:
            local_index = {str(item[merge_key]): item for item in local_value}
            merged_items = []
            seen = set()
            for template_item in template_value:
                item_key = str(template_item[merge_key])
                seen.add(item_key)
                if item_key in local_index:
                    merged_items.append(merge_values(template_item, local_index[item_key]))
                else:
                    merged_items.append(template_item)
            for local_item in local_value:
                item_key = str(local_item[merge_key])
                if item_key not in seen:
                    merged_items.append(local_item)
            return merged_items
        return local_value if local_value else template_value

    if isinstance(local_value, str):
        repaired = repair_mojibake(local_value)
        if repaired is not None:
            return repaired
    return local_value


def repair_mojibake(value: str) -> str | None:
    if not looks_like_mojibake(value):
        return None
    try:
        repaired = value.encode("latin-1").decode("gb18030")
    except Exception:
        return None
    return repaired if repaired != value else None


def looks_like_mojibake(value: str) -> bool:
    if not value:
        return False
    marker_hits = sum(1 for ch in value if ch in MOJIBAKE_MARKERS)
    if marker_hits >= 2:
        return True
    return "�" in value


def sync_spec(spec: TemplateSpec, dry_run: bool) -> str:
    template_path = spec.template
    target_path = ROOT / spec.target
    if not template_path.is_file():
        raise FileNotFoundError(f"Template missing: {template_path}")

    template_text = read_text_with_fallback(template_path)
    if not target_path.exists():
        write_text(target_path, template_text, dry_run)
        return f"created {spec.target}"

    if not spec.merge:
        if read_text_with_fallback(target_path) == template_text:
            return f"unchanged {spec.target}"
        backup = backup_file(target_path, dry_run)
        write_text(target_path, template_text, dry_run)
        return f"overwritten {spec.target} (backup: {backup.name})"

    try:
        template_value = load_structured(template_path, spec.format)
        local_value = load_structured(target_path, spec.format)
        merged_value = merge_values(template_value, local_value)
        merged_text = dump_structured(merged_value, spec.format)
    except Exception:
        backup = backup_file(target_path, dry_run)
        write_text(target_path, template_text, dry_run)
        return f"overwritten {spec.target} (backup: {backup.name})"

    current_text = read_text_with_fallback(target_path)
    if current_text == merged_text:
        return f"unchanged {spec.target}"

    write_text(target_path, merged_text, dry_run)
    return f"updated {spec.target}"


def main() -> int:
    args = parse_args()
    print(f"Initializing project from templates in {TEMPLATES_ROOT}", flush=True)
    for spec in TEMPLATE_SPECS:
        result = sync_spec(spec, dry_run=args.dry_run)
        print(f" - {result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
