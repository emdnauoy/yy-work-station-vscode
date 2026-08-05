# yy-work-station

从 yy 主项目拆出的小需求工作区。**默认栈：Python 3.8 + FastAPI + MySQL**。每个需求一个 **snake_case** 隔离目录（如 `tasks/fix_login/`），配套 Cursor 规则按路径自动生效。

## 核心约束（速查）

- **先设计后编码** — 新需求必须先定表设计 + 方案设计，用户确认后再写代码
- **任务隔离** — 禁止跨 `tasks/*` 目录改代码（除非用户明确要求）
- **规则优先级** — task .mdc > api-patterns > yy-global；冲突时 task 规则优先
- **技术栈锁定** — Python 3.8、Pydantic v1、SQLAlchemy 2.0 async、MySQL 8.0；禁止引入 Django/Flask
- **行为准则** — 遵循 Karpathy guidelines（`@.cursor/rules/karpathy-guidelines.mdc`）

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
| `.cursor/rules/yy-global.mdc` | 全仓通用约定（始终生效） |
| `.cursor/rules/api-patterns.mdc` | API 接口核心约定（编辑 `.py` 时加载） |
| `.cursor/rules/api-patterns-ref.mdc` | API 接口参考模板（按需引用） |
| `.cursor/rules/api-i18n.mdc` | 翻译与国际化约定（编辑 `.py` 时加载） |
| `.cursor/rules/api-logging.mdc` | 操作日志约定（编辑 `.py` 时加载） |
| `.cursor/rules/tasks/<任务名>.mdc` | 子任务规则（`globs` 绑定对应目录） |
| `.cursor/rules/karpathy-guidelines.mdc` | 行为准则（按需引用） |

## 新建子任务

见 [tasks/README.md](tasks/README.md)。

## 规则加载机制

| 规则 | 触发方式 |
|------|----------|
| `yy-global.mdc` | `alwaysApply: true`，始终生效 |
| `api-patterns.mdc` | `globs: tasks/**/*.py`，核心约定，编辑 Python 文件时自动加载 |
| `api-patterns-ref.mdc` | 无 globs，参考模板（文件头、列表/增改接口、DB 三件套），按需 `@` 引用 |
| `api-i18n.mdc` | `globs: tasks/**/*.py`，编辑 Python 文件时自动加载 |
| `api-logging.mdc` | `globs: tasks/**/view/**/*.py`，编辑 view 文件时自动加载 |
| `karpathy-guidelines.mdc` | `alwaysApply: false`，通过 `@karpathy-guidelines` 按需引用 |
| `tasks/<任务名>.mdc` | `globs: tasks/<任务名>/**`，编辑该目录文件时自动加载 |
