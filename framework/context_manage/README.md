# context_manage

`context_manage` 是 agent session 的上下文兜底压缩层。

当前版本先实现最基本策略：

1. 每次 pydantic-ai 准备请求模型前，通过官方 `AbstractCapability.before_model_request` hook 把当前 `ModelRequestContext` 交给 `ContextManager`
2. 用字符数估算 token 数
3. 如果超过 `max_context_tokens * threshold_ratio`，调用固定后端模型压缩上下文
4. 压缩结果必须符合 `CompactState` JSON
5. 按 pydantic-ai compaction 语义将历史改写为 `ModelResponse(CompactionPart)` + 当前请求，再交还给原 agent 继续工作
6. 如果压缩模型失败，不让主流程崩溃，使用本地保守 fallback 摘要
7. （新增）每次模型请求前，若最近工具返回包含超长文本，会先将原文落盘到临时缓存文件，再生成有效信息摘要并替换上下文中的原文，减少上下文噪声

## CompactState

压缩结果必须保留：

- `task_goal`: 任务目标
- `confirmed_facts`: 已确认事实
- `evidence`: 支撑事实的来源 URL / 文件 ID / 行号 / 引用片段
- `useless_sources_visited`: 已经访问过但无用的来源
- `unresolved_questions`: 尚未解决的问题
- `next_steps`: 下一步建议

## Agent 配置

```yaml
context_management:
  enabled: true
  threshold_ratio: 0.8
  # 可选：不填时自动使用 framework/llm_select/models.yaml 里当前任务模型的 context_window_tokens
  max_context_tokens: null
  compact_model_alias: local-default
  chars_per_token: 4.0
  keep_recent_messages: 0
  summarize_large_tool_results: true
  large_tool_result_threshold_chars: 8000
  max_tool_summaries_per_request: 2
  tool_result_cache_dir: "logs/context_cache"
  tool_result_summary_max_chars: 1800
```

`compact_model_alias` 是固定压缩后端的模型别名，由 `framework/llm_select/models.yaml` 解析。它可以和执行任务的 `model_alias` 不同。

字段说明：

- `enabled`: 是否启用上下文管理。
- `threshold_ratio`: 触发压缩的比例，例如 `0.8` 表示达到上下文窗口的 80% 时触发。
- `max_context_tokens`: 可选手动覆盖。为空时从 `framework/llm_select/models.yaml` 的当前模型别名读取 `context_window_tokens`（或兼容字段 `context_window`）。
- `compact_model_alias`: 压缩上下文使用的模型别名。
- `chars_per_token`: token 估算比例，默认 4 字符约等于 1 token。
- `max_serialized_chars_for_compactor`: 送入压缩模型的最大序列化上下文字符数。
- `keep_recent_messages`: 预留字段；当前官方 compaction 模式默认只保留 `CompactionPart + 当前请求`。
- `summarize_large_tool_results`: 是否启用“长工具结果落盘+摘要替换”。
- `large_tool_result_threshold_chars`: 超过该长度的工具文本结果会进入摘要流程。
- `max_tool_summaries_per_request`: 每次模型请求前最多处理多少条超长工具结果，防止摘要本身过慢。
- `tool_result_cache_dir`: 工具原始文本缓存目录。
- `tool_result_summary_max_chars`: 摘要文本写回上下文的最大长度。

注意：当前项目默认任务模型是 `OpenAIChatModel`，这个后端不会向模型发送 `CompactionPart`。因此 `context_manage` 会同时把 `CompactState` 注入当前请求的 `instructions` 作为兼容桥接；如果后续切到 `OpenAIResponsesModel` 或 provider 原生 compaction，可以去掉这层桥接，仅 round-trip 官方 `CompactionPart`。
