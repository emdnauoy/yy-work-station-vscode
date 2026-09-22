---
description: 本仓规则文件（.agent/rules/*.md）的写法约定。新增或修改规则、调整 globs、排查规则没生效时读。
alwaysApply: false
globs: .agent/rules/**/*.md
---

# 写规则的规则

## 禁 `@路径` 引用

规则里写 `@tasks/xxx/design.md`，Cursor 会在规则挂载时把该文件整个塞进上下文。指向文档一律用**纯路径 + 反引号**，让 agent 按需自己读。

```markdown
✓ 方案设计：`tasks/distribution_order/design.md`（62KB，按章节读）
✗ 方案设计：@tasks/distribution_order/design.md
```

规则之间互相引用同理，写文件名即可（`api-patterns-ref.md`），**禁**加 `@`。

## frontmatter

| 目标 | 写法 |
|------|------|
| 每轮常驻 | `alwaysApply: true` — **本仓只允许 `yy-global.md` 常驻，其余规则一律 `false`** |
| 命中文件时挂载 | `alwaysApply: false` + `globs` |
| 让 agent 按描述自取 | `alwaysApply: false` + `description`，不写 `globs` |

`globs` 用**不带引号、不带方括号的逗号分隔单行**（如 `tasks/code_analys/**/*.py,tasks/**/scripts/**/*.py`）。

修改 `globs` 后，必须以目标路径核对规则是否命中；多模式未命中时拆为更小的规则文件，禁假定前端会自动加载。脚本规则与 API 规则的范围不得重叠；独立刷数、回灌、导出、诊断脚本只适用 `data-script.md`。

## 体积

常驻规则每轮都付费，按需规则只在命中时付费。`AGENTS.md` 控制在 **2200 字以内**；单个 globs 规则尽量 ≤ **3000 字**，超了就按更细的路径拆分。

## 单一事实源

同一条约定只在一处详述，其余只写指针。**禁**在两个规则里各写一份——必然漂移。通用约束留在覆盖所有适用任务的公共规则，任务规则只写业务差异与例外；发现重复时，把详述留在加载范围最窄的文件里。

## 新增任务规则

复制 `.agent/rules/tasks/_example.md`，`globs` 改 `tasks/<任务名>/**`；任务规则只写**该任务额外的**约束，全局已有的**禁**重复抄。
