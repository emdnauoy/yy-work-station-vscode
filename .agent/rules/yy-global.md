---
description: yy-work-station 工作区通用约定。卫星仓，小需求按 tasks 隔离。
alwaysApply: true
---

# yy-work-station 通用约定

## 仓库定位

- yy 主项目卫星工作区，小需求拆到 `tasks/<任务名>/`
- 任务间隔离，**禁**跨目录改代码（除非用户明确要求）
- 任务名 `snake_case`；目录名、规则文件名、`globs` 三者一致

## 技术栈

| 项 | 约定 |
|----|------|
| 语言 | **Python 3.8**（禁 3.9+ 语法/标准库） |
| Web | **FastAPI** + **Pydantic v1** |
| ORM | **SQLAlchemy 2.0**（async） |
| DB | **MySQL 8.0**，驱动 `aiomysql` / `asyncmy`（以主仓为准） |
| 运行 | `uvicorn`；启动方式以任务 README 为准 |

- **禁** Django、Flask
- 依赖版本以主仓为准；3.8 不兼容的包在 README 说明
- 连接串写 README，**禁**规则里硬编码密码

## 规则优先级

冲突时：task 规则 > api-patterns/api-logging/data-script > yy-global > karpathy

## 规则文件清单

| 规则 | 作用 | 加载范围 |
|------|------|----------|
| `yy-global.md` | 全仓通用约定 | 始终生效 |
| `authoring-rules.md` | 规则写法约定 | `.agent/rules/**/*.md` |
| `api-patterns.md` | API 核心约定（含翻译） | `tasks/**/*.py` |
| `api-logging.md` | 操作日志 | `tasks/**/view/**/*.py` |
| `api-patterns-ref.md` | 接口参考模板 | 按需引用 |
| `data-script.md` | 数据脚本约定 | `tasks/**/scripts/**/*.py` 等 |
| `karpathy-guidelines.md` | 行为准则（详细原文） | 按需引用 |
| `tasks/<任务名>.md` | 子任务规则 | `tasks/<任务名>/**` |

## 工作范围

- 默认只改当前任务目录 + 对应 `.agent/rules/tasks/<任务名>.md`
- **禁**假设主项目结构；主仓信息写任务 README
- **禁**改 `tasks/_example/`（除非用户要求更新模板）

## 开发流程

**先设计后编码**：新需求先定表设计 + 方案设计，用户确认后再写代码。

- 表设计：表、字段、类型、索引、外键、迁移方式 → README 或 `schema.sql` / `design.md`
- 方案设计：接口路径、入参出参、核心流程、依赖模块、边界条件 → README 或 `design.md`
- **禁**未确认设计前生成 `models.py` / `service.py` / `urls.py`
- 例外：修 bug、补注释、调格式等小改动可跳过

## 行为准则（Karpathy 精炼）

- **先想再写** — 明确假设与困惑，有歧义就问，不默默猜
- **最小实现** — 只做要求的，不加投机功能/抽象；200 行能写 50 行就重写
- **外科式改动** — 只碰必须碰的，不顺手重构；自己改动产生的孤儿要清理
- **目标驱动** — 把需求转成可验证目标，验证通过才算完

详细原文见 `.agent/rules/karpathy-guidelines.md`。

## 代码风格

- 单行 ≤ 200 字符（含缩进），能放一行就一行，超过再紧凑折行
- `import` 每行多个符号，**禁**一项一行；**禁**为「好看」提前拆行
- 文件头、折行示例见 `.agent/rules/api-patterns-ref.md`

## 沟通与提交

- 交流用简体中文
- **仅用户明确要求时**执行 git commit/push/创建 PR
- 变更最小范围，遵循上述行为准则

## 常用命令

```powershell
# 启动服务（以任务目录 README 为准）
uvicorn main:app --reload --port 8000

# 依赖安装（兼容 Python 3.8）
pip install -r requirements.txt

# lint / format（如有配置）
ruff check .
ruff format .
```

## 目录

| 路径 | 说明 |
|------|------|
| `tasks/<任务名>/` | 子任务代码与 `README.md` |
| `.agent/rules/` | 全局规则 + 子任务规则 |

## 新建子任务

1. 复制 `tasks/_example/` → `tasks/<任务名>/`，编辑 README
2. 复制 `.agent/rules/tasks/_example.md` → `.agent/rules/tasks/<任务名>.md`
3. 新规则文件中 `_example` 全部替换为 `<任务名>`，确认 `globs: tasks/<任务名>/**`
4. 任务目录下开发

接口约定：`.agent/rules/api-patterns.md`。
