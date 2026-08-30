---
description: API 接口参考模板。文件头、紧凑书写、import 路径、列表/增改接口、DB 三件套。
alwaysApply: false
---

# API 接口参考模板

按需引用。核心约定见 `.agent/rules/api-patterns.md`。

## 文件头

```python
# -* coding: utf-8 -*-
"""
# @Time    : YYYY/M/D
# @Author  : Zhu Yaming
# @File    : <文件名>.py
# @Description :
"""
```

## 紧凑书写

单行 ≤ 200 字符（含缩进），能放一行就一行，超过再紧凑折行。

- `import`：每行多个符号，**禁**一项一行
- dict/list/函数参数：少则单行，多则分行
- **禁**为对齐强行拆项独占一行

```python
# ✓
from apps.system.distribution_order.schemas import (
    AdjustmentIn, PaymentConfirmIn, PrepayConfirmIn, SplitIn,
)

# ✗ — 每项一行
from apps.system.distribution_order.schemas import (
    AdjustmentIn,
    PaymentConfirmIn,
    SplitIn,
)
```

## import 路径

- **禁**相对路径（`from ..x`、`from .x`）
- **用**主仓绝对路径：`from apps.system.<任务包名>.<模块> import ...`
- 主仓公共包（`core`、`loguru`）保持原 import

## 列表接口

- 参数：`page: int = 1`、`pageSize: int = 50`、`keyword: str = ""`；导出加 `is_download: int = 0`
- 多选筛选：`some_filter: str = "[]"` → `ast.literal_eval` 解析；失败返 `40000`；**禁**改 `List[int] = Query([])`
- 仅查询 → `bi_session`；需写库 → 加 `inter_session`
- 挂 `@translate_all_output`，`skip_fields` 至少 `data, pageSize, page, total, page_total`
- 枚举/状态字段：须附可读文案（`status_str`），映射在 service，**禁**只返魔法数字

```python
payload = {
    "tData": rows, "page": page, "pageSize": pageSize,
    "total": total_num, "page_total": page_total,
}
payload.update(table_base_data)  # 可选：表头、汇总
return {"code": 200, "msg": "获取数据成功", "data": payload}
```

## 增改接口

- 合一 vs 分开：逻辑基本一致 → 合一（按 `body.id` 分支）；差异大 → 拆 add/update；同模块禁混用
- 操作日志 → `.agent/rules/api-logging.md`

## 数据库三件套

`models.py`（ORM）+ `schemas.py`（Pydantic）+ `<表名>.sql`（DDL）

### 命名与类型

- 主键：列名 `_id`，`BigInteger`，`autoincrement=True`，**禁** `id`
- 选项/状态字段：`int`（`SmallInteger`），**禁**字符串枚举；含义写 `comment`
- 外键命名：`<关联表名>_id`，**禁**加 `ForeignKey` 约束
- 表名：`data_<模块>_<业务>`，schema `internal_app`
- 字符集 `utf8mb4`，排序 `utf8mb4_unicode_ci`，引擎 `InnoDB`

### 时间与审计

- 四件套：`create_time` / `update_time` / `create_by` / `update_by`
  - 时间列 `_time` 后缀，操作人 `_by` 后缀，**禁** `_at` / `created_*`
- 软删：`is_deleted TINYINT NOT NULL DEFAULT 0`（0=正常 1=已删），**禁** `SMALLINT`，**禁**混用 `delete_time`
- 软删 API：**禁** body 传 `is_deleted`；删须专用接口或 `deleted_*_ids`；查询默认 `is_deleted=0`
- 时间默认值：DB 端 `server_default=func.now()`，**禁** Python `default=datetime.now` + SQL `DEFAULT CURRENT_TIMESTAMP` 双写

### SQL

- MySQL 8.0；`TEXT` 禁 `DEFAULT ''`；长文本用 `VARCHAR(N) NOT NULL DEFAULT ''` 或 `TEXT NULL`
- 必须参数化（`:param` 或 ORM），**禁**字符串拼接

### Pydantic 读写模型

- `XxxIn`：参考 `_id` 别名陷阱
- `XxxOut`：`id: int = Field(..., alias="_id")`；Config 加 `orm_mode = True` + `allow_population_by_field_name = True`
