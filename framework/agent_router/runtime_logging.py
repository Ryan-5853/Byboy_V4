from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from pydantic_ai import messages as ai_messages


@dataclass
class ToolArgsBuffer:
    tool_name: str | None = None
    args: str | dict[str, Any] | None = None
    call_id: str | None = None


@dataclass
class TextBuffer:
    kind: str
    content: str = ""


class RuntimeLogger:
    def __init__(
        self,
        *,
        enabled: bool = True,
        max_preview_chars: int = 1200,
        log_arg_deltas: bool = False,
        log_text_deltas: bool = False,
        log_thinking: bool = True,
        persist_logs: bool = True,
        log_dir: str | Path | None = None,
        session_id: str | None = None,
        persist_full_payload: bool = False,
        persist_max_chars: int = 4000,
        agent_type: str | None = None,
        task_name: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.max_preview_chars = max_preview_chars
        self.log_arg_deltas = log_arg_deltas
        self.log_text_deltas = log_text_deltas
        self.log_thinking = log_thinking
        self.persist_logs = persist_logs
        self.persist_full_payload = persist_full_payload
        self.persist_max_chars = persist_max_chars
        self.session_id = session_id or uuid4().hex
        self._tool_arg_buffers: dict[int, ToolArgsBuffer] = {}
        self._text_buffers: dict[int, TextBuffer] = {}
        self._log_dir = Path(log_dir).expanduser() if log_dir else Path("logs/agent_runs")
        self._log_file: Path | None = None
        if self.persist_logs:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._log_file = self._build_log_file_name(agent_type=agent_type, task_name=task_name)

    def log(self, event: str, message: str, **fields: Any) -> None:
        persisted_fields = fields
        if not self.persist_full_payload:
            persisted_fields = self._sanitize_for_persist(fields)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event,
            "message": message,
            "fields": persisted_fields,
        }
        if self.persist_logs and self._log_file is not None:
            with self._log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        if self.enabled:
            suffix = ""
            if fields:
                pairs = " ".join(f"{key}={self._preview(value)}" for key, value in fields.items())
                suffix = f" | {pairs}"
            print(f"[agent:{event}] {message}{suffix}", flush=True)

    @property
    def log_file(self) -> Path | None:
        return self._log_file

    def _build_log_file_name(self, *, agent_type: str | None, task_name: str | None) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        agent = self._slug(agent_type or "agent")
        task = self._slug(self._normalize_task_name(task_name or "task"))
        prefix = f"{day}-{agent}-{task}-"
        pattern = re.compile(rf"^{re.escape(prefix)}(\d{{4}})\.jsonl$")
        max_seq = 0
        for item in self._log_dir.iterdir():
            if not item.is_file():
                continue
            m = pattern.match(item.name)
            if not m:
                continue
            try:
                seq = int(m.group(1))
            except Exception:
                continue
            if seq > max_seq:
                max_seq = seq
        next_seq = max_seq + 1
        filename = f"{prefix}{next_seq:04d}.jsonl"
        return self._log_dir / filename

    def _slug(self, value: str) -> str:
        text = value.strip().lower()
        text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-")
        return text or "na"

    def _normalize_task_name(self, value: str) -> str:
        text = value.strip()
        # Remove trailing random/hash-like suffixes, e.g.
        # run_prompt_8_db7e7530 -> run_prompt_8
        # xxx-59cb906b -> xxx
        text = re.sub(r"([_-])[0-9a-fA-F]{8,}$", "", text)
        # If multiple hash-like chunks are chained, strip repeatedly.
        while True:
            updated = re.sub(r"([_-])[0-9a-fA-F]{8,}$", "", text)
            if updated == text:
                break
            text = updated
        return text or "task"

    async def event_stream_handler(
        self,
        _ctx: Any,
        stream: AsyncIterable[ai_messages.AgentStreamEvent],
    ) -> None:
        async for event in stream:
            self.handle_event(event)

    def handle_event(self, event: ai_messages.AgentStreamEvent) -> None:
        kind = getattr(event, "event_kind", type(event).__name__)
        if isinstance(event, ai_messages.FunctionToolCallEvent):
            part = event.part
            self.log(
                "tool_call",
                part.tool_name,
                args=part.args_as_dict(),
                call_id=part.tool_call_id,
                args_valid=event.args_valid,
            )
        elif isinstance(event, ai_messages.FunctionToolResultEvent):
            result = event.result
            content = getattr(result, "content", None)
            self.log(
                "tool_result",
                result.tool_name,
                outcome=getattr(result, "outcome", None),
                result=content,
                call_id=result.tool_call_id,
            )
        elif isinstance(event, ai_messages.PartStartEvent):
            part = event.part
            part_kind = getattr(part, "part_kind", type(part).__name__)
            if isinstance(part, ai_messages.TextPart):
                self._text_buffers[event.index] = TextBuffer(kind="text", content=part.content or "")
                self.log("model_text_start", "model started text response")
            elif isinstance(part, ai_messages.ThinkingPart):
                self._text_buffers[event.index] = TextBuffer(kind="thinking", content=part.content or "")
                if self.log_thinking:
                    self.log("thinking_start", "model started thinking")
            elif isinstance(part, ai_messages.ToolCallPart):
                self._tool_arg_buffers[event.index] = ToolArgsBuffer(
                    tool_name=part.tool_name,
                    args=part.args,
                    call_id=part.tool_call_id,
                )
                self.log("model_tool_start", part.tool_name, call_id=part.tool_call_id)
            elif isinstance(part, ai_messages.CompactionPart):
                self.log("context_compaction", "compaction part emitted", content=part.content)
            else:
                self.log("part_start", str(part_kind))
        elif isinstance(event, ai_messages.PartDeltaEvent):
            delta = event.delta
            delta_kind = getattr(delta, "part_delta_kind", type(delta).__name__)
            content = getattr(delta, "content_delta", None)
            args_delta = getattr(delta, "args_delta", None)
            if content:
                self._merge_text_delta(event.index, content)
                if self.log_text_deltas:
                    self.log("model_text_delta", "text delta", text=content)
            elif args_delta:
                self._merge_tool_args_delta(event.index, delta)
                if self.log_arg_deltas:
                    self.log("tool_args_delta", "tool args delta", args=args_delta)
            else:
                self.log("part_delta", str(delta_kind))
        elif isinstance(event, ai_messages.PartEndEvent):
            part = event.part
            part_kind = getattr(part, "part_kind", type(part).__name__)
            if isinstance(part, ai_messages.TextPart):
                buffer = self._text_buffers.pop(event.index, None)
                text = buffer.content if buffer else part.content
                self.log("model_text_end", "model finished text response", text=text)
            elif isinstance(part, ai_messages.ThinkingPart):
                buffer = self._text_buffers.pop(event.index, None)
                text = buffer.content if buffer else part.content
                if self.log_thinking:
                    self.log("thinking_end", "model finished thinking", text=text)
            elif isinstance(part, ai_messages.ToolCallPart):
                buffer = self._tool_arg_buffers.pop(event.index, None)
                args = part.args_as_dict()
                if buffer is not None and buffer.args is not None:
                    args = self._args_to_dict(buffer.args)
                self.log(
                    "model_tool_end",
                    part.tool_name,
                    args=args,
                    call_id=part.tool_call_id,
                )
            else:
                self.log("part_end", str(part_kind))
        else:
            self.log("event", str(kind))

    def _preview(self, value: Any) -> str:
        text = repr(value)
        if len(text) > self.max_preview_chars:
            return text[: self.max_preview_chars] + "...<truncated>"
        return text

    def _merge_text_delta(self, index: int, content_delta: str) -> None:
        buffer = self._text_buffers.setdefault(index, TextBuffer(kind="text"))
        buffer.content += content_delta

    def _merge_tool_args_delta(self, index: int, delta: Any) -> None:
        buffer = self._tool_arg_buffers.setdefault(index, ToolArgsBuffer())
        tool_name_delta = getattr(delta, "tool_name_delta", None)
        args_delta = getattr(delta, "args_delta", None)
        call_id = getattr(delta, "tool_call_id", None)
        if tool_name_delta:
            buffer.tool_name = (buffer.tool_name or "") + tool_name_delta
        if isinstance(args_delta, str):
            if isinstance(buffer.args, dict):
                buffer.args = repr(buffer.args) + args_delta
            else:
                buffer.args = (buffer.args or "") + args_delta
        elif isinstance(args_delta, dict):
            if isinstance(buffer.args, str):
                buffer.args = buffer.args + repr(args_delta)
            else:
                buffer.args = {**(buffer.args or {}), **args_delta}
        if call_id:
            buffer.call_id = call_id

    def _args_to_dict(self, args: str | dict[str, Any]) -> Any:
        if isinstance(args, dict):
            return args
        try:
            import json

            return json.loads(args)
        except Exception:
            return args

    def _sanitize_for_persist(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) > self.persist_max_chars:
                return {
                    "_truncated": True,
                    "orig_len": len(value),
                    "preview": value[: self.persist_max_chars],
                }
            return value
        if isinstance(value, dict):
            return {k: self._sanitize_for_persist(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_for_persist(v) for v in value]
        if isinstance(value, tuple):
            return [self._sanitize_for_persist(v) for v in value]
        return value
