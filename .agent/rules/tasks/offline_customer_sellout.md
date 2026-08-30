---
description: "线下客户 Sell Out：销量/库存 Excel 导入校验、SKU 生效日取值、含税与汇率口径、ERP 同步。"
alwaysApply: false
globs: tasks/offline_customer/view/sys_offline_sell_out_*.py,tasks/offline_customer/view/update_offline_sell_out.py,tasks/offline_customer/view/sys_offline_sku_view.py
---

# offline_customer — Sell Out 导入与口径

本模块的通用约束（双 schema、状态码、软删、已知偏差）见 `offline_customer.md`，这里只写 Sell Out 与 SKU 特有的部分。

| 文件 | 行数 | 职责 |
|------|-----:|------|
| `view/sys_offline_sell_out_sales.py` | 843 | 销量列表 / 导入 / 作废 |
| `view/sys_offline_sell_out_stock.py` | 812 | 库存列表 / 导入 / 作废 |
| `view/sys_offline_sku_view.py` | 947 | 客户 SKU 维护与导入 |
| `view/update_offline_sell_out.py` | 627 | 汇总同步至 `erp_data`，原生 pymysql |

## 导入校验

销量 `upload_offline_sell_out_sales`、库存 `upload_offline_sell_out_stock`，模板走 `GET /offline_customer/download_excel_template/` 读 `templates/{template_name}.xlsx`。

- 单次 ≤ **5000** 行；失败行汇总成错误文件传 OSS 返回下载地址
- `customer_code` 必须已存在于 `OfflineCustomer`
- 销量唯一键 `(customer_code, store_code, sales_date, product_id)` 且 `status=1` 不可重复
- 「是否含税」`是→1` `否→0`；库存导入默认 `1`，且必填列不含币种
- 销量：`item_sold` 与 `sales` 不能同时为空；库存：`stock_num` 不能为空
- 作废必须走 `common_func.disable_sales_or_stock_by_ids`，它会同步清空 `erp_data.data_offline_sell_out_sku_detail` 对应字段，**禁**只改 `status`

## 数据口径

- **`product_id` 存字符串**，比较前统一 `str()`
- **SKU 按生效日取值**：用 `common_func.find_valid_sku` 取 `effective_date <= sales_date` 的最近一条；SKU 导入默认 `effective_date=1970-01-01`
- **含税**：`is_tax==0` 时 GMV 需乘 `country_tax_config.effective_tax`（tax+1）
- **汇率**：`sales / yy_exchange_rate.exchange_rate AS sales_usd`
- 金额用 `Decimal` + `safe_decimal_convert`，**禁**用 float 中转

## DfToMySqlHelper 客户端

`update_offline_sell_out.py` 与 `common_func.py` 已在模块级声明 `my_client`（`READ_ONLY_HOST`）、`write_client`（`HOST`）。命名不符 `data-script.md` 的 `read_client` / `write_client`，**沿用现状禁改名**（多处引用）；本目录**新增**脚本按 `data-script.md` 命名。
