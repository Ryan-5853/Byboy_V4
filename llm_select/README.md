# llm_select

`llm_select` 负责维护所有后端模型配置，并把工作流里使用的模型别名解析成 `pydantic-ai` 可用的模型对象。

`agent_router` 只指定 `model_alias`，不直接接触 API 地址、令牌和 provider。

## 配置文件

默认配置文件是 [models.yaml](/home/ryan/Bybot_V4/llm_select/models.yaml)。

```yaml
default_alias: local-default

models:
  local-default:
    provider: openai-compatible
    name: your-local-model-name
    base_url: http://127.0.0.1:8000/v1
    api_key: sk-local

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
- `models.<alias>.api_key`: API token。支持 `${ENV_NAME}` 环境变量展开。
- `models.<alias>.system_prompt_role`: OpenAI chat system prompt role，可选；不熟悉时保持空。

## Python 调用

```python
from llm_select import LLMSelector

selector = LLMSelector(config_file="llm_select/models.yaml")
model = selector.get("local-default")
```
