from __future__ import annotations

from dataclasses import is_dataclass
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai import messages as ai_messages
from pydantic_ai.models import ModelRequestContext

from llm_select import LLMSelector

from .schemas import CompactState, ContextManageConfig, ContextManageReport, EvidenceRef


COMPACT_PROMPT = """
你要把一个即将溢出的 agent 上下文压缩成可继续执行的状态。

不要保留无用原文。
必须保留：
1. 任务目标
2. 已确认事实
3. 支撑事实的来源 URL / 文件 ID / 行号 / 引用片段
4. 已经访问过但无用的来源
5. 尚未解决的问题
6. 下一步建议

输出必须符合 CompactState JSON。
""".strip()

TOOL_SUMMARY_PROMPT = """
你将收到一次工具调用返回的大段原始文本。
请仅提炼对当前任务后续推理真正有用的信息，删除噪声。

输出要求（纯文本，简洁）：
1) 有效信息要点（最多10条）
2) 明确不确定/缺失项（最多5条）
3) 建议下一步（最多5条）

不要复述大段原文，不要输出 JSON。
""".strip()


class ContextManager:
    """Compress pydantic-ai message history before it exceeds context limits."""

    def __init__(
        self,
        config: ContextManageConfig | None = None,
        *,
        llm_selector: LLMSelector | None = None,
        llm_config_file: str | None = None,
        active_model_alias: str | None = None,
    ) -> None:
        self.config = config or ContextManageConfig()
        self.llm_selector = llm_selector or LLMSelector(config_file=llm_config_file)
        self.active_model_alias = active_model_alias
        self.last_report = ContextManageReport()
        self._cache_dir = Path(self.config.tool_result_cache_dir).expanduser()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def compact_request_context(
        self,
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        if self.config.summarize_large_tool_results:
            request_context.messages = await self._summarize_large_tool_results(
                request_context.messages
            )
        report = self._build_report(request_context.messages)
        self.last_report = report
        if not self.config.enabled:
            return request_context
        if report.estimated_tokens < report.threshold_tokens:
            return request_context
        if len(request_context.messages) < 2:
            return request_context

        message_count_before = len(request_context.messages)
        messages_to_compact = request_context.messages[:-1]
        current_request = request_context.messages[-1]

        try:
            compact_state = await self._compact_with_llm(messages_to_compact)
            fallback_used = False
            error = None
        except Exception as exc:
            compact_state = self._fallback_compact(messages_to_compact, str(exc))
            fallback_used = True
            error = str(exc)

        compacted_messages = self._inject_compact_state(current_request, compact_state)
        request_context.messages = compacted_messages
        self.last_report = ContextManageReport(
            compacted=True,
            estimated_tokens=report.estimated_tokens,
            threshold_tokens=report.threshold_tokens,
            message_count_before=message_count_before,
            message_count_after=len(compacted_messages),
            compact_model_alias=self.config.compact_model_alias,
            fallback_used=fallback_used,
            error=error,
        )
        return request_context

    async def process_messages(
        self,
        messages: list[ai_messages.ModelMessage],
    ) -> list[ai_messages.ModelMessage]:
        """Deprecated compatibility path. Prefer `ContextManageCapability`."""
        report = self._build_report(messages)
        self.last_report = report
        return messages

    def _build_report(self, messages: list[ai_messages.ModelMessage]) -> ContextManageReport:
        max_context_tokens = self._resolve_max_context_tokens()
        estimated_tokens = self.estimate_tokens(self.serialize_messages(messages))
        return ContextManageReport(
            compacted=False,
            estimated_tokens=estimated_tokens,
            threshold_tokens=int(max_context_tokens * self.config.threshold_ratio),
            message_count_before=len(messages),
            message_count_after=len(messages),
            compact_model_alias=self.config.compact_model_alias,
        )

    def _resolve_max_context_tokens(self) -> int:
        if self.config.max_context_tokens is not None:
            return int(self.config.max_context_tokens)
        resolved = self.llm_selector.get_context_window_tokens(self.active_model_alias)
        if resolved is not None:
            return int(resolved)
        # Fallback only when model metadata does not declare context window.
        return 32000

    async def _compact_with_llm(self, messages: list[ai_messages.ModelMessage]) -> CompactState:
        model = self.llm_selector.get(self.config.compact_model_alias)
        agent = Agent(
            model=model,
            output_type=CompactState,
            system_prompt=COMPACT_PROMPT,
            retries=1,
        )
        serialized = self.serialize_messages(messages)
        if len(serialized) > self.config.max_serialized_chars_for_compactor:
            serialized = serialized[-self.config.max_serialized_chars_for_compactor :]
        prompt = (
            "以下是即将溢出的 agent 上下文，已经序列化为 pydantic-ai messages JSON。\n"
            "请压缩为 CompactState JSON，并保证后续 agent 能继续执行任务。\n\n"
            f"{serialized}"
        )
        result = await agent.run(prompt)
        return result.output

    async def _summarize_large_tool_results(
        self,
        messages: list[ai_messages.ModelMessage],
    ) -> list[ai_messages.ModelMessage]:
        summarized = 0
        output: list[ai_messages.ModelMessage] = []
        for message in messages:
            new_message = message
            parts = getattr(message, "parts", None)
            if not isinstance(parts, list):
                output.append(new_message)
                continue
            new_parts = list(parts)
            changed = False
            for idx, part in enumerate(parts):
                if summarized >= self.config.max_tool_summaries_per_request:
                    break
                if not self._looks_like_tool_result_part(part):
                    continue
                content = getattr(part, "content", None)
                if not isinstance(content, str):
                    continue
                if content.startswith("[CONTEXT_CACHE]"):
                    continue
                if len(content) < self.config.large_tool_result_threshold_chars:
                    continue
                cached = self._write_tool_cache(content)
                summary = await self._summarize_text_content(content)
                replacement = self._build_cached_placeholder(content, cached, summary, part)
                new_part = self._replace_part_content(part, replacement)
                if new_part is None:
                    continue
                new_parts[idx] = new_part
                summarized += 1
                changed = True
            if changed:
                replaced = self._replace_message_parts(message, new_parts)
                if replaced is not None:
                    new_message = replaced
            output.append(new_message)
        return output

    def _looks_like_tool_result_part(self, part: Any) -> bool:
        if not hasattr(part, "content"):
            return False
        if hasattr(part, "tool_name") or hasattr(part, "tool_call_id"):
            return True
        part_kind = str(getattr(part, "part_kind", "")).lower()
        return "tool" in part_kind and "result" in part_kind

    async def _summarize_text_content(self, text: str) -> str:
        model = self.llm_selector.get(self.config.compact_model_alias)
        agent = Agent(
            model=model,
            output_type=str,
            system_prompt=TOOL_SUMMARY_PROMPT,
            retries=1,
        )
        clipped = text[: self.config.max_serialized_chars_for_compactor]
        prompt = (
            "下面是一次工具调用返回的大段文本。请按要求提炼有效信息。\n\n"
            f"{clipped}"
        )
        try:
            result = await agent.run(prompt)
            summary = str(result.output).strip()
        except Exception as exc:
            summary = f"摘要失败，保留占位。错误：{exc}"
        if len(summary) > self.config.tool_result_summary_max_chars:
            summary = summary[: self.config.tool_result_summary_max_chars] + "...<truncated>"
        return summary

    def _write_tool_cache(self, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rel = f"{ts}_{digest}.txt"
        path = self._cache_dir / rel
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        return str(path)

    def _build_cached_placeholder(self, text: str, cache_path: str, summary: str, part: Any) -> str:
        tool_name = getattr(part, "tool_name", "unknown_tool")
        call_id = getattr(part, "tool_call_id", "")
        meta = {
            "tool_name": tool_name,
            "tool_call_id": call_id,
            "orig_chars": len(text),
            "cache_file": cache_path,
            "policy": "large_tool_result_cached_and_summarized",
        }
        return "[CONTEXT_CACHE]\n" + json.dumps(meta, ensure_ascii=False) + "\n\n" + summary

    def _replace_part_content(self, part: Any, content: str) -> Any | None:
        if hasattr(part, "model_copy"):
            try:
                return part.model_copy(update={"content": content})
            except Exception:
                pass
        if is_dataclass(part):
            try:
                return replace(part, content=content)
            except Exception:
                pass
        try:
            setattr(part, "content", content)
            return part
        except Exception:
            return None

    def _replace_message_parts(
        self,
        message: ai_messages.ModelMessage,
        new_parts: list[Any],
    ) -> ai_messages.ModelMessage | None:
        if hasattr(message, "model_copy"):
            try:
                return message.model_copy(update={"parts": new_parts})
            except Exception:
                pass
        if is_dataclass(message):
            try:
                return replace(message, parts=new_parts)
            except Exception:
                pass
        try:
            setattr(message, "parts", new_parts)
            return message
        except Exception:
            return None

    def _fallback_compact(
        self,
        messages: list[ai_messages.ModelMessage],
        error: str,
    ) -> CompactState:
        serialized = self.serialize_messages(messages)
        excerpt = serialized[-8000:]
        return CompactState(
            task_goal="Context compaction fallback: infer task goal from preserved recent context.",
            confirmed_facts=[
                "LLM compaction failed; preserved only a recent serialized context excerpt.",
                f"Compaction error: {error}",
            ],
            evidence=[
                EvidenceRef(
                    source="recent_context_excerpt",
                    detail="Last 8000 characters of serialized pydantic-ai message history.",
                    quote=excerpt[:1000],
                )
            ],
            useless_sources_visited=[],
            unresolved_questions=[
                "Review the recent context excerpt to recover task state before continuing."
            ],
            next_steps=[
                "Continue from the preserved recent context.",
                "Avoid reloading long raw sources unless needed.",
            ],
        )

    def _inject_compact_state(
        self,
        current_request: ai_messages.ModelMessage,
        compact_state: CompactState,
    ) -> list[ai_messages.ModelMessage]:
        compact_json = compact_state.model_dump_json(indent=2)
        compacted_response = ai_messages.ModelResponse(
            parts=[
                ai_messages.CompactionPart(
                    content=compact_json,
                    provider_name="bybot-context-manage",
                    provider_details={"compaction": True, "format": "CompactState"},
                )
            ],
            model_name=self.config.compact_model_alias,
            provider_name="bybot-context-manage",
            provider_details={"compaction": True, "format": "CompactState"},
        )
        bridged_current_request = self._bridge_compaction_for_non_native_models(
            current_request,
            compact_json,
        )
        if self.config.keep_recent_messages <= 0:
            return [compacted_response, bridged_current_request]
        return [compacted_response, bridged_current_request]

    def _bridge_compaction_for_non_native_models(
        self,
        current_request: ai_messages.ModelMessage,
        compact_json: str,
    ) -> ai_messages.ModelMessage:
        if not isinstance(current_request, ai_messages.ModelRequest):
            return current_request
        bridge = (
            "Previous session history was compacted by context_manage. "
            "Continue from this CompactState JSON. Do not assume facts not present here.\n"
            f"{compact_json}"
        )
        instructions = current_request.instructions
        merged_instructions = f"{bridge}\n\n{instructions}" if instructions else bridge
        return replace(current_request, instructions=merged_instructions)

    def serialize_messages(self, messages: list[ai_messages.ModelMessage]) -> str:
        return ai_messages.ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")

    def estimate_tokens(self, text: str) -> int:
        return int(len(text) / self.config.chars_per_token)

    def as_history_processor(self) -> Any:
        async def process(messages: list[ai_messages.ModelMessage]) -> list[ai_messages.ModelMessage]:
            return await self.process_messages(messages)

        return process
