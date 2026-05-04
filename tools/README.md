# tools

这里存放所有可被 `tool_call` 发现和路由的项目工具。

当前分类：

- `web`: 网页读取、链接提取、POST 请求、网页搜索
- `filesystem`: 受 workspace 限制的本地文件读、写、列举、搜索
- `data`: 数据解析和转换

## 可用工具

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

## 编写新工具

请遵循 [tool_call/README.md](/tool_call/README.md) 中的 `ToolSpec` 接口规范。新工具建议按类别放入子包，例如：

- `tools/web/my_tool.py`
- `tools/filesystem/my_tool.py`
- `tools/data/my_tool.py`
