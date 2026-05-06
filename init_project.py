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
READ_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1")


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
        import yaml

        return yaml.safe_load(text)
    raise ValueError(f"Unsupported format: {file_format}")


def dump_structured(value: Any, file_format: str) -> str:
    if file_format == "json":
        return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if file_format in {"yaml", "yml"}:
        import yaml

        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
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
        merged = dict(local_value)
        for key, template_child in template_value.items():
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

    return local_value


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
