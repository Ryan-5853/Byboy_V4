# llm_select

`llm_select` 负责维护所有后端模型配置，并把工作流里使用的模型别名解析成 `pydantic-ai` 可用的模型对象。

`agent_router` 只指定 `model_alias`，不直接接触 API 地址、令牌和 provider。

## 配置文件

默认配置文件是 [models.yaml](framework/llm_select/models.yaml)。

加载顺序是：

1. 自动加载工程根目录 `.env`
2. 自动加载工程根目录 `.env.local`
3. 再解析 `models.yaml` 里的 `${ENV_NAME}` 占位

因此推荐把所有真实密钥都放进 `.env` / `.env.local`，不要直接写进 YAML。

```yaml
default_alias: local-default

models:
  local-default:
    provider: openai-compatible
    name: your-local-model-name
    context_window_tokens: 32768
    base_url: http://127.0.0.1:8000/v1
    api_key: ${LOCAL_OPENAI_API_KEY}
    model_settings:
      temperature: 1.0
      top_p: 0.95
      presence_penalty: 1.5
      max_tokens: 2048
      timeout: 180
      extra_body:
        top_k: 20
        min_p: 0.0
        repetition_penalty: 1.0

  openai-default:
    provider: openai
    name: gpt-4.1-mini
    api_key: ${OPENAI_API_KEY}
```

## 字段说明

- `default_alias`: 默认模型别名。当 agent 配置没有指定 `model_alias` 时使用。
- `models`: 模型别名到模型配置的映射。
- `models.<alias>.provider`: provider 类型。当前支持 `openai-compatible`、`openai`、`openai-chat`、`known`。
- `models.<alias>.name`: 真实模型名，会传给 pydantic-ai。
- `models.<alias>.base_url`: OpenAI-compatible API 地址，例如 `http://127.0.0.1:8000/v1`。`openai-compatible` 通常需要。
- `models.<alias>.api_key`: API token。支持 `${ENV_NAME}` 环境变量展开。若环境变量未设置，会被解析为空字符串，不会把 `${VAR}` 原样发给后端。
- `models.<alias>.system_prompt_role`: OpenAI chat system prompt role，可选；不熟悉时保持空。
- `models.<alias>.context_window_tokens`: 该模型上下文窗口（token）。供 `context_manage` 自动读取。
- `models.<alias>.context_window`: `context_window_tokens` 的兼容别名（旧字段名）。
- `models.<alias>.model_settings`: 该模型别名固定携带的 pydantic-ai `model_settings`。工作流只指定模型别名时也会自动带上这些参数。

## model_settings 与 extra_body

`model_settings` 会由 `agent_router` 自动传给 pydantic-ai。

标准 OpenAI Chat 参数可以直接写在 `model_settings` 顶层，例如：

- `temperature`
- `top_p`
- `presence_penalty`
- `frequency_penalty`
- `max_tokens`
- `timeout`

OpenAI-compatible 后端支持、但 OpenAI 标准接口没有的参数，应写入 `extra_body`，由 pydantic-ai 透传给后端，例如 Qwen 后端常见的：

```yaml
model_settings:
  temperature: 1.0
  top_p: 0.95
  presence_penalty: 1.5
  extra_body:
    top_k: 20
    min_p: 0.0
    repetition_penalty: 1.0
```

### Qwen 专用适配

对于 `models.<alias>.name` 含 `qwen` 的模型，框架会自动把：

```yaml
model_settings:
  extra_body:
    enable_thinking: false
```

转换为 Qwen 官方格式：

```yaml
model_settings:
  extra_body:
    chat_template_kwargs:
      enable_thinking: false
```

这样你可以继续用现有配置写法，不会影响非 Qwen 模型。

如果某个任务配置中也写了 `model_settings`，任务级字段会覆盖模型别名中的同名字段；常规 workflow 不需要这样做。

## Python 调用

```python
from llm_select import LLMSelector

selector = LLMSelector(config_file="framework/llm_select/models.yaml")
model = selector.get("local-default")
```

## 推荐的 env 模板

根目录 `.env.example`：

```dotenv
LOCAL_OPENAI_API_KEY=
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
WEBUI_PORT=8897
```
