from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    source: str
    detail: str = ""
    quote: str = ""


class CompactState(BaseModel):
    task_goal: str
    confirmed_facts: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    useless_sources_visited: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class ContextManageConfig(BaseModel):
    enabled: bool = True
    threshold_ratio: float = Field(default=0.8, gt=0, le=1)
    max_context_tokens: int | None = Field(default=None, ge=1000)
    compact_model_alias: str = "local-default"
    chars_per_token: float = Field(default=4.0, gt=0)
    max_serialized_chars_for_compactor: int = Field(default=120000, ge=1000)
    keep_recent_messages: int = Field(default=0, ge=0)
    summarize_large_tool_results: bool = True
    large_tool_result_threshold_chars: int = Field(default=8000, ge=1000)
    max_tool_summaries_per_request: int = Field(default=2, ge=1, le=20)
    tool_result_cache_dir: str = "logs/context_cache"
    tool_result_summary_max_chars: int = Field(default=1800, ge=200, le=20000)


class ContextManageReport(BaseModel):
    compacted: bool = False
    estimated_tokens: int = 0
    threshold_tokens: int = 0
    message_count_before: int = 0
    message_count_after: int = 0
    compact_model_alias: str | None = None
    fallback_used: bool = False
    error: str | None = None
