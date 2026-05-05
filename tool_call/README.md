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
- 当模型调用 tool 时，如果参数被安全策略拦截或执行失败，返回 `TOOL_ERROR ...` 字符串给模型，让模型修正请求后重试；不直接抛异常打断整个 subagent

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
- 浏览器类 tool 必须在 `ConfigModel` 中声明允许访问的 scheme/domain、渲染超时、返回体积上限；如果涉及截图或下载，也必须声明 workspace 写入边界
- 写操作必须显式配置允许写入，默认只读
- tool 抛出的错误应尽量清楚说明是权限、配置还是参数问题

## 错误返回约定

挂载给模型的 pydantic tool 必须遵守“失败返回，不崩 agent”的约定：

```text
TOOL_ERROR <tool_name>: 你的上一次toolcall失败了/被拦截了，因为 <ErrorType>: <message>。
请你修改参数后重新提交toolcall，或者改用其他方式完成同一任务。
```

`ToolCallManager.as_pydantic_tools()` 会在所有 tool 外层统一兜底，并将：

- 运行时抛出的异常
- tool 内部返回的旧格式 `TOOL_ERROR ...`

统一规范为上面的引导式错误文本，确保模型明确知道“上一次调用失败的原因”以及“下一步动作（改参数重提或换工具路径）”。

注意：`ToolCallManager.call(...)` 和 CLI 直调仍会抛出异常，方便测试、CI 和人工调试发现问题。只有模型运行时挂载的 pydantic tool 会自动转成 `TOOL_ERROR`。
