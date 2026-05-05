# workflow 架构

## 核心理念：程序编排，Agent 执行

**Agent 不做决策，Agent 只完成被精确描述的任务。**
程序控制流程，subagent 完成原子级操作。

---

## 目录结构

```
workflow/
├── ARCHITECTURE.md          ← 本文件
├── orchestrator.py          ← 兼容主编排入口
├── workflow.py              ← Python 状态机与流程控制
│
├── User/                    ← 用户入口（你的信息）
│   ├── README.md            ← 使用说明
│   ├── tutor_favor.json     ← 导师选择偏好（必填，固定格式）
│   ├── profile.md           ← 个人档案（由 build-profile 生成）
│   └── resume.*             ← 简历（pdf/docx/tex/txt/md，可选）
│
└── config/
    └── workflow.yaml        ← 步骤模型、工具限制、上下文管理配置
```

运行数据位于工程根目录的 `workspace/`，日志位于工程根目录的 `logs/`，通用 agent 框架位于工程根目录的 `framework/`。

---

### workflow/User/ 目录说明

用户信息全部隔离在 `workflow/User/` 目录，不依赖外部文件：

- **`tutor_favor.json`** — 必填。固定格式，定义了评分维度、加分/扣分特征、优先级阈值。是整个系统的**灵魂文件**。
- **简历文件** — 可选。支持 PDF / Word / LaTeX / TXT / MD 任意格式。`python -m workflow build-profile` 会自动选取最大的文件提取文本，结合导师偏好生成 `profile.md`。

### 完整流程

```
===== 第1步：构建个人档案 =====
  workflow/User/resume.*
  workflow/User/tutor_favor.json
      │
      └──→ build-profile ──→ subagent 读取并提取
              ↓
          workflow/User/profile.md          ← 标准化个人档案


===== 第2步：初始化学校导师名录 =====
  workspace/school_info.json
  ├── school_name
  ├── academy_name
  └── homepage_url
      │
      └──→ init-school ──→ subagent 寻访主页
              ↓                 提取导师名单
          workspace/{project}/   分析 URL 规律
          ├── school_profile.md
          ├── page_pattern.md
          ├── tutors_data.json
          └── access_log.md


===== 第3步：构建页面访问策略 =====
  workspace/{project}/
  │
  ├──→ explore  ──→ 串行测试 5 个导师主页
  │                              → 每个 subagent 独立分析
  │                              → 综合生成 page_pattern.md
  │
  └──→ condense-pattern ──→ 精简 page_pattern.md 为可执行指令
                                  → page_pattern_condensed.md


===== 第4步：批量生成分析 Prompt =====
  workflow/User/profile.md              ← 学生档案
  page_pattern_condensed.md    ← 页面访问策略
  tutors_data.json             ← 导师名单
      │
      └──→ gen-prompts ──→ 注入姓名 + URL
              ↓                 → 每个导师生成独立 prompt
          prompts/prompt_{序号}_{姓名}.md


===== 第5步：执行分析 =====
  prompts/ 目录
      │
      ├──→ test <prompt_file>    单测
      ├──→ batch <from> <to>     批量（序号范围）
      └──→ full                  全量分析
              ↓
          output/(test|full)/
          └── tutor_{seq}_{name}.json
```

---

## 关键设计原则

1. **Agent 无流程决策权** — 每一步做什么、下一步做什么，都由脚本决定
2. **上下文隔离** — 每个 subagent 只看到自己的任务描述，不持有全局状态
3. **可重入性** — eval_state.json 跟踪每个导师的 `unanalyzed → running → done → checked` 状态，可随时中断/重启
4. **双通道输出** — test 和 full 输出目录分离，不影响正式结果
5. **并行可控** — `--parallel N` 控制并行 subagent 数量，`--batch-size N` 控制批结算频率

---

## 对比 v2 的改进

| 特性 | v2 | v3 |
|------|----|----|
| 流程控制 | Agent 手动走（WORKFLOW.md 指引） | Shell 脚本编排 |
| 学生信息入口 | 手工编写 student_profile.json | 简历 + build_profile.sh 自动提取 |
| 审计 | 无 | run_audit.sh 可审计输出质量 |
| 恢复 | 读 STATE.md 手动恢复 | eval_state.json 自动恢复 |
| 页面探索 | 手工分析 | explore_pages.sh 串行 5 个 subagent |
| 可重复 | 依赖操作者步骤一致 | 脚本保证一致 |
