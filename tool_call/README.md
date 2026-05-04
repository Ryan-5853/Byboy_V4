# tool_call

`tool_call` 是所有工具调用的抽象层。

职责：

- 管理和发现 `/home/ryan/Bybot_V4/tools` 下注册的 tool
- 根据 subagent 配置创建每个 agent 专属的 `ToolCallManager`
- 校验 agent 是否允许调用某个 tool
- 校验 tool 配置里的硬限制是否合法
- 校验运行时调用参数是否合法
- 执行 tool，并返回统一结果
- 为 `pydantic-ai` 暴露可挂载的 tool callable

## Agent 配置格式

```yaml
tools:
  - name: web.fetch_url
    config:
      max_read_chars: 6000
      timeout_seconds: 20
      allowed_schemes:
        - http
        - https
```

`config` 是硬限制，不是 prompt 约束。它会在 tool 抽象层被校验，并固化到本次 agent 的 tool 实例中。

## 直接调用

```python
from tool_call import ConfiguredTool, ToolCallManager

manager = ToolCallManager([
    ConfiguredTool(
        name="web.fetch_url",
        config={"max_read_chars": 5000},
    )
])

result = manager.call("web.fetch_url", {"url": "https://example.com"})
print(result.output)
```

也可以用 CLI：

```bash
python -m tool_call \
  --tool web.fetch_url \
  --config-json '{"max_read_chars": 5000}' \
  --args-json '{"url": "https://example.com"}'
```

## Tool 编写规范

每个 tool 放在 `/home/ryan/Bybot_V4/tools` 下一个独立 Python 模块中，例如 `tools/web_fetch_url.py`。

模块必须提供 `get_tool_spec()`，返回 `tool_call.ToolSpec`。

每个 tool 必须包含：

- `ConfigModel`: 继承 `pydantic.BaseModel`，描述 agent 配置时允许设置的硬限制
- `ArgsModel`: 继承 `pydantic.BaseModel`，描述运行时调用参数
- `execute(args, config)`: 实际执行逻辑，只接收已经校验过的 `ArgsModel` 和 `ConfigModel`
- `build_pydantic_tool(config)`: 返回给 `pydantic-ai` 挂载的函数；函数内部仍应把参数转成 `ArgsModel` 再调用 `execute`
- `get_tool_spec()`: 返回完整 `ToolSpec`

建议格式：

```python
from pydantic import BaseModel, Field

from tool_call import ToolSpec


class ExampleConfig(BaseModel):
    max_items: int = Field(default=10, ge=1, le=100)


class ExampleArgs(BaseModel):
    query: str = Field(min_length=1)


def execute(args: ExampleArgs, config: ExampleConfig) -> str:
    return args.query[: config.max_items]


def build_pydantic_tool(config: ExampleConfig):
    def example_tool(query: str) -> str:
        args = ExampleArgs.model_validate({"query": query})
        return execute(args, config)

    return example_tool


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="example.tool",
        description="Short action-oriented description.",
        config_model=ExampleConfig,
        args_model=ExampleArgs,
        execute=execute,
        pydantic_tool_factory=build_pydantic_tool,
    )
```

安全要求：

- 不要从 prompt 或模型输出中读取硬限制；只使用 `config`
- 文件类 tool 必须在 `ConfigModel` 中声明工作空间根目录，并在 `execute` 中解析真实路径后检查是否仍在工作空间内
- 网络类 tool 必须在 `ConfigModel` 中声明读取长度、超时、允许 scheme/domain 等限制
- 写操作必须显式配置允许写入，默认只读
- tool 抛出的错误应尽量清楚说明是权限、配置还是参数问题
