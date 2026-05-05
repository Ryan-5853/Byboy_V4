from __future__ import annotations


TOOL_GUIDE = """### 工具总则

1. 先选最小必要工具，不要一次调用过多工具。
2. 先本地读写，再联网抓取；先文本抓取，再浏览器渲染。
3. 每次调用前明确目标字段，避免“先抓一大堆再筛”。
4. 如返回 `TOOL_ERROR ...`，只修正本任务的参数后重试，不要切换阶段。
5. 同一路径连续 2 次“无新增信息”（空返回、同样错误、同样片段）时，不要继续同参重放；必须换途径。
6. 如果已确认目标站点处于统一挑战页/反爬拦截状态，立即收敛并输出失败留痕，不要继续扩展到缓存站、镜像站、Wayback、无关搜索。

### 文件系统工具（工程根内）

- `filesystem_list_files(path=".", glob="**/*")`
  用途：列出目录下文件，定位输入/输出文件。
  关键参数：`path` 目录，`glob` 过滤模式。
  返回：路径字符串列表。

- `filesystem_read_file(path)`
  用途：读取单个文本文件。
  关键参数：`path` 相对工作区路径。
  返回：文件文本。

- `filesystem_read_many(paths)`
  用途：一次读取多个小文件，做对比/汇总。
  关键参数：`paths` 路径数组。
  返回：对象数组，包含 `path`、`content`、`truncated`。

- `filesystem_file_info(path, include_hash=False)`
  用途：查看文件元信息（大小、时间、是否存在）。
  关键参数：`include_hash=True` 时会计算 hash（更慢）。
  返回：文件信息对象。

- `filesystem_search_text(query, path=".", glob="**/*")`
  用途：在本地文件中查关键字。
  关键参数：`query`、`path`、`glob`。
  返回：命中片段数组（含文件路径和行信息）。

- `filesystem_write_file(path, content)`
  用途：写入/覆盖文本文件（常用于最终产物）。
  关键参数：`path`、`content`。
  返回：写入结果（路径、字符数）。

- `filesystem_append_file(path, content, newline=True)`
  用途：向日志类文件追加内容。
  关键参数：`newline` 控制是否补换行。
  返回：追加结果。

### 数据工具

- `data_parse_json(text)`
  用途：严格解析 JSON 字符串。
  返回：JSON 对象/数组；非法 JSON 会报错。

- `data_extract_json(text, mode="first")`
  用途：从混杂文本中提取 JSON 片段。
  场景：页面文本里夹杂 JSON、模型返回含解释文字。
  返回：提取出的 JSON（按 `mode`）。

- `data_render_template(template, values, safe=True)`
  用途：简单模板渲染，批量生成结构化文本。
  返回：渲染后的字符串。

### Web 文本抓取工具（优先使用）

- `web_fetch_url(url)`
  用途：GET 网页并返回清洗后的可读文本。
  场景：静态页面正文抓取、快速读取公告/列表。
  返回：文本字符串。

- `web_extract_links(url)`
  用途：提取页面中的链接 URL。
  场景：先找“教师名录/师资队伍/下一页/各系入口”。
  返回：链接数组。

- `web_post_url(url, data=None, headers=None)`
  用途：POST 请求抓取页面或接口返回文本。
  场景：站点用表单提交或 POST API 获取内容。
  返回：文本字符串。
  失败诊断：
  - 若返回空字符串或 `sql error`，优先判断参数编码/会话上下文问题；
  - 连续 2 次无新增后，改用 `browser_capture_requests` 或 `browser_render_page` 抽取可用信息，不要原样重试。

- `web_fetch_json(url)`
  用途：GET 并解析 JSON 接口。
  场景：站点前端走 JSON API 时直接取结构化数据。
  返回：JSON 对象/数组。

- `web_search(query)`
  用途：外部搜索入口页面。
  场景：找官网、找学院名录入口、找备用网址。
  返回：结果数组（`title`、`url`、`snippet`）。

- `web_download_file(url, path)`
  用途：下载文件到 workspace。
  场景：下载 PDF/附件后再做后处理。
  返回：下载结果（写入字节数等）。

### 浏览器渲染工具（动态页面/JS 页面时使用）

- `browser_render_page(url, wait_until="domcontentloaded", wait_for_selector=None)`
  用途：用真实浏览器渲染页面，返回 `title`、`text`、`html`、`links`。
  场景：`web_fetch_url` 抓不到正文、页面依赖 JS 渲染。
  参数建议：
  - 首选 `wait_until="domcontentloaded"`；
  - 仅在必要时用 `networkidle`；
  - 知道关键节点时再加 `wait_for_selector`。
  返回：结构化对象（含 `final_url`、`status`、`wait_until`）。

- `browser_capture_requests(url, wait_until="domcontentloaded", wait_for_selector=None)`
  用途：渲染页面同时抓取网络请求（重点是 `xhr` / `fetch` / `document`）。
  场景：排查 SPA 动态加载路径，定位真实 API（如 `TeacherHome/teacherBody.do`）和请求方法。
  返回：结构化对象，包含 `requests` 数组，每条含 `resource_type`、`method`、`url`、`status`、
  `request_post_data`、`content_type` 等字段。
  使用建议：
  - 先用它识别“哪个请求返回核心内容”；
  - 再用 `web_post_url` 或 `web_fetch_json` 复现关键请求；
  - 若需要页面证据，可再配合 `browser_screenshot_page`。

- `browser_capture_xhr(url, wait_until="domcontentloaded", wait_for_selector=None)`
  用途：抓取 XHR/fetch，并生成可复用的 `session_id`（含 cookie/storage state）。
  场景：接口需要会话上下文时，先抓包建立会话，再重放 API。
  返回：包含 `session_id` 与 `requests` 列表。
  使用建议：
  - 对需要 cookie 的接口，优先走 `browser_capture_xhr`；
  - 从 `requests` 里提取真实参数（如数字 `id` / `data-tid`）；
  - 不要猜测 UUID 或用户名去硬试 API。

- `browser_replay_api(session_id, url, method="GET", data=None, headers=None)`
  用途：在 `browser_capture_xhr` 建立的同一会话中重放 API 请求。
  场景：`web_post_url` 因会话缺失失败、或接口依赖前置页面状态。
  返回：结构化对象（`status`、`ok`、`content_type`、`response_body`）。
  使用建议：
  - 先用抓包结果中的请求参数与 header 最小复现；
  - 若返回业务失败（如 `sql error`），必须改参数来源或改路径，不能原样重试。

- `browser_export_session(session_id, path)`
  用途：把当前进程中的浏览器会话导出到 workspace JSON 文件。
  场景：人工过盾后长期复用会话、跨任务复用。
  返回：写入路径与字符数。

- `browser_import_session(path)`
  用途：从 workspace JSON 文件导入会话，得到新的 `session_id`。
  场景：重启后恢复已保存的过盾会话。
  返回：新的 `session_id`。

- `browser_screenshot_page(url, path, wait_until="domcontentloaded", wait_for_selector=None, full_page=True)`
  用途：渲染后截图，写入 workspace 文件。
  场景：调试页面是否正确打开、记录证据。
  返回：截图结果（路径、字节数、状态码）。

### 受限命令工具（诊断/转换）

- `process_run_command(command)`
  用途：在工作区内执行 allowlist 内的本地命令。
  典型场景：
  - 网页诊断：`curl` 抓原始 HTML，配合 `grep/head/sed` 抽样查看脚本与关键片段；
  - 文档转换：`pdftotext`、`pandoc` 处理简历或附件文本。
  关键限制：
  - `command` 不是 shell；它会按参数拆分执行；
  - 只能执行允许的命令名；
  - 不支持 shell 管道、重定向、变量替换、here-doc、命令替换等复杂 shell 行为；
  - **禁止**写 `|`、`>`, `>>`, `<`, `2>&1`, `&&`, `||`, `;`；
  - 如果你想“先 curl 再 head/grep/sed”，必须拆成多次工具调用，不能写成一条 shell 命令；
  - 超时和输出长度受配置限制。
  返回：结构化对象（`returncode`、`stdout`、`stderr`）。

### 反爬/挑战页快速识别

如果出现以下任意组合，视为“站点被统一挑战页拦截”：

- `web_fetch_url` 返回几乎空白的 HTML，但包含长混淆 JS、`$_ts`、动态 challenge 脚本等特征；
- `browser_render_page` 连续 2 次返回 `status=202` 且 `title/text/html` 基本为空；
- 根路径和目标路径都只返回相同模式的挑战页；
- `browser_capture_requests` 没有抓到可直接复现的业务接口，只看到 challenge 资源。

一旦确认上述状态：

1. 不要继续微调同一路径参数；
2. 不要继续尝试 Wayback、缓存页、泛搜索、无关镜像；
3. 立即写失败留痕，明确标注：
   - `ANTI_BOT_CHALLENGE_BLOCKED`
   - 已尝试的路径
   - 关键证据（202 空白页 / challenge JS 特征 / 无业务接口）
   - 建议下一步（人工浏览器取 cookie、换网络、人工导出名单）
4. 当前任务若要求必须写产物文件，就写最小失败产物并结束。

### 路径与错误处理

- 所有本地路径相对于工程根目录。
- 用户输入位于 `workflow/User/`，工作流配置位于 `workflow/config/`，元提示位于 `workflow/meta/`。
- 项目输出文件必须写到 `workspace/` 前缀路径，例如
  `workspace/学校_学院/tutors_data.json`。
- 如果返回 `TOOL_ERROR ...`：
  1) 先检查 URL、路径、参数名、等待策略；
  2) 改参数后重试同一任务；
  3) 若同一路径连续 2 次无新增信息，必须换工具路径（例如 `browser_capture_requests` → `browser_render_page`）；
  4) 不要把错误当成新用户需求，不要切换阶段。
"""


def build_profile_prompt() -> str:
    return f"""## 任务：构建个人档案

你现在在工程根目录下。查找 `workflow/User/` 目录读取用户文件。

{TOOL_GUIDE}

请执行以下步骤：

### 步骤 1：读取输入

读取 `workflow/User/tutor_favor.json` 获取导师选择偏好。

然后读取简历文件：找 `workflow/User/resume.*` 或 `workflow/User/cv.*` 或 `workflow/User/简历.*` 中最大的文件。
如果存在 `workflow/meta/_resume_extracted.txt`，优先读取它作为简历正文。

### 步骤 2：生成本人档案

综合简历内容和导师偏好，生成 markdown 并写入 `workflow/User/profile.md`，必须包含以下章节：

```markdown
# 个人档案

> 一句话概括：XXX

## 基础信息

- 姓名：（从简历提取，找不到写"待确认"）
- 学校/专业：（从简历提取）
- 年级：（从简历提取）
- GPA/排名：（从简历提取）
- 英语水平：（从简历提取）
- 联系方式：（从简历提取，找不到写"待确认"）

## 项目经历

按重要性排序，每条：
- **项目名称**（角色）— 时间
  - 技术要点：XXX
  - 成果/奖项：XXX

## 技术栈

- **核心领域：** XXX
- **编程语言：** XXX
- **框架/工具：** XXX
- **硬件平台：** XXX

## 荣誉与竞赛

按时间倒序排列。

## 导师选择偏好

从 tutor_favor.json 中提取，按以下分类：

### 评分维度
- XXX（满分XX）：XXX

### 加分特征
- XXX — 必备
- XXX — 重要
- XXX — 加分

### 扣分特征
- XXX — 一票否决
- XXX — 强烈减分
- XXX — 轻微减分

### 优先级阈值
S≥XX, A≥XX, B≥XX, C≥XX

### 自定义备注
- XXX

## 个人定位总结

根据你的经历和偏好，总结最适合什么样的课题组、应避开什么样的课题组，用于导师筛选时的快速匹配参考。
```

### 步骤 3：写入文件

使用 `filesystem_write_file` 工具将生成的 markdown 写入 `workflow/User/profile.md`。

### 要求
- 简历中明确有的信息必须保留，没有的字段写"待确认"
- 项目经历用自然语言归纳，不要照搬原文
- 导师选择偏好从 `tutor_favor.json` 原样提取，不要改动原意
- 确认文件已写入后回复"个人档案已生成"
"""


def init_school_extract_prompt(
    *,
    school_name: str,
    academy_name: str,
    homepage_url: str,
    tutors_file: str,
    project_dir: str,
) -> str:
    url_desc = homepage_url or "（无URL，请先用 web_search 搜索学院官网找到主页）"
    return f"""## 任务：提取导师名单

目标院校：**{school_name} {academy_name}**
目标主页：{url_desc}

{TOOL_GUIDE}

### 核心目标：只提取导师姓名和主页URL。

除姓名和主页URL外，**本阶段不需要职称、所属系、研究方向等任何其他信息**。
无需逐页翻找每条额外信息，只拿姓名和主页链接即可。

### 步骤

#### 第一步：找到学院官网
访问目标 URL；如果目标 URL 为空或不可用，使用 `web_search` 搜索 "{school_name} {academy_name}" 找到准确的学院官网。

#### 第二步：找到导师名录页面
在学院官网找到"师资队伍"、"教师名录"、"导师介绍"等版块。
确认是 {academy_name} 的导师列表，不是全校或跨院系页面。

### 执行预算与早停规则

- 页面直读/渲染总预算：最多 4 次
- 请求抓包（`browser_capture_requests`）：最多 1 次
- 搜索（`web_search`）：最多 2 次
- 受限命令诊断（`process_run_command`）：最多 2 次

满足以下任一条件时，立即停止扩展探索并结束：

1. 已成功拿到完整导师名单并写入文件；
2. 已确认站点被统一挑战页/反爬保护拦截，无法在当前工具条件下拿到名单；
3. 连续 2 条不同路径都只返回相同挑战页或相同空白 202 页面；
4. 搜索/缓存路径没有提供新的学院名录入口。

如果触发条件 2/3/4：

- 仍然写入 `{project_dir}/access_log.md`
- 明确记录 `ANTI_BOT_CHALLENGE_BLOCKED`
- 记录最后验证过的入口 URL、页面状态、挑战页特征
- 不要继续尝试 Wayback、百度快照、更多搜索词变体
- 本轮不要写伪造名单

#### 第三步：提取导师名单（仅姓名+主页URL）

从页面上提取每位导师的姓名和对应的个人主页链接。
如果列表分页，请翻页获取所有导师。如果按系分组，请合并所有系的数据。
可以使用 `web_fetch_url` 阅读页面正文，使用 `web_extract_links` 提取候选链接。

#### 第四步：写入 JSON

将结果写入 `{tutors_file}`，JSON 数组格式：

```json
[
  {{
    "导师姓名": "张三",
    "主页URL": "https://example.edu/zhangsan"
  }},
  {{
    "导师姓名": "李四",
    "主页URL": "https://example.edu/lisi"
  }}
]
```

**JSON 只包含 `导师姓名` 和 `主页URL` 两个字段，不要添加其他字段。**

#### 第五步：写入访问日志（可选但推荐）

将关键访问路径、判断依据和无法确认的点写入 `{project_dir}/access_log.md`。
如果失败，必须写失败留痕，至少包含：

```markdown
# 访问留痕

- 结论：ANTI_BOT_CHALLENGE_BLOCKED / 部分成功 / 成功
- 目标主页：...
- 已尝试入口：
  - ...
  - ...
- 关键证据：
  - `web_fetch_url` 返回 challenge JS
  - `browser_render_page` 返回 202 空白页
  - `browser_capture_requests` 未发现可复现业务接口
- 建议下一步：
  - 人工浏览器获取 cookie 后再试
  - 或人工导出导师名单
```

### 要求
- 只提取 {academy_name} 的导师，不要扩大到其他学院
- 尽可能找全所有导师
- 如果页面 JS 动态加载导致 `web_fetch_url` 获取不到列表，用 `web_extract_links`、`web_post_url` 或 `web_search` 尝试替代来源
- 如果已确认统一挑战页/反爬拦截，停止继续搜索和猜路径，写失败留痕后结束
- 确认 `{tutors_file}` 写入成功后回复"名单已生成"
- 如果失败留痕已写完，回复"名单提取失败，已写访问留痕"
- **不要输出任何其他内容，只写入文件后回复确认**
"""


def init_school_verify_prompt(
    *,
    school_name: str,
    academy_name: str,
    homepage_url: str,
    tutors_file: str,
) -> str:
    url_desc = homepage_url or "（无URL，请用 web_search 搜索学院官网）"
    return f"""## 任务：校验导师名单质量

目标院校：**{school_name} {academy_name}**
导师名单文件：`{tutors_file}`

{TOOL_GUIDE}

### 你的任务

1. 读取 `{tutors_file}`
2. 访问学院主页 {url_desc}，或通过 `web_search` 搜索 "{school_name} {academy_name} 导师名录"
3. 检查以下内容：

#### 检查清单
- **完整性**：名单覆盖了所有导师吗？导师人数是否合理？
- **遗漏**：是否有明显缺失的导师或某个系/研究所完全没有被覆盖？
- **名称错误**：导师姓名是否准确（没有错别字、同音字、多字少字）？
- **URL 合理性**：主页URL是否指向每个人的个人主页（而不是学院首页或空链接）？
- **跨院系**：是否有其他学院的导师混入？

#### 校验策略
- 先读一次 `{tutors_file}`，先做本地检查：JSON 是否是数组、字段是否齐全、URL 域名和格式是否明显异常。
- 再做**有限外部抽查**：优先访问学院官网师资入口页，再抽查少量关键页面确认是否存在明显遗漏或明显错链。
- **不要**为了“完全证明”而无休止搜索；拿到足够证据后立即输出结论。
- 如果已经发现明确 FAIL 证据，就直接输出 `VERIFY_FAIL`，不要继续扩展搜索。
- 如果没有明确 FAIL 证据，但也无法完全确认，就输出 `VERIFY_PASS`，备注“无法完全确认”及原因。
- 总共只做少量网页请求，避免反复尝试同类 URL 或重复搜索同一个问题。

#### 输出要求

如果名单完整、格式正确、没有明显问题，回复：
```
VERIFY_PASS
备注：XXX
```

如果发现以下问题，回复：
```
VERIFY_FAIL
- 问题1：XXX
- 问题2：XXX
- 建议补充的来源：XXX
```

### 重要
- 不要问用户确认，直接给出 PASS 或 FAIL
- 如果无法完全确认，也给出 PASS，备注"无法完全确认"及原因
- 判断重点是**明显遗漏**（如某系完全缺失）和**明显错误**（如URL全是学院首页）
- 输出结论后立刻停止，不要继续思考后续修复方案，不要继续搜索更多页面
"""


def explore_prompt(
    *,
    name: str,
    url: str,
    school_name: str,
    academy_name: str,
    test_file: str,
) -> str:
    return f"""## 任务：探索导师主页

导师姓名：**{name}**
主页URL：{url}
所属项目：{school_name} {academy_name}

{TOOL_GUIDE}

### 你的任务

访问该导师的个人主页，探索以下内容，将发现写入 `{test_file}`：

### 执行预算与退出条件

- 目标是**尽快产出可执行证据**，不是做无限探索。
- 工具调用预算建议（软上限）：
  1) 页面直读/渲染：最多 2 次
  2) 请求抓包（`browser_capture_requests`）：最多 1 次
  3) API 复现（`web_post_url`/`web_fetch_json`）：最多 2 次
- 满足以下任一条件应立即写文件并结束：
  - 已确认静态可读，且关键信息可提取；
  - 已确认动态加载路径（如接口 URL + 方法 + 关键参数）；
  - 复现接口连续失败，但失败原因已清楚（如 cookie/session/参数格式问题）。
- 不要因为“还能再试一次”而持续循环；证据足够就收敛。
- 连续 2 次调用同一接口仍失败时，必须停止重试该接口，写入失败留痕并结束。
- 如果页面入口与站点根路径都只返回 challenge 页/202 空白页，直接判定 `ANTI_BOT_CHALLENGE_BLOCKED`，写失败留痕并结束。
- 严禁在思考中重复同一计划；如果你发现自己在重复同一句话，请立即执行“写报告并结束”。

#### 探索清单

1. **页面可访问性**
   - 页面是否正常打开（HTTP 200）？
   - 是否有重定向？
   - 是否跳转到其他页面？

2. **页面技术类型**
   - 是静态 HTML 页面，还是 JavaScript 动态渲染（SPA）？
   - 如果是 SPA/动态渲染，是否可以通过 `web_fetch_url` 获取到有效内容？
   - 是否需要调用后端 API 才能获取完整信息？如果需要，尝试使用 `web_post_url`。

3. **可获取的有效信息**
   - 导师的研究方向和基本信息（能获取到吗？在页面什么位置？）
   - 论文/专著列表（能获取到吗？）
   - 教育经历/工作经历
   - 联系方式（邮箱、电话等）
   - 课题组信息（学生列表、课题组合影等）

4. **页面结构总结**
   - 页面有几个主要区域/版块？
   - 哪些版块对导师筛选最有价值？
   - 是否需要 POST/API 请求来获取更多信息？
   - 如果需要 API，参数是什么格式？
   - 如果 API 调用失败，失败原因最可能是什么（参数、cookie、header、会话、权限）？

#### 输出格式

写入 `{test_file}` 的 markdown 内容格式：

```markdown
# 探索报告：{name}

## 基本信息
- URL: {url}
- 可访问性: （可访问/无法访问/重定向）
- 页面类型: （静态/动态SPA/混合）

## 页面结构

（描述页面布局、主要版块、信息位置）

## 可获取的信息

- ✅ 研究方向：在页面哪个位置，内容是否完整
- ✅ 论文列表：是否可获取，在什么位置
- ❌ 邮箱：页面没有
- ✅ 教育经历：有，在底部
- ...

## 信息获取策略

（具体操作步骤，如：用 `web_fetch_url` 访问首页，提取某个字段，或需要先取得 data-tid 再调 API）

## 失败留痕

- 最后一次失败调用：工具名 + 参数摘要（脱敏） + 错误原文
- 失败原因判断：一句话
- 下一步最优动作：一句话（重试参数 / 换工具 / 到此为止）
- 重试计数：列出每个关键接口尝试次数（例如 `teacherBody.do: 2 次`）

## 总结

（对这个页面访问的总体评价，是否有价值，访问难度如何）
```

写入完成后回复"测试完成"。不要继续调用其他工具。
"""


def synthesize_pattern_prompt(
    *,
    school_name: str,
    academy_name: str,
    total_count: int,
    effective_count: int,
    test_reports: str,
    pattern_file: str,
) -> str:
    return f"""## 任务：综合生成页面访问策略

项目：{school_name} {academy_name}
有效测试数：{effective_count} / {total_count}

{TOOL_GUIDE}

### 测试报告汇总

以下是 {total_count} 个导师主页的探索报告：

{test_reports}

### 你的任务

综合以上测试报告，生成一份通用的页面访问策略，写入 `{pattern_file}`。

#### 策略内容要求

```markdown
# 页面访问策略：{school_name} {academy_name}

## 主页系统概述

（这个学校用的是什么主页系统？整体技术架构？）

## 访问步骤

（按顺序列出获取导师信息的完整操作步骤）

### 第一步：XXX
### 第二步：XXX
### ...

## 使用工具建议

- 使用什么工具获取信息（`web_fetch_url` / `web_post_url` / `web_extract_links` 等）
- 参数/Header格式
- 常见坑点

## 信息获取对照表

| 信息类型 | 位置/方法 | 成功率 | 备注 |
|---------|----------|-------|------|
| 研究方向 | ... | 高/中/低 | ... |
| 论文 | ... | ... | ... |
| 邮箱 | ... | ... | ... |
| 教育经历 | ... | ... | ... |

## 注意事项

- 哪些页面容易404
- 特殊处理（如需要URL编码的汉字拼音）
- 备选方案（如果某步失败怎么处理）

## 总体评价

（基于 {effective_count} 个有效测试样本，评估该主页系统的可访问性和信息丰富度）
```

写入完成后回复"访问策略已生成"。
"""


def condense_pattern_prompt(
    *,
    school_name: str,
    academy_name: str,
    pattern_file: str,
    condensed_file: str,
) -> str:
    return f"""## 任务：精简页面访问策略

文件：`{pattern_file}`

{TOOL_GUIDE}

### 你的任务

读取 `{pattern_file}`，然后重写一份精简版到 `{condensed_file}`。

### 要求

1. **去废话**：去掉背景介绍、比喻、解释性文字、建议与提示等指导性内容。
2. **只留可执行指令**：每一步都是 subagent 可以直接照做的具体操作。
3. **使用哪些工具、参数怎么传、拿到什么数据**，写清楚就行。
4. 整体控制在 100 行以内。
5. 如果访问有分叉（如页面A可用走方案A，不可用走方案B），用 if/else 分支表述。

### 格式示例

```
访问策略：{school_name} {academy_name} 导师主页

第一步：获取 data-tid
  用 web_fetch_url 访问 {{主页URL}}
  在 <div class="teacher-body" data-tid="..."> 中提取 data-tid 的值
  如果页面 404，尝试 {{主页URL}} 去掉 ?lang=zh 参数

第二步：调 API 获取完整信息
  用 web_post_url 调用 https://example.edu/api
  Header/Body: ...
  返回 HTML，包含研究领域、论文、教育经历等完整内容

第三步：从HTML中提取信息
  研究领域：...
  论文列表：...
  邮箱：...

第四步：备用方案
  如果以上步骤无法获取任何信息，标注"主页信息不可用"
```

要求简洁明了、无废话、无解释、subagent 直接能执行。
写入后回复"精简完成"。
"""


def tutor_eval_prompt(
    *,
    seq: str,
    name: str,
    url: str,
    school_name: str,
    academy_name: str,
    access_strategy: str,
    student_info: str,
) -> str:
    return f"""## 任务：导师分析与评分

你正在参与一个导师筛选系统。你的任务是分析一位导师的个人主页，
提取关键信息，并根据给定的评分标准进行评分。

{TOOL_GUIDE}

### 目标导师

- **姓名：** {name}
- **主页URL：** {url}
- **所属项目：** {school_name} {academy_name}

### 行为限制

- **不得**访问目标导师主页以外的任何页面。如果主页中的链接指向无关页面（如学院首页、其他导师主页、外部论文数据库等），不要点击。
- **不得**爬到其他学院、其他导师的信息。只分析 {academy_name} 的这位导师。
- 如果页面无法访问或信息不足，如实标注，不要编造。
- 如果某个 tool 调用失败或被拦截，请根据错误信息修改参数后重试，或改用其他工具路径完成同一任务。
- 不要把 tool 错误当成新的用户需求，不要切换工作流阶段。

### 页面访问策略

以下是经过测试的导师主页访问策略，请严格按此执行。
如果你发现此策略失效（如页面结构变化、URL 格式不对等），
可以自由使用当前框架允许的网页工具尝试获取信息。

{access_strategy}

### 学生信息与导师选择偏好

以下是被筛选学生的完整档案，包含个人信息、项目经历、技术栈、
导师选择偏好（评分维度、加分特征、扣分特征、优先级阈值）：

{student_info}

### 输出要求

将评分结果写入 `__OUTPUT_FILE__`，格式如下：

```json
{{
  "序号": "{seq}",
  "导师姓名": "{name}",
  "研究方向摘要": "",
  "方向匹配_20": 0,
  "工程系统匹配_20": 0,
  "导师风格与氛围_20": 0,
  "录取可行性_15": 0,
  "经历匹配_15": 0,
  "主页完整度_5": 0,
  "套磁可写性_5": 0,
  "总分": 0,
  "优先级": "",
  "主匹配项目": "",
  "套磁切入角度": "",
  "风险点": "",
  "邮箱": "",
  "本轮初筛说明": "",
  "信息留痕": ""
}}
```

填入实际评分值。完成后回复"评分已完成"，不要重复输出 JSON 内容。

### 注意事项

- 研究方向摘要要完整（包括研究领域、项目类型、学生成果等）
- 每项评分都要有信息依据，记录在"信息留痕"字段中
- 如果页面信息不足，相关维度填低分并注明原因
- 优先级阈值和评分维度见上方"导师选择偏好"中的定义
- 扣分特征中的"一票否决"项应直接归入 D 档
"""


def fix_eval_json_prompt(*, output_file: str, name: str, validate_message: str) -> str:
    return f"""## 任务：修正导师评分 JSON 文件

上一轮分析 **{name}** 时输出的 JSON 文件格式有问题。
请读取现有的文件 `{output_file}`（如果存在），修正后重新写入。

{TOOL_GUIDE}

### 格式要求
必须是一个合法的 JSON 对象，包含以下字段：
- "序号": 字符串
- "导师姓名": 字符串
- "研究方向摘要": 字符串（50-100字）
- "方向匹配_20": 整数（1-20）
- "工程系统匹配_20": 整数（1-20）
- "导师风格与氛围_20": 整数（1-20）
- "录取可行性_15": 整数（1-15）
- "经历匹配_15": 整数（1-15）
- "主页完整度_5": 整数（1-5）
- "套磁可写性_5": 整数（1-5）
- "总分": 整数
- "优先级": 字符串（S/A/B/C/D）
- "主匹配项目": 字符串
- "套磁切入角度": 字符串
- "风险点": 字符串
- "邮箱": 字符串
- "所属系": 字符串
- "本轮初筛说明": 字符串（详细分析）
- "信息留痕": 字符串（每项评分的来源依据）

### 校验提示
{validate_message}

### 重要
- 直接修改文件 `{output_file}`
- 确保 JSON 字符串值中的引号被正确转义
- 修改后回复"文件已修正"
"""


def audit_prompt(
    *,
    meta_version: str,
    student_profile: str,
    scoring_criteria: str,
    audit_checklist: str,
    recent_results: str,
    file_count: int,
    batch_count: int,
) -> str:
    return f"""## 审计任务

你正在审计导师筛选系统的输出结果质量。请根据以下清单检查最近完成的几批结果。

{TOOL_GUIDE}

### 当前元框架版本: v{meta_version}

### 学生背景

{student_profile}

### 评分标准

{scoring_criteria}

### 审计清单

{audit_checklist}

### 最近输出结果样本（最多5个）

{recent_results}

### 审计要求

1. 逐条检查审计清单中的每个项目
2. 找出评分不一致、摘要不完整、信息留痕不足等问题
3. 评估当前元框架是否存在系统性缺陷：
   - subagent prompt 是否清晰？
   - 评分标准是否合理？
   - 访问策略是否有效？
   - 是否有频繁出现的错误模式？
4. 如果发现问题，给出 **具体的修正建议**（针对 workflow/meta/ 中的哪个文件、改什么）
5. 如果未发现问题，明确声明

### 输出格式

按以下 JSON 格式输出审计报告：

```json
{{
  "meta_version": "{meta_version}",
  "audit_batch_range": "最近 {batch_count} 批",
  "total_checked": {file_count},
  "issues_found": [
    {{
      "severity": "high|medium|low",
      "file": "涉及的文件或结果",
      "description": "问题描述",
      "suggestion": "修正建议"
    }}
  ],
  "systemic_problems": ["描述1", "描述2"],
  "framework_change_needed": true,
  "recommended_actions": [
    "将 scoring_criteria.md 中的 XX 维度下调权重",
    "subagent_prompt.md 的访问策略部分增加 YY 说明"
  ],
  "overall_quality": "good|fair|needs_improvement"
}}
```

如果 framework_change_needed 为 true，应对 workflow/meta/ 中对应的文件做修正。
"""
