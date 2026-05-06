# workflow Python 工作流

这是从旧 OpenClaw 工作区迁移到当前框架后的 Python 控制版本。

旧 Bash 脚本、原始固定提示词和旧 orchestrator 已归档到：

```text
logs/legacy_openclaw_archive/
```

主动运行的流程控制入口改为：

```bash
cd <repo>
.venv/bin/python -m workflow status
.venv/bin/python -m workflow build-profile
.venv/bin/python -m workflow init-school
.venv/bin/python -m workflow explore
.venv/bin/python -m workflow condense-pattern
.venv/bin/python -m workflow gen-prompts
.venv/bin/python -m workflow test workspace/<project>/prompts/prompt_1_xxx.md
.venv/bin/python -m workflow batch 1 10 --parallel 1
.venv/bin/python -m workflow full --parallel 1
.venv/bin/python -m workflow report
```

Windows PowerShell 等价写法：

```powershell
cd <repo>
.venv\Scripts\python.exe -m workflow status
.venv\Scripts\python.exe -m workflow build-profile
.venv\Scripts\python.exe -m workflow init-school
.venv\Scripts\python.exe -m workflow explore
.venv\Scripts\python.exe -m workflow condense-pattern
.venv\Scripts\python.exe -m workflow gen-prompts
.venv\Scripts\python.exe -m workflow test workspace\<project>\prompts\prompt_1_xxx.md
.venv\Scripts\python.exe -m workflow batch 1 10 --parallel 1
.venv\Scripts\python.exe -m workflow full --parallel 1
.venv\Scripts\python.exe -m workflow report
```

也可以直接执行：

```bash
.venv/bin/python workflow/orchestrator.py status
```

Windows：

```powershell
.venv\Scripts\python.exe workflow\orchestrator.py status
```

Web UI 入口也已迁移，页面和原接口保持一致，后端任务改为调用 Python orchestrator：

```bash
cd <repo>
.venv/bin/python workflow/webui.py
```

Windows：

```powershell
cd <repo>
.venv\Scripts\python.exe workflow\webui.py
```

默认地址：

```text
http://localhost:8897
```

可用 `WEBUI_PORT=8898` 改端口。

Windows PowerShell 改端口示例：

```powershell
$env:WEBUI_PORT = "8898"
.venv\Scripts\python.exe workflow\webui.py
```

## 项目选择与激活学院

`workspace/school_info.json` 现在只负责第一次初始化学院时提供输入：

- `school_name`
- `academy_name`
- `homepage_url`

执行 `init-school` 后：

- 实际项目数据会写入 `workspace/<学校>_<学院>/`
- 当前激活学院会写入 `workspace/active_project.json`
- 每个学院目录会写入自己的 `project_info.json`

后续 `explore`、`condense-pattern`、`gen-prompts`、`full`、`report` 都默认基于“当前激活学院”运行，而不是继续依赖 `school_info.json`。

Web UI 顶部也支持用下拉框切换所有已存在学院，切换后下方状态、结果、进度和当前学院导师名单都会同步切换。

## 模型配置

工作流层只使用模型别名，不写后端地址和 token。

后端模型地址、真实模型名和默认参数模板仍在：

```text
framework/llm_select/models.yaml
```

真实密钥不要直接写在 `models.yaml`，改为用工程根目录 `.env` / `.env.local` 注入，例如：

```yaml
api_key: ${DEEPSEEK_API_KEY}
```

`.env.local` 会覆盖 `.env`，适合放本机私有配置。

本工作流的步骤到模型别名映射在：

```text
workflow/config/workflow.yaml
```

字段说明：

- `default_model_alias`：默认模型别名；未使用 `--per-step-model` 时所有步骤都用它。
- `step_model_aliases`：按步骤指定模型别名；使用 `--per-step-model` 时生效。
- `usage_limits`：传给 pydantic-ai 的运行限制。`max_total_tokens: unlimited` 表示不限制总 token 流量。
- `context_management`：上下文压缩配置；默认在 80% 阈值触发。
- `tool_limits`：本工作流给工具层的硬限制，如文件读写长度、网页读取长度、链接数量和超时。
- `tool_limits.search_backend`：网页搜索后端，默认 `auto`。会优先使用本地 SearXNG，失败时回退到内置 DuckDuckGo 搜索；可配 `searxng_url` 和 `auto_start_searxng`。

命令行 `--model <alias>` 会覆盖本次命令的所有步骤：

```bash
.venv/bin/python -m workflow full --model local-default
```

## 工具名

提示词已从旧 OpenClaw 工具名调整为当前 pydantic-ai 暴露的工具名：

- `filesystem_list_files`
- `filesystem_read_file`
- `filesystem_write_file`
- `filesystem_search_text`
- `data_parse_json`
- `web_fetch_url`
- `web_extract_links`
- `web_post_url`
- `web_search`

工具授权与参数边界由生成的 subagent config 传给 `tool_call` 检查。
