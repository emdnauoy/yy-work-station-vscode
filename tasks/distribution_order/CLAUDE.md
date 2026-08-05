# 子任务：distribution_order（分销下单）

## 背景

分销订单全生命周期（审批、千易下发、拆单、回款）。产品需求见 `需求文档.md`；方案草案见 `design.md`（Q2/Q5/Q6/Q7/Q9 已确认，其余暂定沿用草案倾向）。

## 允许修改的范围

- **仅** `tasks/distribution_order/` 内文件
- **禁止** 修改其他 `tasks/*` 目录及无关全局配置

## 额外技术约定

- **views**：`from core.db.session import get_async_session, get_async_data_session`（**禁止**用任务内 `db.py` stub）；日志 `from loguru import logger`，异常 `logger.error(f"...{e}")` / `logger.exception(...)`
- **异常返回码**：除 `DistributionOrderError` 外，所有 `except Exception as e:` 兜底分支 **统一返回** `{"code": 40000, ...}`。
- **import 路径（禁相对路径）**：
  - **禁止** `from ..`、`from ...` 及 `from .模块` 引用本任务内代码
  - **统一**主仓绝对路径：`from apps.system.distribution_order.<模块> import ...`
  - 主仓公共：`core.db.session`、`loguru` 等照旧
  - 跨模块如线下客户：`from apps.system.offline_customer.models import ...`（**禁止** `from ..offline_customer`）
  - `urls.py` 绑 view：`from apps.system.distribution_order.views.<文件> import ...`（**禁止** `from .views`）

## 软删除（`is_delete`）

- 库表：`is_delete TINYINT`，`0=正常` `1=已删`（主表 + 报价/订单明细）；仅 service 写入
- **禁止** save body 传 `is_delete`；**禁止**靠「少传一行」隐式删行
- **删除**：批量 save 传 `_id` + `is_delete=1`；或专用 delete 接口 / `deleted_*_detail_ids`（兼容）；查询默认 `is_delete=0`

## 报价/订单明细（共用 line_service）

- 逻辑集中在 `distribution_order_line_service.py`（`kind=quote|order` 配置 ORM、可写字段、可编辑状态）
- 独立接口：`GET/POST .../quote_details/save/`、`.../order_details/save/`（**常用**）
- **save 行语义**：无 `_id` → 新增；有 `_id` 且 `is_delete=0` → 更新；有 `_id` 且 `is_delete≠0` → 软删（勿无 `_id` 删）
- `LineDetailBatchSaveIn` 仅 `order_id` + `lines`；`delete` 接口可选
- `draft/save` / `order/save`：显式传 `quote_details` / `order_details` 时 **全量替换**（软删旧行后全部新建，忽略行 `_id`）；未传明细字段则不改明细
- 独立 `quote_details/save`、`order_details/save` 仍按 `_id` 增改删
- `deleted_*_detail_ids` 仅独立 save 兼容；主单 save 全量替换时不再使用

## 明细 SKU 唯一（应用层）

- 报价/订单明细表**不设** `UNIQUE(order_id, sku)`（软删后可留多条历史同 SKU）
- **保存/新建行**时 service 校验：同单 `is_delete=0` 的 SKU 不可重复（含本次 body 多行互斥）

## 唯一键（库表）

| 表 | 唯一键 | 说明 |
|----|--------|------|
| 主表 | `uk_order_sn` | 单号全局唯一 |
| 快照 | `PRIMARY KEY(order_id)` | 1:1 主表 |
| 手工调整 | `uk_order_seq(order_id, seq)` | |
| 预付/尾款确认 | `uk_order_id(order_id)` | 一单一条确认记录 |
| 序列表/审批配置 | 见 `schema.sql` | |

## 补充约定

- **公共工具函数**：`_orm_out_dict`、`_load_order`、`_mark_delete`、Decimal 工具（`_as_decimal`/`_q2`）等放 `utils.py`，**禁**各 service 重复定义
- **拆单后缀**：`chr(ord("A") + child_count)` 只支持 26 单，超过需用 `AA/AB/...` 双字母
- **`from __future__ import annotations`**：本任务 service 文件统一使用，views 不用
- **列表查询**：条件构建 + 分页逻辑**必须**在 service 层，view 只调 `await list_xxx(session, params)`

## 参考

- 需求文档：`tasks/distribution_order/需求文档.md`
- 方案设计：`tasks/distribution_order/design.md`
- API 文档：`tasks/distribution_order/API_FRONTEND.md`
