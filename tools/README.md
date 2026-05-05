# tools

这里存放所有可被 `tool_call` 发现和路由的项目工具。

当前分类：

- `web`: 网页读取、链接提取、POST 请求、网页搜索、JSON 抓取、文件下载
- `browser`: 真实浏览器渲染、渲染后文本提取、截图
- `filesystem`: 受 workspace 限制的本地文件读、写、追加、列举、搜索、元信息查询、批量读取
- `data`: 数据解析、JSON 提取、模板渲染
- `process`: 受 allowlist 限制的本地命令执行

## 可用工具

### 浏览器运行时准备

浏览器类工具默认使用本地 `playwright` 后端。首次启用需要：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

如果在其他环境迁移，通常只需要同样两步。安装完成后，`browser.*` 工具就能直接被 `tool_call` 发现和挂载。

### `browser.render_page`

使用真实浏览器渲染页面，返回渲染后的标题、正文文本、HTML 和链接列表，适合处理 SPA、JS 动态注入内容、客户端渲染页面。

```yaml
tools:
  - name: browser.render_page
    config:
      backend: playwright
      browser_name: chromium
      headless: true
      timeout_seconds: 30
      max_html_chars: 200000
      max_text_chars: 30000
      max_links: 200
      allowed_schemes: [http, https]
      allowed_domains:
        - "hit.edu.cn"
        - "*.hit.edu.cn"
      viewport_width: 1440
      viewport_height: 1080
      block_resource_types: [image, media, font]
```

调用参数：

```json
{"url": "https://seie.hit.edu.cn/", "wait_until": "networkidle", "wait_for_selector": ".teacher-list"}
```

配置字段：`backend` 当前支持 `playwright`；`browser_name` 选择浏览器；`headless` 控制无头模式；`timeout_seconds` 限制单次渲染超时；`max_html_chars`、`max_text_chars`、`max_links` 限制返回体积；`allowed_domains`、`allowed_schemes` 做网络边界限制；`viewport_width`、`viewport_height` 固定渲染视口；`block_resource_types` 可屏蔽图片、媒体、字体等资源以节省时间。

调用字段：`url` 是目标地址；`wait_until` 是导航完成条件；`wait_for_selector` 可选，用于等待关键 DOM 出现。

### `browser.screenshot_page`

使用真实浏览器渲染页面并截图，写入 workspace 内允许的位置。

```yaml
tools:
  - name: browser.screenshot_page
    config:
      workspace_root: 
      allow_write: true
      backend: playwright
      browser_name: chromium
      headless: true
      timeout_seconds: 30
      allowed_schemes: [http, https]
      allowed_domains:
        - "hit.edu.cn"
        - "*.hit.edu.cn"
      allowed_globs:
        - "workspace/**/*.png"
      image_type: png
      max_image_bytes: 10000000
      overwrite: false
```

调用参数：

```json
{"url": "https://seie.hit.edu.cn/", "path": "workspace/debug/seie-home.png", "wait_until": "networkidle", "full_page": true}
```

配置字段：`workspace_root` 是写入根目录；`allow_write` 必须显式为 `true`；`allowed_globs` 限制可写路径；`image_type` 支持 `png`/`jpeg`；`max_image_bytes` 限制截图大小；其余浏览器字段含义与 `browser.render_page` 一致。

调用字段：`url` 是目标地址；`path` 是 workspace 内相对输出路径；`wait_until`、`wait_for_selector` 控制页面等待；`full_page` 控制是否整页截图。

### `web.fetch_url`

抓取 URL，并返回清洗后的正文。

```yaml
tools:
  - name: web.fetch_url
    config:
      max_read_chars: 5000
      timeout_seconds: 20
      follow_redirects: true
      allowed_schemes: [http, https]
```

调用参数：

```json
{"url": "https://example.com"}
```

配置字段：`max_read_chars` 限制返回正文长度；`timeout_seconds` 限制 HTTP 请求超时；`follow_redirects` 控制是否跟随重定向；`allowed_schemes` 限制 URL scheme。

调用字段：`url` 是要抓取的网页地址。

### `web.extract_links`

抓取网页并提取 anchor 链接。

```yaml
tools:
  - name: web.extract_links
    config:
      max_links: 50
      timeout_seconds: 20
      same_host_only: false
      allowed_schemes: [http, https]
```

调用参数：

```json
{"url": "https://example.com"}
```

配置字段：`max_links` 限制返回链接数量；`timeout_seconds` 限制 HTTP 请求超时；`follow_redirects` 控制是否跟随重定向；`allowed_schemes` 限制 URL scheme；`same_host_only` 为 `true` 时只返回同 host 链接。

调用字段：`url` 是要提取链接的网页地址。

### `web.post_url`

向 URL 发起 POST 请求，并返回清洗后的正文。

```yaml
tools:
  - name: web.post_url
    config:
      max_read_chars: 50000
      timeout_seconds: 30
      follow_redirects: true
      allowed_schemes: [http, https]
      default_headers: {}
```

调用参数：

```json
{"url": "https://example.com/api", "data": {"id": "123"}, "headers": {"Content-Type": "application/x-www-form-urlencoded"}}
```

配置字段：`max_read_chars` 限制返回正文长度；`timeout_seconds` 限制 HTTP 请求超时；`follow_redirects` 控制是否跟随重定向；`allowed_schemes` 限制 URL scheme；`default_headers` 是默认请求头。

调用字段：`url` 是请求地址；`data` 是表单数据、字符串或空；`headers` 是本次请求头。

### `web.search`

搜索网页并返回结果列表。

```yaml
tools:
  - name: web.search
    config:
      max_results: 8
      max_read_chars: 12000
      timeout_seconds: 20
```

调用参数：

```json
{"query": "哈尔滨工业大学 电子与信息工程学院 导师名录"}
```

配置字段：`max_results` 限制返回条数；`max_read_chars` 限制搜索结果页读取长度；`timeout_seconds` 限制 HTTP 请求超时。

调用字段：`query` 是搜索关键词。

### `web.fetch_json`

抓取 URL 并将响应解析成 JSON。

```yaml
tools:
  - name: web.fetch_json
    config:
      max_read_chars: 200000
      timeout_seconds: 30
      follow_redirects: true
      allowed_schemes: [http, https]
      default_headers: {}
```

调用参数：

```json
{"url": "https://example.com/data.json", "headers": {}}
```

配置字段：`max_read_chars` 限制响应正文长度；`timeout_seconds` 限制请求超时；`follow_redirects` 控制重定向；`allowed_schemes` 限制 URL scheme；`default_headers` 是默认请求头。

调用字段：`url` 是 JSON 地址；`headers` 是本次请求头。

### `web.download_file`

下载 URL 内容到 workspace 内文件。默认禁止写入，必须显式配置 `allow_write: true`。

```yaml
tools:
  - name: web.download_file
    config:
      workspace_root: 
      allow_write: true
      max_bytes: 10000000
      timeout_seconds: 60
      allowed_globs:
        - "workspace/**"
      overwrite: false
```

调用参数：

```json
{"url": "https://example.com/file.pdf", "path": "workspace/tmp/file.pdf"}
```

配置字段：`workspace_root` 是写入根目录；`allow_write` 必须为 `true`；`max_bytes` 限制下载大小；`timeout_seconds` 限制请求超时；`allowed_schemes` 限制 URL scheme；`allowed_globs` 限制写入路径；`overwrite` 控制是否覆盖。

调用字段：`url` 是下载地址；`path` 是 workspace 内相对保存路径。

### `filesystem.list_files`

列出 workspace 内文件。

```yaml
tools:
  - name: filesystem.list_files
    config:
      workspace_root: 
      max_results: 200
      include_hidden: false
      allowed_globs:
        - "**/*.py"
        - "**/*.md"
```

调用参数：

```json
{"path": ".", "glob": "**/*.py"}
```

配置字段：`workspace_root` 是允许访问的工作空间根目录；`max_results` 限制返回条数；`include_hidden` 控制是否包含隐藏路径；`allowed_globs` 限制允许返回的文件模式。

调用字段：`path` 是 workspace 内相对目录；`glob` 是在该目录下匹配文件的 glob。

### `filesystem.read_file`

读取 workspace 内文本文件。

```yaml
tools:
  - name: filesystem.read_file
    config:
      workspace_root: 
      max_read_chars: 20000
      allowed_globs:
        - "**/*.py"
        - "**/*.md"
```

调用参数：

```json
{"path": "agent_router/README.md"}
```

配置字段：`workspace_root` 是允许访问的工作空间根目录；`max_read_chars` 限制读取字符数；`allowed_globs` 限制可读取文件；`encoding` 指定文本编码。

调用字段：`path` 是 workspace 内相对文件路径。

### `filesystem.read_many`

一次读取多个 workspace 文本文件，适合对比多个小文件。

```yaml
tools:
  - name: filesystem.read_many
    config:
      workspace_root: 
      max_files: 10
      max_read_chars_per_file: 20000
      max_total_chars: 100000
      allowed_globs:
        - "**/*.md"
        - "**/*.json"
```

调用参数：

```json
{"paths": ["README.md", "config/workflow.yaml"]}
```

配置字段：`workspace_root` 是允许访问的根目录；`max_files` 限制单次读取文件数；`max_read_chars_per_file` 限制单文件读取长度；`max_total_chars` 限制总返回长度；`allowed_globs` 限制可读文件。

调用字段：`paths` 是 workspace 内相对文件路径列表。

### `filesystem.file_info`

查看文件或目录元信息，可选计算文件 SHA256。

```yaml
tools:
  - name: filesystem.file_info
    config:
      workspace_root: 
      max_hash_bytes: 20000000
      allowed_globs:
        - "**/*"
```

调用参数：

```json
{"path": "README.md", "include_hash": true}
```

配置字段：`workspace_root` 是允许访问的根目录；`allowed_globs` 限制可查询文件；`max_hash_bytes` 限制允许计算 hash 的最大文件大小。

调用字段：`path` 是 workspace 内相对路径；`include_hash` 控制是否计算 SHA256。

### `filesystem.search_text`

在 workspace 内搜索文本。

```yaml
tools:
  - name: filesystem.search_text
    config:
      workspace_root: 
      max_results: 100
      max_file_read_chars: 200000
      include_hidden: false
      allowed_globs:
        - "**/*.py"
        - "**/*.md"
```

调用参数：

```json
{"query": "ToolSpec", "path": ".", "glob": "**/*.py"}
```

配置字段：`workspace_root` 是允许访问的工作空间根目录；`max_results` 限制匹配结果数；`max_file_read_chars` 限制每个文件最多读取字符数；`include_hidden` 控制是否搜索隐藏路径；`allowed_globs` 限制可搜索文件；`encoding` 指定文本编码。

调用字段：`query` 是搜索文本或正则；`path` 是 workspace 内相对路径；`glob` 是文件匹配模式；`regex` 控制是否按正则搜索；`case_sensitive` 控制大小写敏感。

### `filesystem.write_file`

写入 workspace 内文本文件。默认禁止写入，必须显式配置 `allow_write: true`。

```yaml
tools:
  - name: filesystem.write_file
    config:
      workspace_root: 
      allow_write: true
      max_write_chars: 20000
      create_dirs: false
      overwrite: false
      allowed_globs:
        - "tmp/*.md"
```

调用参数：

```json
{"path": "tmp/out.md", "content": "hello"}
```

配置字段：`workspace_root` 是允许写入的工作空间根目录；`allow_write` 必须为 `true` 才允许写；`max_write_chars` 限制写入字符数；`allowed_globs` 限制可写文件；`create_dirs` 控制是否自动创建父目录；`overwrite` 控制是否允许覆盖已有文件；`encoding` 指定文本编码。

调用字段：`path` 是 workspace 内相对文件路径；`content` 是写入内容。

### `filesystem.append_file`

向 workspace 内文本文件追加内容。默认禁止写入，必须显式配置 `allow_write: true`。

```yaml
tools:
  - name: filesystem.append_file
    config:
      workspace_root: 
      allow_write: true
      max_append_chars: 20000
      create_dirs: true
      allowed_globs:
        - "workspace/**/*.md"
```

调用参数：

```json
{"path": "workspace/log.md", "content": "- 新记录", "newline": true}
```

配置字段：`workspace_root` 是允许写入的根目录；`allow_write` 必须为 `true`；`max_append_chars` 限制单次追加长度；`allowed_globs` 限制可写文件；`create_dirs` 控制是否自动创建父目录。

调用字段：`path` 是 workspace 内相对文件路径；`content` 是追加内容；`newline` 控制是否自动补换行。

### `data.parse_json`

解析 JSON 字符串。

```yaml
tools:
  - name: data.parse_json
    config:
      max_input_chars: 100000
```

调用参数：

```json
{"text": "{\"ok\": true}"}
```

配置字段：`max_input_chars` 限制输入 JSON 字符串长度。

调用字段：`text` 是待解析 JSON 字符串。

### `data.extract_json`

从混杂文本中提取 JSON 对象或数组。

```yaml
tools:
  - name: data.extract_json
    config:
      max_input_chars: 200000
      max_results: 10
```

调用参数：

```json
{"text": "说明文字 {\"ok\": true}", "mode": "first"}
```

配置字段：`max_input_chars` 限制输入文本长度；`max_results` 限制 `mode=all` 时最多返回多少段 JSON。

调用字段：`text` 是待扫描文本；`mode` 可为 `first` 或 `all`。

### `data.render_template`

使用 Python `string.Template` 做安全文本替换，不执行代码。

```yaml
tools:
  - name: data.render_template
    config:
      max_template_chars: 100000
      max_value_chars: 50000
```

调用参数：

```json
{"template": "Hello $name", "values": {"name": "Ryan"}, "safe": true}
```

配置字段：`max_template_chars` 限制模板长度；`max_value_chars` 限制每个值的长度。

调用字段：`template` 是模板文本；`values` 是替换字典；`safe` 为 `true` 时缺失变量会原样保留。

### `process.run_command`

在 workspace 内运行 allowlist 中的本地命令。该工具不是通用 shell，不支持管道、重定向或命令拼接。

```yaml
tools:
  - name: process.run_command
    config:
      workspace_root: 
      allowed_commands:
        - pdftotext
        - pandoc
      timeout_seconds: 60
      max_output_chars: 50000
```

调用参数：

```json
{"command": "pdftotext User/resume.pdf -"}
```

配置字段：`workspace_root` 是命令运行目录；`allowed_commands` 是允许执行的可执行文件名；`timeout_seconds` 限制运行时间；`max_output_chars` 限制 stdout/stderr 返回长度；`extra_env` 可添加固定环境变量。

调用字段：`command` 是命令字符串，会用 `shlex.split` 拆分，并以 `shell=False` 执行。

## 编写新工具

请遵循 [tool_call/README.md](/tool_call/README.md) 中的 `ToolSpec` 接口规范。新工具建议按类别放入子包，例如：

- `tools/web/my_tool.py`
- `tools/filesystem/my_tool.py`
- `tools/data/my_tool.py`

## 工具错误协议（给模型）

当工具调用失败或被拦截时，返回值应为 `TOOL_ERROR ...` 文本，而不是让 agent 崩溃。
当前框架会把异常和旧式 `TOOL_ERROR` 自动规范为以下引导式格式：

```text
TOOL_ERROR <tool_name>: 你的上一次toolcall失败了/被拦截了，因为 <ErrorType>: <message>。
请你修改参数后重新提交toolcall，或者改用其他方式完成同一任务。
```

建议工具实现时尽量提供清晰错误原因（权限、参数、路径、网络、超时等），
以便模型可以基于错误信息自动修正下一次调用。
