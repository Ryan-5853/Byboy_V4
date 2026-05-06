# User 目录 — 你的信息

这是你的专属入口，放你的简历和导师选择偏好。

## 1. 简历文件

把你的简历放在这里（可以同时放多个），支持任意格式：

- `resume.pdf` — PDF 简历
- `resume.docx` — Word 简历
- `resume.tex` — LaTeX 简历
- `resume.txt` — 纯文本简历
- `resume.md` — Markdown 简历

如果有多份（如中英文），系统会用字数最多的作为主要来源。

## 2. 导师选择偏好

**必须填写**: `tutor_favor.json`

这个文件定义了导师选择规则，包括：

| 字段 | 说明 |
|------|------|
| `scoring_dimensions` | 评分维度，每个维度有名称、满分、高/中/低评分指引 |
| `adds` | 加分特征，分 essential / important / nice 三级 |
| `subs` | 扣分特征，分 fatal(一票否决) / strong / mild 三级 |
| `priority_thresholds` | S/A/B/C/D 优先级阈值 |
| `custom_notes` | 自由文本备注 |

### 怎么填？

如果刚拉新仓库，先在根目录运行 `python3 init_project.py`，它会从 `templates/workflow/User/tutor_favor.json` 初始化本地实例文件。

直接用文本编辑器改 `tutor_favor.json`：

- **评分维度**：默认 7 个维度（方向匹配/工程系统匹配/导师风格/录取可行性/经历匹配/主页完整度/套磁可写性）。你可以改评分指引，例如把"方向匹配"的高分门槛设得更高或更低。
- **加分项**：把自己看重的导师特征列出来。`essential` 是必备条件，`important` 是重要加分，`nice` 是锦上添花。
- **扣分项**：想避开的坑。`fatal` 是一票否决（匹配到直接归 D 档），`strong` 是大大减分，`mild` 是轻微减分。
- **自定义备注**：任何想额外强调的偏好，用自由文本写。

## 3. 目录结构

```
User/
├── README.md              ← 本文件
├── tutor_favor.json       ← 导师选择偏好（必填）
├── resume.pdf             ← 简历（可选，格式不限）
├── resume.tex
├── resume.md
#（简历文件按需放入，支持 pdf/docx/tex/txt/md，不限制文件名）
└── ...其他简历文件
```

## 提示

- `tutor_favor.json` 是整个系统的**灵魂文件** — 它决定了怎么评分、什么好什么不好。花时间把它调精准，后续结果质量会高很多。
- 模板更新后，再运行一次 `python3 init_project.py`；脚本会尽量补齐新字段，同时保留你已经写过的本地配置。
- 填完后在工程根目录运行 `python -m workflow build-profile` 生成个人档案，然后按 `workflow/README_WORKFLOW.md` 的指引继续（init-school → explore → gen-prompts → full）。
- 这里放的是用户输入，不要把 API key、token 之类敏感信息放进来；敏感配置统一放工程根目录 `.env` / `.env.local`。
