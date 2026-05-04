# agent_router

`agent_router` 是工作流控制层和 `pydantic-ai` 之间的 subagent 管理/任务转发层。

调用方只需要提供：

- `prompt_file`: 本次任务的 prompt 文件
- `config_file`: 本次任务的 subagent 配置文件
- `variables`: 可选 prompt 模板变量

路由层会读取任务配置，选择模型别名、工具白名单及每个工具的硬限制参数、模型参数、最大请求次数和最大工具调用次数，然后创建一次性的 `pydantic_ai.Agent` 执行任务。

具体模型的 API 地址、令牌、provider 和真实模型名由 `llm_select` 管理，`agent_router` 不保存这些后端细节。

## Python 调用

```python
from pathlib import Path

from agent_router import AgentRouter, RouterRequest

router = AgentRouter(base_dir=Path(__file__).parent)
result = router.run_sync(
    RouterRequest(
        prompt_file=Path("agent_router/examples/research.prompt.md"),
        config_file=Path("agent_router/examples/openai_compatible.yaml"),
        variables={"topic": "pydantic-ai OpenAI-compatible API"},
    )
)

print(result.output)
```

## CLI 调用

```bash
python -m agent_router \
  --prompt agent_router/examples/research.prompt.md \
  --config agent_router/examples/openai_compatible.yaml \
  --llm-config llm_select/models.yaml \
  --var topic="pydantic-ai OpenAI-compatible API"
```

## 配置字段

```yaml
agent:
  name: research-worker
  instructions: null
  system_prompt: ""
  retries: 1
  output_retries: 1
  tool_timeout: 20
  stream_events: true
  log_tool_results: true
  log_preview_chars: 1200
  log_arg_deltas: false
  log_text_deltas: false
  log_thinking: true
  output_schema:
    answer: str
    sources: list[str]
    confidence: float

model_alias: local-default

model_settings:
  temperature: 0.2
  max_tokens: 1200

usage_limits:
  request_limit: 8
  tool_calls_limit: 5
  input_tokens_limit: 20000
  output_tokens_limit: 2000
  total_tokens_limit: 30000

context_management:
  enabled: true
  threshold_ratio: 0.8
  max_context_tokens: 32000
  compact_model_alias: local-default
  chars_per_token: 4.0
  max_serialized_chars_for_compactor: 120000
  keep_recent_messages: 0

tools:
  - name: web.fetch_url
    config:
      max_read_chars: 5000
      timeout_seconds: 20
      allowed_schemes:
        - http
        - https
```

### 字段说明

`agent`

- `name`: subagent 名称，用于日志和结果标识。
- `instructions`: pydantic-ai instructions，可选。适合放动态或框架级指令。
- `system_prompt`: subagent 系统提示词，可为字符串或字符串列表。
- `retries`: tool 调用或模型行为可重试时的默认重试次数。
- `output_retries`: 结构化输出校验失败时的重试次数；为空时使用 pydantic-ai 默认值。
- `tool_timeout`: 单个 tool 执行超时时间，单位秒。
- `output_schema`: 结构化输出字段定义。当前支持 `str`、`int`、`float`、`bool`、`dict`、`Any`、`list[...]`、`dict[..., ...]`。
- `stream_events`: 是否输出 agent 运行事件，例如模型文本、tool call、tool result。
- `log_tool_results`: 是否输出 tool 实际执行开始、结束和返回摘要。
- `log_preview_chars`: 日志中长文本/长结果的最大预览字符数。
- `log_arg_deltas`: 是否输出流式 tool 参数增量。默认 `false`，默认只在参数拼完整后输出。
- `log_text_deltas`: 是否输出模型文本流式增量。默认 `false`，默认只在一段文本结束后输出完整文本。
- `log_thinking`: 是否输出 thinking part 的聚合结果。若后端会产生较长 thinking，可设为 `false`。

`model_alias`

- `model_alias`: 任务模型别名。这里只写别名，真实模型名、API 地址、令牌和 provider 都在 [llm_select/models.yaml](/home/ryan/Bybot_V4/llm_select/models.yaml) 中配置。

`model_settings`

- `temperature`: 单次模型请求的采样温度。
- `max_tokens`: 单次模型响应最多生成多少 token。它限制的是“这一轮回答/工具参数/最终输出”的生成长度，不是整个 session 的总上下文。
- `top_p`、`timeout`、`presence_penalty`、`frequency_penalty`、`stop_sequences` 等: 这些字段会原样传给 pydantic-ai 的模型设置，是否生效取决于后端 provider。

`usage_limits`

- `request_limit` / `max_requests`: 整次 agent run 最多请求模型多少次。每次模型回复、工具调用后继续推理，都会消耗请求次数。
- `tool_calls_limit` / `max_tool_calls`: 整次 agent run 最多成功执行多少次 tool。
- `input_tokens_limit` / `max_input_tokens`: pydantic-ai 已统计到的输入 token 上限。
- `output_tokens_limit` / `max_output_tokens`: pydantic-ai 已统计到的输出 token 上限。
- `total_tokens_limit` / `max_total_tokens`: 整次 agent run 累计输入+输出 token 上限。
- `count_tokens_before_request`: 是否在请求前做 token 计数预检查。当前 OpenAI-compatible chat 后端未必支持精确预检查。
- 不想限制某个 limit 时，可以省略该字段；如果配置系统必须显式传值，可传 `null`、`none`、`unlimited` 字符串，都会解析为不限制。

`max_tokens` 和 `max_total_tokens` 的区别：

- `model_settings.max_tokens`: 单次模型响应最多生成多少 token。例如设为 `1200`，表示某一轮模型最多输出 1200 token。
- `usage_limits.max_total_tokens`: 整个 agent run 的累计 token 预算，包括多轮模型请求的输入和输出。例如设为 `30000`，表示这次任务整体累计超过 30000 token 后要停止或报可接管错误。
- 简单说：`max_tokens` 管“单次输出长度”，`max_total_tokens` 管“整次任务总消耗”。

`context_management`

- `enabled`: 是否启用上下文管理。
- `threshold_ratio`: 触发压缩的比例。比如 `0.8` 表示达到上下文预算 80% 时压缩。
- `max_context_tokens`: 估算的上下文窗口大小。
- `compact_model_alias`: 固定压缩模型别名，由 `llm_select` 解析，可以和任务模型不同。
- `chars_per_token`: token 粗略估算比例。默认 4 字符约等于 1 token。
- `max_serialized_chars_for_compactor`: 送给压缩模型的最大序列化上下文字符数。
- `keep_recent_messages`: 预留字段。当前官方 compaction 模式下默认保留 `CompactionPart + 当前请求`。

`tools`

- `name`: tool 名称，必须是 `/home/ryan/Bybot_V4/tools` 下注册过的 `ToolSpec.name`。
- `config`: 当前 subagent 对该 tool 的硬限制配置。配置会在 `tool_call` 层校验并固化，模型不能绕过。

当前常用 tool 见 [tools/README.md](/home/ryan/Bybot_V4/tools/README.md)。

当前内置示例：

- `web.fetch_url`: 抓取 URL，并尽量返回清洗后的正文。支持 `max_read_chars`、`timeout_seconds`、`follow_redirects`、`allowed_schemes`。

## Tool 配置接口

每个 tool 可以有自己的 `config`，这些配置会交给 [tool_call](/home/ryan/Bybot_V4/tool_call/README.md) 层校验并固化。真正执行工具调用时，tool 自己检查这些硬限制，例如网页读取长度、允许 URL scheme、文件工作空间路径、是否允许写入等。

```yaml
tools:
  - name: filesystem.read_file
    config:
      workspace_root: /home/ryan/Bybot_V4
      max_read_chars: 20000
      allowed_globs:
        - "**/*.py"
        - "**/*.md"
```

上面只是接口示例；只有 `/home/ryan/Bybot_V4/tools` 下按规范注册、并且出现在当前 subagent 配置里的 tool 才能被启用。
