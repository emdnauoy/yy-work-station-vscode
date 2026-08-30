---
description: "线下客户子任务：客户档案与合同审批流。含双 schema、状态码、软删差异、事务现状与已知偏差。"
alwaysApply: false
globs: tasks/offline_customer/**
---

# 子任务：offline_customer（线下客户）

线下客户档案、合同审批流、客户 SKU、Sell Out 销量 / 库存导入与 ERP 汇总同步。

## 允许修改的范围

**仅** `tasks/offline_customer/` 内文件。以下是本模块在全局约定之外的**额外**约束与**已知偏差**。

## 双 schema 与 session

| 库 | 表 | session |
|----|----|---------|
| `internal_app` | 客户 `data_sys_offline_customers`、合同 `data_sys_offline_contract` 及其子表（联系人 / 地址 / 附件 / 返利 / 状态日志 / 审批配置） | `get_async_session` → `inter_session` |
| `bi` | `data_offline_customer_sku`、`data_offline_sell_out_sales`、`data_offline_sell_out_stock` | `get_async_data_session` → `session` / `bi_session` |
| `erp_data` | `data_offline_sell_out_sku_detail`（同步目标） | `update_offline_sell_out.py` 内原生 pymysql |

Sell Out 导入写 `bi` + 操作日志写 `internal_app`，**两个 session 同时注入**。部分 view 声明了 `bi_session` 却没用（如 `get_sys_offline_customers_list`），**禁**顺手删签名，前端可能已在调。

## 状态码

| 字段 | 取值 |
|------|------|
| `OfflineCustomer.customer_status` | `10` 建联中 `20` 生效中 `30` 已过期 |
| `cooperation_method` | `1` 批发 `2` 一件代发 |
| SKU / Sell Out `status` | `0` 禁用 `1` 启用（作废即写 `status=0`） |

## 软删不统一（现状，禁统一化）

联系人 / 地址用 `is_delete`；随访记录用 `invalid_ind`；SKU 与 Sell Out 用 `status`；客户主表与合同主表**无软删字段**。客户 upsert 时未出现在请求里的旧联系人 / 地址是**物理 DELETE**（`delete_removed_objects`），独立删除接口同样物理删。**禁**为「对齐全局」把这些改成 `is_deleted`，会连带动前端契约与历史数据。

## 已知偏差（沿用现状，禁顺手重构）

本模块早于全局分层约定，以下与 `api-patterns.md` 不一致。按 `AGENTS.md` 硬约束「历史写法优先」**一律照现状写**，列在这里是为了让你别误判成 bug：

- **service 内 commit**：`service.upsert_offline_customer`、`contract_service.create/update/delete_offline_contract`、`contract_workflow_engine.apply_transition` 都自行 `commit`。改这些函数时注意 view 里可能还有二次 `commit`，别造成 double-commit 或漏 rollback
- **`raise HTTPException`**：`contract_service.update_offline_contract`（非草稿态）与 `sys_offline_contract_approve._do_transition` 会抛，由 view catch 后转 `ResultResponse`
- **返回值两套**：客户 / 合同用 `ResultResponse`（`core.response`）；SKU / Sell Out 直接返 dict。**同一文件内保持一致**，禁混用
- **错误码不止 40000**：现存 `50000`（客户）与 `404`（同步状态查询）。新增接口一律用 `40000`，**禁**扩散旧码
- 无自定义业务异常类，实际捕获 `ValueError` / `HTTPException` / `PermissionError` / `IntegrityError` / `ValidationError`

## 公共函数，禁重复定义

| 位置 | 内容 |
|------|------|
| `common_func.py` | `safe_parse_date` / `smart_parse_date`、`find_valid_sku`、`upload_df_to_oss`、`get_customer_info_df` / `get_store_info_df` / `get_product_info_df` / `get_user_name_dict`、`COUNTRY_CURRCNCY_DICT`、`disable_sales_or_stock_by_ids`、`get_table_key_cols` |
| `model_response.py` | 出参 Pydantic 与 `from_orm` enrichment、`CONTACT_FREQUENCY_MAP`、`COOPERATION_METHOD_STR` |
| `contract_service.py` | `serialize_contract_entity`、`convert_to_serializable`、`json_serializer`、`generate_contract_no` |
| `change_diff.py` | 模块自带 `deep_diff` / `deep_diff_create` / `parse_diff_log`，**禁**改用 `apps.common` 版；默认 `ignore_keys` 比全局多 `contract_no` |

`json_serializer` 目前在 `contract_service.py`、`sys_offline_sku_view.py`、`sys_offline_customers_view.py` 各有一份（已知重复），新代码统一引 `contract_service` 那份，**禁**再抄第四份。

入参 Pydantic 放 `schemas.py`，出参放 `model_response.py`，**禁**混写。

## 数据口径与坑

- **金额精度**：销售 `Numeric(15,4)`，合同 `Numeric(9,4)` / `Numeric(18,2)`；用 `Decimal` + `safe_decimal_convert`，**禁**用 float 中转
- **`customer_code` 自动生成** `{国家}{客户类型首字母}{4位序号}`（如 `THMTR0001`）；新增按 `(customer_short_name, customer_country)` 唯一
- **类型不一致（现状）**：`create_by` 在客户主表是 `BigInteger`、在 SKU / Sell Out 是 `String(64)`；`effective_node` ORM 是 `String(128)` 而 schema 是 `int`。读写时显式转换，**禁**假定同型

## 参考（按需读）

- **代码地图与场景导航：`tasks/offline_customer/README.md`**（文件职责、行数、改哪类需求先看哪几个文件）
- 合同状态机与审批链细则：`offline_customer_contract.md`（改合同文件时读）
- Sell Out 导入校验与含税汇率口径：`offline_customer_sellout.md`（改 Sell Out / SKU 文件时读）
- 迁移脚本：`tasks/offline_customer/migrations/`
