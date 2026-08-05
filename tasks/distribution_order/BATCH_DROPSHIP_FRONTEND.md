# 一件代发批量 — 前端接口与规则说明

> 给前端对接用。统一返回：`{ code, msg, data }`；成功 `code=200`，业务失败 `code=40000`。  
> 鉴权：与其它分销接口相同（Bearer Token）。

---

## 一、注意事项（必读）

### 1. 入口与流程边界

| 注意点 | 说明 |
|--------|------|
| 只用新弹框 | 批量建单**禁止**走 `draft/save` → `quote/submit` |
| 不能存草稿 | `batch/submit` 成功后直接进 **订单审核 `status=40`** |
| 两步提交 | 必须先 `parse` 再 `submit`；已废弃 `batch/create` |
| 客户范围 | 仅一件代发客户（下拉用 `dropship_customers`，勿用普通客户搜索） |
| SKU 校验 | 须商品库已启用；前端无需、也不应调框架报价相关接口 |

### 2. Excel / 解析

| 注意点 | 说明 |
|--------|------|
| 列名勿改 | 表头与模板完全一致，改列名会解析失败 |
| 文本列 | 前 9 列（客户编码～邮编）已预设文本格式，勿改成数字 |
| 客户编码 | 每行都要填，且必须等于弹框所选客户 |
| 同 PO 聚合 | 同一「客户侧订单号」多行 → **1 张订单**（多 SKU） |
| 同 PO 一致性 | 同 PO 下：收件人姓名、联系方式、国家/省州/城市/详细地址/邮编 **必须完全一致** |
| 国家 | 收件国家须与客户国家一致，且不能为空 |
| 金额数量 | 单价 > 0；数量正整数；运费 ≥ 0 |
| parse 不落库 | 解析失败整包报错；成功也不写库 |

### 3. 提交前前端补齐

| 注意点 | 说明 |
|--------|------|
| 扁平明细 | `order_details` 一行一条，按 Excel 行序；同 PO 多 SKU 为多条 |
| 地址在行内 | 收件人/地址字段在每条 `order_details` 里，不要另传 |
| 红线价 / 库存 | parse 返回的 `guide_price` / `red_line_price` / `stock_*` 为 `null`，**前端匹配后回填再 submit** |
| 为何必填 | 价偏标签、后续下发库存校验依赖这些快照 |
| 公共字段 | `sales_user_id`、`shop_id` 必填；`vat_rate` / `is_tax_free` 等税率相关字段需前端按业务带上 |
| 失败整批回滚 | submit 任一单失败，本批不会产生半截订单 |

### 4. 运费（与普通单相反）

- Excel **每行**填运费 → 写入明细行 `freight_with_vat`
- **主单运费 = 同行运费之和**
- 普通单是「主单运费分摊到行」，批量单不要按普通单逻辑展示/编辑

### 5. 批量审核

| 注意点 | 说明 |
|--------|------|
| 仅通过 | `batch/approve` **只做通过**，无 `action` 字段 |
| 可审范围 | 仅 `create_source=1` 且 `status=40`；勾了普通单会进 `failed` |
| 驳回 | **不要**调 `batch/approve`；走单条 `approval/order/reject/`，**每单填 remark** |
| 部分成功 | `code` 仍可能是 `200`，必须以 `success` / `failed` 分条展示 |

### 6. 批量下发

| 注意点 | 说明 |
|--------|------|
| 不限来源 | 不要求 `create_source=1`，待下发池都可勾 |
| skipped | 库存不足进 `skipped`（不是 failed），提示补库存后再发 |
| 分条展示 | 同时看 `success` / `skipped` / `failed` |

### 7. 列表与普通单差异

| 注意点 | 说明 |
|--------|------|
| 筛批次 | `batch_id` 精确匹配；提交成功后建议跳列表并带该筛选 |
| 新字段 | 行上有 `batch_id`、`customer_po_no`、`create_source`、`cooperation_method`（及对应 `*_str`） |
| 批量审核按钮 | 勾选全部为 `create_source=1` 且订单审核中才启用 |
| 普通建单 | `draft/save` 若要带合作方式，前端自己传 `cooperation_method`，后端不从客户自动补 |

---

## 二、规则与枚举

| 规则 | 说明 |
|------|------|
| 适用客户 | `cooperation_method = 2`（一件代发） |
| 聚合 | 同一客户侧订单号 → 1 张订单 |
| Batch ID | 后端生成：`BatB2B{YYYYMMDD}{四位自增}` |
| 批量审核 | 仅通过；仅批量创建单 |
| 批量下发 | 库存不足跳过，其余照常 |

| 字段 | 值 | 含义 |
|------|----|------|
| `cooperation_method` | 1 | 批发 |
| `cooperation_method` | 2 | 一件代发 |
| `create_source` | 0 | 普通单 |
| `create_source` | 1 | 一件代发批量创建 |

---

## 三、推荐前端流程

### 1）批量创建

```
点击「批量创建」
  → 弹框
  → GET dropship_customers 选客户
  → GET batch/template 下载模板（可选）
  → 用户填 Excel 后上传
  → POST batch/parse（multipart：客户 + 文件）
  → 前端按返回 SKU 匹配红线价 / 指导价 / 库存，填入各行
  → 填公共信息（销售员、出库店铺、订单审核直线上级、税率等）
  → POST batch/submit（JSON：公共字段 + 补齐后的 order_details）
  → 成功展示 batch_id / 订单数，跳列表并带 batch_id 筛选
```

### 2）批量审核

```
列表筛 batch_id（或 status=40）
  → 勾选 create_source=1 的单
  → 批量通过：POST batch/approve
  → 驳回：单条 approval/order/reject（每单填 remark）
  → 按条展示 success / failed
```

### 3）批量下发

```
列表筛 status=60（待下发）
  → 勾选
  → POST batch/dispatch
  → 展示 success / skipped（库存不足）/ failed
```

---

## 四、接口明细

### 4.1 一件代发客户下拉

`GET /distribution_order/batch/dropship_customers/`

| Query | 类型 | 说明 |
|-------|------|------|
| `keyword` | string | 客户编码/简称模糊搜 |
| `page` | int | 默认 1 |
| `page_size` | int | 默认 50 |

```json
{
  "t_data": [
    {
      "_id": 123,
      "customer_code": "TH-xxx",
      "customer_short_name": "7-11",
      "customer_country": "TH",
      "settlement_currency": "THB",
      "current_contract_id": 456
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

---

### 4.2 下载批量导入模板

`GET /distribution_order/batch/template/`

- 响应：Excel 文件流（按 `Content-Disposition` 处理文件名）
- 空表头，无历史行

**表头（固定）：**

| 列名 |
|------|
| 客户编码 |
| 客户侧订单号 |
| 收件人姓名 |
| 收件人联系方式 |
| 收件人地址-国家 |
| 收件人地址-省州 |
| 收件人地址-城市 |
| 收件人地址-详细地址 |
| 收件人地址-邮编 |
| SKU编码 |
| 含增值税单价 |
| 销售数量 |
| 含增值税运费收入 |

---

### 4.3 批量上传解析（不落库）

`POST /distribution_order/batch/parse/`  
`Content-Type: multipart/form-data`

| Form 字段 | 必填 | 说明 |
|-----------|------|------|
| `offline_customer_id` | 是 | 一件代发客户 `_id` |
| `file` | 是 | `.xls` / `.xlsx` / `.xlsm` |

**成功 data：**

```json
{
  "offline_customer_id": 123,
  "customer_code": "TH-xxx",
  "imported_count": 2,
  "order_count": 1,
  "order_details": [
    {
      "customer_po_no": "PO-001",
      "name": "张三",
      "contact_info": "0812345678",
      "country": "TH",
      "province": "Bangkok",
      "city": "Bangkok",
      "address": "...",
      "post_code": "10110",
      "sku": "SKU-A",
      "price_with_vat": "100.00",
      "qty": 2,
      "freight_with_vat": "10.00",
      "guide_price": null,
      "red_line_price": null,
      "stock_on_hand": null,
      "stock_in_transit": null,
      "stock_planned": null
    }
  ]
}
```

---

### 4.4 批量提交审核

`POST /distribution_order/batch/submit/`  
`Content-Type: application/json`

| 字段 | 必填 | 说明 |
|------|------|------|
| `offline_customer_id` | 是 | 一件代发客户 `_id` |
| `sales_user_id` | 是 | 本单销售员 |
| `shop_id` | 是 | 出库店铺 id |
| `order_details` | 是 | parse 返回并补齐后的明细（结构同 4.3） |
| `is_tax_free` | 否 | 默认 `0` |
| `is_ewt` | 否 | 默认 `0` |
| `vat_rate` | 否 | VAT 税率（如 `0.07`） |
| `ewt_rate` | 否 | 预扣税比例 |
| `currency` | 否 | 缺省用客户结算币种 |
| `order_delivery_fee_payment` | 否 | 运费承担方；可空则后台尝试取合同 |
| `contract_id` | 否 | 缺省用客户当前生效合同 |
| `expected_ship_date` | 否 | `YYYY-MM-DD` |
| `ship_method` | 否 | 发货方式 |
| `remark` | 否 | 备注 |
| `order_lm_user_id` | 否 | 订单审核直线上级 |
| `chain_code` | 否 | 审批链 2/3；不传则按金额自动分档 |

**请求示例（节选）：**

```json
{
  "offline_customer_id": 123,
  "sales_user_id": 88,
  "shop_id": "shop-1",
  "order_lm_user_id": 99,
  "order_details": [
    {
      "customer_po_no": "PO-001",
      "name": "张三",
      "contact_info": "0812345678",
      "country": "TH",
      "province": "Bangkok",
      "city": "Bangkok",
      "address": "...",
      "post_code": "10110",
      "sku": "SKU-A",
      "price_with_vat": "100.00",
      "qty": 2,
      "freight_with_vat": "10.00",
      "guide_price": "120.00",
      "red_line_price": "90.00",
      "stock_on_hand": 50,
      "stock_in_transit": 0,
      "stock_planned": 0
    }
  ]
}
```

**成功 data：**

```json
{
  "batch_id": "BatB2B202608040001",
  "order_ids": [1001, 1002],
  "order_sns": ["B2BTH20260804...", "..."],
  "count": 2
}
```

---

### 4.5 批量审核通过

`POST /distribution_order/batch/approve/`

```json
{
  "order_ids": [1001, 1002],
  "remark": "可选审批意见"
}
```

**data：**

```json
{
  "success": [{ "order_id": 1001, "order_sn": "...", "to_status": 60 }],
  "failed": [{ "order_id": 1002, "msg": "仅批量创建订单支持批量审核" }],
  "success_count": 1,
  "failed_count": 1
}
```

驳回：`POST /distribution_order/approval/order/reject/`（单条，remark 必填）。

---

### 4.6 批量下发

`POST /distribution_order/batch/dispatch/`

```json
{ "order_ids": [1001, 1003, 1005] }
```

**data：**

```json
{
  "success": [{ "order_id": 1001, "order_sn": "...", "system_tracking_number": "..." }],
  "skipped": [{ "order_id": 1003, "order_sn": "...", "msg": "可用库存不足..." }],
  "failed": [{ "order_id": 1005, "msg": "出库店铺未选择..." }],
  "success_count": 1,
  "skipped_count": 1,
  "failed_count": 1
}
```

---

## 五、已有接口变更

### 5.1 列表 `GET /distribution_order/list/`

| 变更 | 说明 |
|------|------|
| Query | `batch_id` 精确匹配 |
| 出参 | `batch_id`、`customer_po_no`、`create_source` / `create_source_str`、`cooperation_method` / `cooperation_method_str` |

### 5.2 草稿保存 `POST /distribution_order/draft/save/`

| 变更 | 说明 |
|------|------|
| 入参 | 可传 `cooperation_method`（1/2），以前端为准 |

### 5.3 勿误用

| 接口 | 说明 |
|------|------|
| `draft/save` / `quote/submit` | 批量弹框不要走 |
| `order/submit` | 批量 `submit` 已自动提交审核，无需再调 |
| `batch/create` | 已废弃，改用 `parse` + `submit` |

---

## 六、常见错误

| msg 关键词 | 处理建议 |
|------------|----------|
| 仅一件代发客户… | 客户下拉须用 `dropship_customers` |
| 客户编码与所选客户不一致 | Excel 客户编码列写错 |
| 以下SKU不存在或未启用 | 换启用 SKU |
| 客户侧订单号…收件人/地址不一致 | 同 PO 多行姓名/电话/地址不统一 |
| 收件国家与客户国家不一致 | Excel 国家与所选客户不符 |
| 收件人姓名不能为空 | 姓名列未填 |
| 请选择本单销售员 / 出库店铺 | 公共信息未填 |
| 仅批量创建订单支持批量审核 | 勾选了普通单或非批量单 |

---

## 七、联调检查清单

- [ ] 下拉只出现一件代发客户  
- [ ] 模板下载 → 填表 → parse 拿到按序 `order_details`  
- [ ] 回填红线价/库存 → submit 成功拿 `batch_id`，状态为订单审核  
- [ ] 列表用 `batch_id` 能筛出本批  
- [ ] 批量通过分条展示；驳回走单条并填 remark  
- [ ] 批量下发时库存不足进 `skipped`  
- [ ] 普通 `draft/save` 可传 `cooperation_method`  
