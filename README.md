# Byboy_V4

`Byboy_V4` 是一个用于导师筛选与评估的 Python agent 工程。现在工程分成四层：

- `framework/`：agent 驱动、模型路由、工具层、上下文管理。
- `workflow/`：导师筛选业务流程、提示词、用户输入模板、Web UI。
- `workspace/`：学校配置、导师名单、访问策略、分析输出。
- `logs/`：agent 运行日志、上下文缓存、旧流程归档。

## 环境准备

```bash
cd <repo>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
python3 init_project.py
```

## 敏感信息配置

敏感信息不要再直接写进 YAML 或代码。统一放在工程根目录：

- `.env`：默认本地配置
- `.env.local`：本机覆盖配置，优先级高于 `.env`

项目会自动加载这两个文件，不需要每次手工 `export`。当前由 [config_loader.py](/framework/llm_select/config_loader.py) 在读取模型配置时自动向上查找并加载。

推荐流程：

1. 复制 `.env.example` 为 `.env`
2. 填入你要用的 API key
3. 如果某台机器需要特殊覆盖，额外新建 `.env.local`

### `.env.example`

```dotenv
LOCAL_OPENAI_API_KEY=
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
WEBUI_PORT=8897
```

字段说明：

- `LOCAL_OPENAI_API_KEY`：本地 OpenAI-compatible 服务需要鉴权时使用；不需要可留空。
- `DEEPSEEK_API_KEY`：DeepSeek 云端模型使用。
- `OPENAI_API_KEY`：OpenAI 官方模型使用。
- `WEBUI_PORT`：Web UI 端口，不是敏感信息，但放 env 里更方便迁移。

## 配置文件分工

### 1. 模型层

- `templates/framework/llm_select/models.yaml`：模型配置模板（Git 跟踪）
- `framework/llm_select/models.yaml`：本地模型配置实例（`python3 init_project.py` 自动生成/更新）

用途：

- 定义模型别名
- 指定 provider、真实模型名、上下文窗口、默认参数
- 非敏感后端地址可以保留在这里

不要直接写真实密钥。应该写成：

```yaml
api_key: ${DEEPSEEK_API_KEY}
```

### 2. 工作流层

- `templates/workflow/config/workflow.yaml`：工作流配置模板（Git 跟踪）
- `workflow/config/workflow.yaml`：本地工作流配置实例（`python3 init_project.py` 自动生成/更新）

用途：

- 配置每个步骤默认用哪个模型别名
- 配置 `usage_limits`
- 配置 `context_management`
- 配置 `tool_limits`

这里主要改“流程行为”，不是存密钥。

### 3. 用户输入层

- `templates/workflow/User/tutor_favor.json`：导师偏好模板（Git 跟踪）
- `workflow/User/tutor_favor.json`：本地导师偏好实例（`python3 init_project.py` 自动生成/更新）
- `workflow/User/resume.*`：简历源文件
- `workflow/User/profile.md`：由 `build-profile` 自动生成
- [workflow/User/README.md](/workflow/User/README.md)：用户输入说明

### 4. 运行数据层

- `templates/workspace/school_info.json`：初始化模板（Git 跟踪）
- `templates/workspace/active_project.json`：当前项目模板（Git 跟踪）
- `workspace/school_info.json`：本地初始化配置实例
- `workspace/active_project.json`：本地当前激活学院实例
- `workspace/<学校>_<学院>/...`

用途：

- `school_info.json` 只作为第一次执行 `init-school` 时的初始化配置输入
- `active_project.json` 记录当前激活学院
- 导师名单
- 页面访问策略
- prompt
- 分析结果
- 状态文件

说明：

- 首次克隆或模板更新后，先运行 `python3 init_project.py`
- 初始化完成后，实际工作流不再依赖 `workspace/school_info.json` 里的 `project_id`
- 每个学院目录现在自带自己的 `project_info.json`
- WebUI 会根据 `active_project.json` 动态切换当前学院

### 5. 日志层

- `logs/agent_runs/`：每个 agent 的实时对话、工具调用、工具返回
- `logs/context_cache/`：超长工具返回的原文缓存
- `logs/legacy_openclaw_archive/`：旧 OpenClaw 流程归档

## 常用命令

```bash
python -m workflow status
python -m workflow build-profile
python -m workflow init-school
python -m workflow explore
python -m workflow condense-pattern
python -m workflow gen-prompts
python -m workflow full --parallel 1
python -m workflow report
python workflow/webui.py
```

## 建议先看的 README

- 根目录 README：整体结构、敏感信息配置、文件分工
- [workflow/README_WORKFLOW.md](/workflow/README_WORKFLOW.md)：怎么跑业务流程
- [framework/llm_select/README.md](/framework/llm_select/README.md)：模型别名与 `.env` 占位写法
- [framework/context_manage/README.md](/framework/context_manage/README.md)：上下文压缩配置
- [framework/tools/README.md](/framework/tools/README.md)：工具能力与参数
- [workflow/User/README.md](/workflow/User/README.md)：用户输入怎么填

## 已完成的安全改动

- `framework/llm_select/models.yaml` 中的真实 DeepSeek key 已移除
- 模型 key 统一改为 `${ENV_NAME}` 占位
- `.env` / `.env.local` 自动加载已经接入
- `.gitignore` 已忽略 `.env`、`.env.local` 和其他 `.env.*`，保留 `.env.example`
