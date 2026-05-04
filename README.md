# BYboy_V4 — 导师筛选系统

BYboy_V4 是一套基于 Python 和 `pydantic-ai` 的轻量化 Agent 工作流执行框架，专为**导师筛选与评估**这一核心业务需求而打造。它可以自动根据你的个人简历和偏好，去目标院校寻找导师列表，并结合网页搜索能力分析导师的契合度，最终给出结构化的匹配报告。

本系统最初由 V3 架构控制流迁移并重构而来，专注于将原有使用 Bash 难以维护的工作流升级为模块化、易扩展、易于调试的纯 Python 工程，并将agent基座从openclaw这样面向用户的巨大后端改为面向脚本、高度自定义、轻量化的pydantic-ai。

## 核心特点

1. **继承 v3 架构的优秀工作流程**：保留了原 v3 版本成熟的“构建个人档案 → 抓取名录 → 探索页面策略 → 批量生成 Prompt → 执行 LLM 分析与校验”这一多步状态机交互逻辑。原有 `.sh` 工作流与旧版代码归档至 `tutor_select_v3/legacy/`。
2. **改用 `pydantic-ai` 作为 Agent 后端框架**：基于 `pydantic-ai` 重构底座，提供类型安全、配置极度简化的模型通信与工具调用管理方案，大幅降低了组件之间的整合成本。
3. **全面 Python 化**：彻底告别 shell 脚本！原有的流控制全部更改为 Python 代码运行，极大地提升了系统可读性。支持原生断点调试、错误回溯处理，二次扩展更为容易。

## 目录结构与模块架构

工程通过高内聚的解耦模块划分，使 Agent 运行流更加清晰：

* **`tutor_select_v3/`**
  核心工作流执行层的 Python 版本。目前的主流程控制入口，包含了状态调度、文件状态机以及工作区数据处理。支持 `status`, `build-profile`, `init-school`, `explore` 等阶段任务。
    * `User/`：你的个人档案、简历与导师偏好配置。
    * `workspace/`：运行时的学校配置、抓取的数据及输出报告。
* **`agent_router/`**
  工作流控制层和 `pydantic-ai` 之间的路由转发业务。通过传入任务 YAML 和 Prompt 模板来创建受限的 Agent 实例。
* **`tool_call/`**
  全局工具调用抽象层，管理并挂载 `tools` 工具。提供细粒度的硬限制环境（指定工作区间、超时限制、文本读取阈值等）。
* **`llm_select/`**
  后端模型别名及凭证管理层。支持简易别名底层映射具体的模型与 API 进行多模型灵活切换。
* **`context_manage/`**
  针对超长文任务（如导师网页抓取）的上下文兜底压缩层，到达预定义 token 比例时主动触发模型压缩核心内容，防止防爆限制。
* **`tools/`**
  核心功能插件集（文件操作、WEB 请求、URL 解析、搜索引擎）。

## 快速配置及运行

### 环境准备

项目使用常见的虚拟环境进行隔离安装：

```bash
cd 

# 激活你的 python 虚拟环境 (例如使用 venv)
python3 -m venv .venv
source .venv/bin/activate

# 安装相关依赖包
pip install -r requirements.txt
```

### 核心工作流执行步骤

你可以按顺序运行工作流（**这是本系统的核心串行逻辑**）：

**1. 构建个人档案**
读取 `tutor_select_v3/User/` 下的简历（resume.pdf/docx/tex/txt/md）与偏好模板 `tutor_favor.json`，分析生成统一的个人档案 `profile.md`。
```bash
python -m tutor_select_v3 build-profile
```

**2. 初始化学校导师名录**
在此之前请确保配置了 `tutor_select_v3/workspace/school_info.json`。自动探索学院页面获取导师名单（JSON 格式）。
```bash
python -m tutor_select_v3 init-school
```

**3. 构建与精简页面访问策略**
随机抽取学校的 5 个导师页面，摸底模式并生成精简的 `page_pattern_condensed.md`。
```bash
python -m tutor_select_v3 explore
python -m tutor_select_v3 condense-pattern
```

**4. 批量生成分析 Prompt**
整合任务目标、行为限制、你的档案与访问策略，并注入每位导师的姓名+URL，生成各自的独立文件在 `prompts/`。
```bash
python -m tutor_select_v3 gen-prompts
```

**5. 导师匹配度分析与产出**
通过大模型深度调查资料为您输出打分。利用状态机跟踪每个导师进度：`unanalyzed → running → done → checked`，自动断点续传。
```bash
# 单测验证某位导师
python -m tutor_select_v3 test workspace/<project>/prompts/prompt_1_xxx.md

# 批量执行分析序号范围（支持并发）
python -m tutor_select_v3 batch 1 10 --parallel 1

# 全量分析所有导师
python -m tutor_select_v3 full --parallel 1

# 汇总评分结果做图表及总结
python -m tutor_select_v3 report
```

### 其他常用命令

```bash
# 查看各个导师状态及执行进度一览
python -m tutor_select_v3 status

# 全程指定使用的别名模型
python -m tutor_select_v3 full --model local-default
```

