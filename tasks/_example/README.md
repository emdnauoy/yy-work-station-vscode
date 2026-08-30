# _example（模板任务 + 接口脚手架）

复制本目录并重命名为 **snake_case** 任务名（如 `fix_login`），删除本段模板说明，改为你的真实任务文档。

## 背景

（为何从 yy 主项目拆出此需求。）

## 技术栈

- Python **3.8**
- **FastAPI**（`uvicorn` 启动）
- **Pydantic v1**
- **SQLAlchemy 2.0**（async）+ 异步 MySQL 驱动（`aiomysql` / `asyncmy`，以主仓为准）
- **MySQL 8.0**（连接信息放环境变量，写在 README 即可，勿提交密码）

> 依赖版本以**主仓**为准，模板不预置 `requirements.txt`。

## 范围

- 本目录：`tasks/_example/`（复制后改为你的任务路径）
- 不改动：其他 `tasks/*` 目录

## 验收标准

- [ ] 条目 1
- [ ] 条目 2

## 主项目参考

- 仓库 / 分支：（如有）
- 相关模块：（如有）
- 链接：（Issue、文档、截图路径等）

---

## 目录结构（对齐主仓模块惯例）

```
tasks/_example/
├── README.md
├── __init__.py
├── auth.py              # 主仓 oauth2_scheme 的本地 stub
├── db.py                # 主仓 get_async_session / get_async_data_session 的本地 stub
├── translate.py         # 主仓 translate_all_output / get_translaiton_dict_from_request 的本地 stub
├── models.py            # ORM 模型（对齐主仓复数命名）
├── schemas.py           # Pydantic v1 读写模型
├── service.py           # 业务逻辑层（SQL / 校验 / 状态机；不 commit）
├── urls.py              # 路由注册（聚合本任务所有 router）
├── view/                # 接口实现（按业务拆 .py 文件）
│   ├── __init__.py
│   └── example.py
└── example.sql          # 建表 DDL（MySQL 8.0）
```

主仓模块还可能有 `common_func.py`、`<业务>_service.py`、`<业务>_engine.py` 等 —— **按需新建**，不预置。

## 分层约定

完整职责表见 `.agent/rules/api-patterns.md` 的"模块分层"小节。本仓三条最易出错的硬约束：

- view 层管事务（`try / commit / rollback`），**service 不 commit**
- 业务异常一律返回 `{"code": 40000+, ...}` dict，**不 raise HTTPException**
- `models.py` / `schemas.py` 只放字段形状，业务规则写在 `service.py`

## 复制任务后必做

1. **改 stub 的 import**：把 `auth.py` / `db.py` / `translate.py` 三个 stub 里的 import 路径改回主仓真实路径，或直接删掉这三个文件、把 `view/example.py` 顶部的 `from ..auth import ...` 等改成主仓真实路径。
2. **改业务名**：`models.py` / `schemas.py` / `service.py` / `view/example.py` / `example.sql` 里所有 `example` / `Example` 字样替换成你的业务名。
3. **挂载到主仓**：以主仓既有方式 include `urls.py` 里的 `router`。

接口约定见 `.agent/rules/api-patterns.md`。
