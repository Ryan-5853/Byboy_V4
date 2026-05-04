from __future__ import annotations

from dataclasses import replace
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


class ContextManager:
    """Compress pydantic-ai message history before it exceeds context limits."""

    def __init__(
        self,
        config: ContextManageConfig | None = None,
        *,
        llm_selector: LLMSelector | None = None,
        llm_config_file: str | None = None,
    ) -> None:
        self.config = config or ContextManageConfig()
        self.llm_selector = llm_selector or LLMSelector(config_file=llm_config_file)
        self.last_report = ContextManageReport()

    async def compact_request_context(
        self,
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
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
        estimated_tokens = self.estimate_tokens(self.serialize_messages(messages))
        return ContextManageReport(
            compacted=False,
            estimated_tokens=estimated_tokens,
            threshold_tokens=int(self.config.max_context_tokens * self.config.threshold_ratio),
            message_count_before=len(messages),
            message_count_after=len(messages),
            compact_model_alias=self.config.compact_model_alias,
        )

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
