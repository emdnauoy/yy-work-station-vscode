# 规则体系说明（给 Cursor / AI Agent 参考）

本文档说明本仓库规则体系的整体设计、迁移决策，以及各 AI 工具的配合方式。受众：Cursor 及任何在此仓库工作的 AI Agent。

## 整体结构

```
AGENTS.md                      ← 唯一入口（硬约束 + 编辑前必读导航）
.agent/rules/
├── yy-global.md               ← alwaysApply，唯一详述源
├── authoring-rules.md         ← 规则写法约定
├── api-patterns.md            ← API 核心约定 + 翻译（globs: tasks/**/*.py）
├── api-logging.md             ← 操作日志（globs: tasks/**/view/**/*.py）
├── api-patterns-ref.md        ← 接口参考模板（按需）
├── data-script.md             ← 数据脚本约定（globs: tasks/**/scripts/**/*.py 等）
├── karpathy-guidelines.md     ← 行为准则详细原文（按需）
└── tasks/
    ├── distribution_order.md  ← 子任务规则
    ├── offline_customer.md    ← 子任务规则（含 contract / sellout 细分）
    ├── code_analys.md         ← 子任务规则
    └── _example.md            ← 新任务模板
```

## 设计原则

1. **单一事实源** — 每项规范只在一处详述，其余仅指针引用，杜绝双写漂移。
2. **入口薄、详述厚** — `AGENTS.md` 只留硬约束与导航（约 0.9KB）；完整约定全在 `yy-global.md`。
3. **硬约束 alwaysApply** — 仅 `yy-global.md` 始终注入；其余按需读。
4. **跨 harness 通用** — 规则放 `.agent/rules/`（`agents` 约定），omp / Codex / Gemini 自动发现；不依赖任何单一工具的私有目录。

完整规则清单（含加载范围）见 `.agent/rules/yy-global.md` 的「规则文件清单」节。

## 为什么是 `.agent` 而不是 `.cursor`（迁移决策）

本仓库规则原分散在三套，内容高度重叠、靠「源文件 CLAUDE.md」注释互相引用，必漂移：

- `.cursor/rules/*.mdc`（Cursor 分拆规则）
- 根 `CLAUDE.md` + `tasks/*/CLAUDE.md`（Claude Code 完整规范）
- 根 `AGENTS.md`（速查）

且根 `CLAUDE.md`（最完整规范）在 omp 下根本不被加载——omp 只认 `.claude/CLAUDE.md`，不认 standalone `CLAUDE.md`。

迁移后统一到 `.agent/rules/`，融合了 `CLAUDE.md` 独有的「View 骨架」「异常约定」「行为准则」等内容，删除三套重复源。

**tradeoff**：`.agent/` 不是 Cursor 约定，Cursor 不认其 `globs` 自动附加——原「编辑 `.py` 自动加载 api-patterns」失效。代价由 `AGENTS.md` 的「编辑前必读」弥补：每次会话读 `AGENTS.md`，按其导航手动读对应规则。

## 各工具如何配合

| 工具 | 发现机制 | 实际用法 |
|------|----------|----------|
| Cursor | 读根 `AGENTS.md` | 按「编辑前必读」手动读 `.agent/rules/*.md` |
| omp | `agents` provider 自动发现 `.agent/rules/*.md` | globs 仅提示，同样按 `AGENTS.md` 导航 |
| Codex / Gemini | `.agent/` + `AGENTS.md` | 同上 |
| Claude Code | 读根 `AGENTS.md` | 同上 |

## 给 Cursor 的实操清单

1. 会话开始：读根 `AGENTS.md`，记住 11 条硬约束。
2. 编辑 `tasks/**/*.py` 前：读 `.agent/rules/api-patterns.md`（含翻译）。
3. 编辑 `tasks/**/view/**/*.py`：加读 `api-logging.md`。
4. 进入某任务目录：读 `.agent/rules/tasks/<任务名>.md` + 该任务 README。
5. 写新接口：参考 `api-patterns-ref.md`。
6. 冲突裁决：task 规则 > api-patterns/api-logging/data-script > yy-global > karpathy。
