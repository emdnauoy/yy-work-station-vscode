# tasks — 隔离子任务目录

每个需求一个独立文件夹，互不影响。配套规则在 `.agent/rules/tasks/`。

**默认栈**：Python 3.8 · FastAPI · Pydantic v1 · SQLAlchemy 2.0 (async) · MySQL 8.0（详见 `.agent/rules/yy-global.md`）。

## 新建任务

1. **复制模板**：

   ```powershell
   Copy-Item -Recurse tasks\_example tasks\<任务名>
   ```

   任务名用 `snake_case`（与 Python 包命名一致），如 `fix_login`、`export_csv`。**禁止**短横线（`fix-login`）。

2. **填写任务说明**：编辑 `tasks/<任务名>/README.md`，写背景、范围、验收标准、主仓参考链接。

3. **复制并改名规则**：

   ```powershell
   Copy-Item .agent\rules\tasks\_example.md .agent\rules\tasks\<任务名>.md
   ```

   在新 `.md` 中将 `_example` 全局替换为 `<任务名>`，确认 frontmatter 的 `globs` 为 `tasks/<任务名>/**`。

4. **开始开发**：在 `tasks/<任务名>/` 下改代码；规则按 globs 自动附加。

## 目录布局

```
tasks/
├── README.md                            # 本说明
├── _example/                            # 模板：新任务的起点
│   ├── README.md                        # 任务说明 + 复制后必做清单
│   ├── auth.py / db.py / translate.py   # 主仓依赖的本地 stub
│   ├── models.py / schemas.py           # ORM + Pydantic
│   ├── service.py                       # 业务层（不 commit）
│   ├── urls.py                          # 路由集中绑定
│   ├── view/example.py                  # 接口实现
│   └── example.sql                      # 建表 DDL
└── <你的任务名>/                        # 复制 _example 后改名
    ├── README.md
    └── ...
```

## 命名示例

| 正确 | 错误 |
|------|------|
| `tasks/fix_login/` | `tasks/fix-login/` |
| `.agent/rules/tasks/fix_login.md` | `fix-login.md` |

## 约束

- **禁止**在一个任务里修改另一个 `tasks/*` 目录。
- 主仓信息写在任务 `README.md`，**禁止**在本仓虚构主项目路径。
- `yy-global` / `karpathy-guidelines` 始终生效；`api-patterns` / `api-i18n` / `api-logging` 按需读；任务规则按 globs 附加。
