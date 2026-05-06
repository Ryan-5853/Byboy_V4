from __future__ import annotations


TOOL_GUIDE = """### 工具清单（名称 + 简接口）

调用规则：
- 先选最少工具完成当前子任务。
- 若返回 `TOOL_ERROR ...`，根据报错改参数或换工具，不切换阶段。

文件系统：
- `filesystem_list_files(path=".", glob="**/*")`
- `filesystem_read_file(path)`
- `filesystem_read_many(paths)`
- `filesystem_file_info(path, include_hash=False)`
- `filesystem_search_text(query, path=".", glob="**/*")`
- `filesystem_write_file(path, content)`
- `filesystem_append_file(path, content, newline=True)`

数据处理：
- `data_parse_json(text)`
- `data_extract_json(text, mode="first")`
- `data_render_template(template, values, safe=True)`

Web：
- `web_fetch_url(url)`
- `web_extract_links(url)`
- `web_post_url(url, data=None, headers=None)`
- `web_fetch_json(url)`
- `web_search(query)`
- `web_download_file(url, path)`

浏览器：
- `browser_render_page(url, wait_until="domcontentloaded", wait_for_selector=None)`
- `browser_capture_requests(url, wait_until="domcontentloaded", wait_for_selector=None)`
- `browser_capture_xhr(url, wait_until="domcontentloaded", wait_for_selector=None)`
- `browser_replay_api(session_id, url, method="GET", data=None, headers=None)`
- `browser_export_session(session_id, path)`
- `browser_import_session(path)`
- `browser_screenshot_page(url, path, wait_until="domcontentloaded", wait_for_selector=None, full_page=True)`

命令工具：
- `process_run_command(command)`

路径约定：
- 本地路径相对工程根目录。
- 输出文件写到 `workspace/...` 路径。
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
如果某位导师无公开主页，`主页URL` 允许为空字符串 `""`，不要丢弃该导师。
如果出现同名导师，必须都保留，禁止去重。

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
- 出现同名导师时全部保留，不要误去重
- 出现无主页导师时也要保留，`主页URL` 可为空字符串
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
- **同名与无主页处理**：同名导师可能真实存在；无主页URL也可能真实存在，不能仅据此判 FAIL。

#### 校验策略
- 先读一次 `{tutors_file}`，先做本地检查：JSON 是否是数组、字段是否齐全、URL 域名和格式是否明显异常。
- 对空 `主页URL`：仅记录“可能无主页”，不要直接作为格式错误。
- 对同名：结合 URL/所属页面判断是否可能为不同人，不要机械判重。
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


def init_school_repair_prompt(
    *,
    school_name: str,
    academy_name: str,
    homepage_url: str,
    tutors_file: str,
    verify_feedback: str,
) -> str:
    url_desc = homepage_url or "（无URL，请先搜索学院官网）"
    return f"""## 任务：修复导师名单

目标院校：**{school_name} {academy_name}**
目标主页：{url_desc}
导师名单文件：`{tutors_file}`

{TOOL_GUIDE}

### 输入

- 原始导师名单文件：`{tutors_file}`
- 校验失败原因（原文）：

```text
{verify_feedback}
```

### 你的目标

在不改变任务边界的前提下修复名单，并覆盖写回 `{tutors_file}`。

### 修复规则

1. 只保留两个字段：`导师姓名`、`主页URL`。
2. 同名导师允许存在，禁止因同名直接删除。
3. 无主页导师允许存在，`主页URL` 可为空字符串 `""`。
4. 仅删除明显坏数据：
   - 非对象项
   - 姓名为空
   - URL 非空但明显不是 URL（不以 http/https 开头）
5. 如能从学院页面补回明显缺失项，可补；不能确认时不要编造。

### 输出要求

- 修复成功并写回后，只回复：
`REPAIR_SUCCESS`
- 如果无法修复到可用状态，只回复：
`REPAIR_FAIL`
- 不要输出额外解释文字。
"""


def explore_prompt(
    *,
    name: str,
    url: str,
    school_name: str,
    academy_name: str,
    test_file: str,
) -> str:
    if not str(url or "").strip():
        return _explore_missing_url_prompt(
            name=name,
            school_name=school_name,
            academy_name=academy_name,
            test_file=test_file,
        )
    return f"""## 任务：探索导师主页

导师姓名：**{name}**
主页URL：{url}
所属项目：{school_name} {academy_name}

{TOOL_GUIDE}

### 你的任务

从已经给出的导师主页 URL 开始，探索如何稳定抓取该主页上的有效信息，并将发现写入 `{test_file}`。

请注意：本阶段不是重新从学院主页发现导师主页地址。正常情况下后续评分 agent 已经拿到了 `主页URL`，访问策略应服务于“给定一个导师主页 URL 后，如何抓到有效信息”。

只有在以下情况才允许考虑学院官网主页、站内列表或 `web_search`：
- 给定 URL 失效、跳转错误、明显不是该导师主页；
- 给定 URL 为空；
- 给定主页可打开但没有任何导师有效信息；
- 页面中明确需要进入同域子页面才能拿到完整信息。

### 执行预算与退出条件

- 目标是**尽快产出可执行证据**，不是做无限探索。
- 工具调用预算建议（软上限）：
  1) 对给定主页 URL 的页面直读/渲染：最多 2 次
  2) 请求抓包（`browser_capture_requests`）：最多 1 次
  3) API 复现（`web_post_url`/`web_fetch_json`）：最多 2 次
- 不要从学院主页开始寻找导师主页；不要把“如何找到 URL”写成主策略。
- 满足以下任一条件应立即写文件并结束：
  - 已确认静态可读，且关键信息可提取；
  - 已确认动态加载路径（如接口 URL + 方法 + 关键参数）；
  - 已确认需要跟进同域子页面（如论文、科研项目、个人简介 tab）才能补全信息；
  - 复现接口连续失败，但失败原因已清楚（如 cookie/session/参数格式问题）。
- 不要因为“还能再试一次”而持续循环；证据足够就收敛。
- 连续 2 次调用同一接口仍失败时，必须停止重试该接口，写入失败留痕并结束。
- 如果页面入口与站点根路径都只返回 challenge 页/202 空白页，直接判定 `ANTI_BOT_CHALLENGE_BLOCKED`，写失败留痕并结束。
- 严禁在思考中重复同一计划；如果你发现自己在重复同一句话，请立即执行“写报告并结束”。

#### 探索清单

1. **页面可访问性**
   - 给定主页 URL 是否正常打开（HTTP 200）？
   - 是否有重定向？
   - 是否跳转到其他页面？跳转后是否仍是该导师主页？

2. **页面技术类型**
   - 是静态 HTML 页面，还是 JavaScript 动态渲染（SPA）？
   - 如果是 SPA/动态渲染，是否可以通过 `web_fetch_url` 获取到有效内容？
   - 是否需要调用后端 API 才能获取完整信息？如果需要，尝试使用 `web_post_url`。
   - 是否存在同域子页面、tab、分页或附件链接，需要从给定主页继续进入？

3. **可获取的有效信息**
   - 导师的研究方向和基本信息（能获取到吗？在页面什么位置？）
   - 论文/专著列表（能获取到吗？）
   - 教育经历/工作经历
   - 联系方式（邮箱、电话等）
   - 课题组信息（学生列表、课题组合影等）

4. **页面结构总结**
   - 页面有几个主要区域/版块？
   - 哪些版块对导师筛选最有价值？
   - 如果存在子页面，哪些子页面值得后续评分 agent 跟进，哪些不值得？
   - 是否需要 POST/API 请求来获取更多信息？
   - 如果需要 API，参数是什么格式？
   - 如果 API 调用失败，失败原因最可能是什么（参数、cookie、header、会话、权限）？
   - 仅当给定 URL 失效/空 URL/无有效信息时，说明是否需要回到学院官网或搜索引擎作为备用路径。

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

（主策略必须从给定 `主页URL` 开始。写清楚：先用什么工具访问该 URL；如何判断静态/动态；如何提取正文、联系方式、研究方向、论文；是否需要跟进同域子页面或 API。只有在 URL 失效/空URL/无有效信息时，才写备用搜索或学院官网路径）

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


def _explore_missing_url_prompt(
    *,
    name: str,
    school_name: str,
    academy_name: str,
    test_file: str,
) -> str:
    return f"""## 任务：探索无主页URL导师的可恢复路径

导师姓名：**{name}**
主页URL：（空）
所属项目：{school_name} {academy_name}

{TOOL_GUIDE}

### 重要背景

这批导师名单中允许存在 `主页URL` 为空的导师。空 URL 不一定是抽取错误，可能表示学院官网没有为该导师公开个人主页。

你的任务不是强行证明每位导师都有主页，而是判断这个空 URL 样本是否能通过低成本检索恢复出可靠主页，并把经验写入 `{test_file}`，供后续生成整体访问策略时参考。

### 执行预算与退出条件

- 目标是**快速判断是否可恢复**，不是无限搜索。
- 工具调用预算建议（软上限）：
  1) `web_search` 最多 2 次；
  2) 候选页面直读/渲染最多 2 次；
  3) 不做 API 抓包，不做站内大规模遍历。
- 搜索优先使用这些关键词：
  - `{school_name} {academy_name} {name} 导师`
  - `{school_name} {name} 个人主页`
- 只接受明显属于 `{academy_name}` 或 `{school_name}` 且能确认是 `{name}` 本人的页面。
- 如果 2 次搜索或 2 个候选页面仍不能确认主页，立即停止，写明“存在根本找不到公开主页的导师”。
- 不要用同名外校、论文库、百度百科、招生目录、新闻稿等页面冒充个人主页。

### 探索清单

1. **空 URL 状态判断**
   - 当前导师在原始名单中 `主页URL` 为空；
   - 说明这类样本会影响整体访问策略，不能按“页面系统失效”处理。

2. **低成本检索恢复**
   - 搜索到了哪些候选？
   - 哪些候选能确认属于本人？
   - 如果找到可靠主页，记录 URL 和确认依据。
   - 如果找不到，记录尝试过的关键词和失败原因。

3. **对整体访问策略的影响**
   - 如果找到了：说明可作为备用方案“姓名 + 学院/学校关键词检索”；
   - 如果找不到：说明策略必须支持 `主页URL` 为空时直接标注无公开主页，不能让后续评分 agent 扩展搜索过久。

#### 输出格式

写入 `{test_file}` 的 markdown 内容格式：

```markdown
# 探索报告：{name}

## 基本信息
- URL: （空）
- 可访问性: 无给定主页URL
- 页面类型: 无主页URL样本

## 空URL说明

（说明该导师在名单中主页URL为空；这批名单存在无公开主页导师，不能据此判定整套主页系统失效）

## 检索尝试

- 搜索关键词 1:
- 结果:
- 搜索关键词 2:
- 结果:

## 可恢复主页

- 是否找到可靠主页: 是/否
- 可靠主页URL: （如有）
- 确认依据: （如学校域名、学院栏目、页面姓名/单位一致）

## 信息获取策略

（如果找到主页，写明如何从空URL恢复到主页；如果没找到，写明后续应快速退出并标注无公开主页）

## 失败留痕

- 最后一次失败调用：工具名 + 参数摘要（脱敏） + 错误原文
- 失败原因判断：一句话
- 下一步最优动作：到此为止 / 记录无公开主页 / 用找到的主页继续
- 重试计数：列出搜索和候选页尝试次数

## 总结

（明确写出：该样本说明名单中存在空URL导师；整体访问策略应包含空URL分支）
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

### 核心约束

这份策略是给后续“单导师评分 agent”使用的。评分 agent 正常情况下已经拿到了每位导师的 `主页URL`，所以策略主路径必须回答：

> 给定一个导师主页 URL 后，如何正确抓到该页面及其必要子页面/API 中的有效信息。

不要把“从学校主页/学院主页一步步找到教师主页地址”写成主流程。那会干扰后续评分 agent。

只有在以下 fallback 情况，才允许写学院官网主页或 `web_search` 路径：
- `主页URL` 为空；
- 给定 URL 404/403/跳转到无关页面/明显不是该导师主页；
- 给定主页可打开但没有任何导师有效信息；
- 给定主页明确指向同域子页面、tab、附件或 API 才能拿到完整信息。

#### 策略内容要求

```markdown
# 页面访问策略：{school_name} {academy_name}

## 主页系统概述

（基于已给导师主页 URL 的测试结果，说明导师主页系统的页面类型、静态/动态特征、是否有统一结构、是否常见同域子页面/API）

## 主路径：从给定导师主页URL抓取信息

（这是最重要的部分。必须从 `{{主页URL}}` 开始，不要从学院主页开始。）

### 第一步：访问给定主页URL

（说明优先使用 `web_fetch_url` 还是 `browser_render_page`；如何判断页面有效；如何处理轻微重定向）

### 第二步：识别页面类型

（静态 HTML / 动态渲染 / 混合 / challenge 页；如何判断）

### 第三步：提取主页正文中的有效信息

（研究方向、邮箱、电话、教育经历、工作经历、论文/项目等分别通常在什么位置、用什么方式提取）

### 第四步：必要时跟进同域子页面或API

（只有当测试报告显示需要时才写。说明哪些链接/tab/API 值得跟进，参数是什么，最多尝试几次）

## 备用路径：URL失效、空URL或主页无信息

（这部分只能作为 fallback，不能放到主路径前面。）

### 空URL处理

（如果测试报告显示存在空 URL，写明：低成本搜索 1-2 次；找不到可靠学校/学院页面就标注无公开主页并退出）

### 给定URL失效处理

（如果 404/403/跳转无关页面，允许做哪些有限修正，如 http/https、去掉语言参数；什么时候停止）

### 主页无有效信息处理

（如果页面可访问但没有导师信息，是否允许回到学院官网或 web_search；限制次数和退出条件）

## 使用工具建议

- 主路径使用什么工具获取信息（`web_fetch_url` / `browser_render_page` / `web_post_url` / `web_fetch_json` 等）
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
- 备选方案（如果给定主页URL失败怎么处理）
- 明确写出：不要在主页URL有效且信息充分时回到学院主页重新找导师主页。
- 如果测试报告显示存在 `主页URL` 为空的导师，必须单独写一个“空URL处理”分支：
  - 先说明这不是主页系统整体失效；
  - 可低成本用“学校/学院 + 导师姓名 + 导师/个人主页”搜索 1-2 次；
  - 找不到可靠学校/学院页面时，应快速标注“无公开主页”，不要让后续 agent 无限检索；
  - 后续评分时应允许主页为空并降低主页完整度，而不是编造 URL。

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
4. 主流程必须从给定 `{{主页URL}}` 开始；学院主页和 `web_search` 只能保留为 URL 失效、空 URL 或主页无信息时的 fallback。
5. 整体控制在 100 行以内。
6. 如果访问有分叉（如页面A可用走方案A，不可用走方案B），用 if/else 分支表述。

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
  如果 {{主页URL}} 为空、失效或无法获取任何信息，才允许有限搜索学校/学院官网与导师姓名
  仍找不到可靠主页时，标注"无公开主页/主页信息不可用"
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

### 主页有效性验证（必须先执行）

给定主页 URL 可能是错误、失效或导师未开通主页。你必须先验证它是否有效。

执行规则（严格）：
1. 先访问给定 `主页URL`（`web_fetch_url` 或 `browser_render_page`）。
2. 若失败，仅允许最多 2 次有限修正尝试（例如：
   - `http`/`https` 切换；
   - 去掉或补上 `?lang=zh`；
   - 同域名下同一路径轻微规范化）。
3. **禁止**扩展到广泛搜索、禁止到处猜测新主页、禁止跨域找“可能的个人主页”。
3.1 **禁止**回到学院教师名录/研究生导师总表进行“反查主页”。
3.2 **禁止**通过遍历学院栏目链接去碰运气寻找导师个人页。
4. 超过 2 次仍无法拿到有效主页内容，立即判定“主页无效”，直接结束当前任务。

当判定“主页无效”时：
- 仍然按照规定输出格式写入 `__OUTPUT_FILE__`；
- 分数字段可填 0；
- `优先级` 填 `D`；
- 在 `本轮初筛说明` 与 `信息留痕` 明确写“给定主页无效，按规则终止，不再扩展搜索”；
- 写完后仅回复“评分已完成”。

### 页面访问策略

以下是经过测试的导师主页访问策略，请参照执行。
如果你发现此策略失效（如页面结构变化、URL 格式不对等），考虑当前导师主页是否无效。
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
- 如果主页无效，按“主页无效”分支直接收敛，不要继续尝试更多路径
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
