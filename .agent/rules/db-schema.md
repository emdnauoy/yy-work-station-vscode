---
description: 建表三件套。约束新增表或字段的 ORM、Pydantic 和 DDL。
alwaysApply: false
globs: tasks/**/models.py,tasks/**/schemas.py,tasks/**/*.sql
---

# 数据库三件套

只约束新增表和字段；既有表沿用原命名和类型。建表同时维护 `models.py`（ORM）、`schemas.py`（Pydantic）和 `<表名>.sql`（DDL）。

## 命名与类型

- 主键列 `_id`，`BigInteger`，`autoincrement=True`；状态/选项用 `SmallInteger` 且在 `comment` 写明含义
- 外键列命名 `<关联表名>_id`，不加 `ForeignKey` 约束；表名为 `data_<模块>_<业务>`，schema 为 `internal_app`
- 使用 `utf8mb4`、`utf8mb4_unicode_ci` 与 `InnoDB`

## 时间、审计与 SQL

- 审计四件套：`create_time`、`update_time`、`create_by`、`update_by`；软删列：`is_deleted TINYINT NOT NULL DEFAULT 0`，查询默认过滤 `is_deleted=0`
- 删除不允许 body 直接传 `is_deleted`；使用专用删除接口或 `deleted_*_ids`
- 时间默认值放在 DB 端 `server_default=func.now()`，禁止与 Python `default=datetime.now` 双写
- MySQL 8.0：`TEXT` 不设 `DEFAULT ''`；所有 SQL 参数化，禁止字符串拼接

## Pydantic 输出模型

`XxxOut` 以 `id: int = Field(..., alias="_id")` 声明主键，并在 `Config` 配置 `orm_mode = True` 与 `allow_population_by_field_name = True`。
