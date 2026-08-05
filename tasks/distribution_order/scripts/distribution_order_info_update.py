# -* coding: utf-8 -*-
"""
# @Time    : 2026/6/4
# @Author  : Zhu Yaming
# @File    : distribution_order_info_update.py
# @Description : 定时任务：千易状态同步、库存快照、标签重算（YYDB 游标，不用 ORM Session）
"""
import argparse
import json
import os
import sys

sys.path.append(os.getcwd().split('apps')[0])

import datetime
from decimal import Decimal
from loguru import logger
from conf.settings import settings
from apps.pyscript.helpers.db_helper import YYDB
from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper

# USER = 'yaoyao_auto_dev'
# PASSWORD = 'qwedcvfrt1234@'
# HOST = 'rr-uf69h9u7nqk74j65x8o.mysql.rds.aliyuncs.com'
# WHOST = 'rm-uf61x6v9wnzc1uo2f7o.mysql.rds.aliyuncs.com'
read_client = DfToMySqlHelper(host=settings.READ_ONLY_HOST, db="bi", user=settings.USER, password=settings.PASSWORD, port=settings.PORT)


# read_client = DfToMySqlHelper(host=HOST, db="bi", user=USER, password=PASSWORD, port=settings.PORT)

def _parse_date(val):
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    s = str(val).strip()[:10]
    if not s:
        return None
    return datetime.datetime.strptime(s, "%Y-%m-%d").date()


def is_ship_date_urgent(expected_ship_date, *, now=None):
    """
    期望出库日紧急判定：已过期望出库日，或距当日 24:00 不足 48h。
    """
    ship_date = _parse_date(expected_ship_date)
    if ship_date is None:
        return False
    now = now or datetime.datetime.now()
    if now.date() > ship_date:
        return True
    deadline = datetime.datetime.combine(ship_date, datetime.time(23, 59, 59))
    hours_left = (deadline - now).total_seconds() / 3600.0
    return hours_left < _URGENT_HOURS


def calc_expected_payment_date(
        actual_ship_date,
        settlement_method,
        settlement_days,
        effective_node,
):
    """按结算方式与合同快照计算预计回款日期。"""
    ship_date = _parse_date(actual_ship_date)
    if ship_date is None:
        return None
    method = int(settlement_method or 0)
    if method == 1:
        return ship_date
    if method != 2:
        return None
    days = int(settlement_days or 0)
    node = int(effective_node) if effective_node is not None else None
    if node == 0:
        days += 3
    elif node == 1:
        days += 5
    if days > 0:
        return ship_date + datetime.timedelta(days=days)
    return ship_date


# ---------------------------------------------------------------------------
# 标签位图 tags_bitmask（与 constants.py / distribution_order_tags.py 对齐）
# bit 含义见 schema.sql 注释；定时任务与 --tags-only 全量重算共用下列常量
# ---------------------------------------------------------------------------
TAG_PRICE_DEVIATION = 1  # 价偏：含增值税单价 < 红线价
TAG_LARGE_AMOUNT = 2  # 大额：含税订单总额 USD > 5000
TAG_SAMPLE = 4  # 样品：订单明细含协议/折扣样品行
TAG_OUT_OF_STOCK = 8  # 缺货：待发数量 > 在库库存（待下发及之后）
TAG_SPLIT = 16  # 拆单：存在子单
TAG_SPECIAL_OPS = 32  # 特殊作业：发货备注或发货指导附件非空
TAG_URGENT = 64  # 紧急：已过/临近期望出库日，且千易未发货或未同步
TAG_RECEIVE_DIFF = 128  # 实收差异：任一行 received_qty 已填且 ≠ qty
TAG_PAYMENT_OVERDUE = 256  # 回款超期：已过预计回款日且仍待回款
LARGE_AMOUNT_USD_THRESHOLD = Decimal("5000")
_URGENT_HOURS = 48
# 千易未发货状态（与 QyOrderStatus 枚举 value 一致）；None/空视为未同步，同样可打紧急
_QY_URGENT_STATUSES = ("WAIT_PAYMENT", "WAIT_AUDIT", "WAIT_SHIP")
STATUS_PENDING_DISPATCH = 60
STATUS_FULFILLING = 70
STATUS_PENDING_PAYMENT = 80
STATUS_VOIDED = 99
QY_ORDER_STATUS_SHIPPED = "SHIPPED"
# 标签重算涉及的表名
QUOTE_DETAIL_TABLE = "data_distribution_order_quote_detail"
ITEM_DETAIL_TABLE = "data_distribution_order_item_detail"
ORDER_TABLE = "data_distribution_order"

TAG_BITS = (
    TAG_PRICE_DEVIATION,
    TAG_LARGE_AMOUNT,
    TAG_SAMPLE,
    TAG_OUT_OF_STOCK,
    TAG_SPLIT,
    TAG_SPECIAL_OPS,
    TAG_URGENT,
    TAG_RECEIVE_DIFF,
    TAG_PAYMENT_OVERDUE,
)
TAG_LABELS = {
    TAG_PRICE_DEVIATION: "价偏",
    TAG_LARGE_AMOUNT: "大额",
    TAG_SAMPLE: "样品",
    TAG_OUT_OF_STOCK: "缺货",
    TAG_SPLIT: "拆单",
    TAG_SPECIAL_OPS: "特殊作业",
    TAG_URGENT: "紧急",
    TAG_RECEIVE_DIFF: "实收差异",
    TAG_PAYMENT_OVERDUE: "回款超期",
}


def patch_tag_bit(mask, bit, enabled):
    """保留其他标签位，仅增删指定 bit。"""
    current = int(mask or 0)
    bit = int(bit)
    if enabled:
        return current | bit
    return current & ~bit


def _mask_to_db(mask):
    """位图为 0 时落库 NULL，与 ORM 侧 refresh_order_tags 一致。"""
    value = int(mask or 0)
    return value if value else None


def decode_tag_bits(mask):
    """位图 -> 标签 bit 列表。"""
    value = int(mask or 0)
    return [bit for bit in TAG_BITS if value & int(bit)]


def tags_to_label_str(bits):
    """标签 bit 列表 -> 中文名，逗号分隔；空列表返回 '-'。"""
    if not bits:
        return "-"
    return ",".join(TAG_LABELS.get(int(b), str(b)) for b in bits)


def diff_tag_bitmask(old_mask, new_mask):
    """对比新旧位图，返回 (新增 bits, 移除 bits)。"""
    old_bits = set(decode_tag_bits(old_mask))
    new_bits = set(decode_tag_bits(new_mask))
    added = sorted(new_bits - old_bits)
    removed = sorted(old_bits - new_bits)
    return added, removed


def format_tag_bitmask(mask):
    """位图 ->「128|实收差异,64|紧急」便于日志检索。"""
    bits = decode_tag_bits(mask)
    if not bits:
        return "0"
    return ",".join("%s|%s" % (b, TAG_LABELS.get(b, b)) for b in bits)


def build_tag_refresh_change(order_id, order_sn, old_mask, new_mask):
    """组装单条标签变更记录。"""
    added, removed = diff_tag_bitmask(old_mask, new_mask)
    return {
        "order_id": int(order_id),
        "order_sn": (order_sn or "").strip() or None,
        "old_mask": int(old_mask or 0),
        "new_mask": int(new_mask or 0),
        "old_tags": decode_tag_bits(old_mask),
        "new_tags": decode_tag_bits(new_mask),
        "added": added,
        "removed": removed,
    }


def log_tag_refresh_changes(changes, *, dry_run=False):
    """逐单记录标签全量重算差异。"""
    if not changes:
        return
    prefix = "dry-run " if dry_run else ""
    for item in changes:
        oid = item["order_id"]
        sn = item.get("order_sn") or "-"
        logger.info(
            f"{prefix}标签变更 order_id={oid} order_sn={sn} | "
            f"{format_tag_bitmask(item['old_mask'])} -> {format_tag_bitmask(item['new_mask'])} | "
            f"移除:[{tags_to_label_str(item['removed'])}] 新增:[{tags_to_label_str(item['added'])}]"
        )
    added_total = sum(len(item["added"]) for item in changes)
    removed_total = sum(len(item["removed"]) for item in changes)
    logger.info(
        f"{prefix}标签差异汇总：变更 {len(changes)} 单，"
        f"新增标签 {added_total} 次，移除标签 {removed_total} 次"
    )


def _row_get(row, key, default=None):
    """游标 dict 行安全取值。"""
    if not row:
        return default
    return row.get(key, default)


def _norm_country(val):
    """国家/地区代码规范化：去空格并转大写，用于 (sku, country) 库存匹配。"""
    return (val or "").strip().upper()


def _decimal(val):
    """金额/数量转 Decimal，None 视为 0。"""
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def _attachments_empty(val):
    """JSON 附件列是否为空（含 MySQL 字符串 'null' / '[]'）。"""
    if val is None:
        return True
    if isinstance(val, (list, tuple)):
        return len(val) == 0
    if isinstance(val, dict):
        return len(val) == 0
    if isinstance(val, str):
        s = val.strip()
        if not s or s.lower() in ("null", "none", "[]", "{}"):
            return True
        try:
            return _attachments_empty(json.loads(s))
        except (ValueError, TypeError):
            return False
    return False


def _line_price_below_red(line):
    """单行是否价偏。"""
    price = _row_get(line, "price_with_vat")
    red = _row_get(line, "red_line_price")
    if price is None or red is None:
        return False
    return _decimal(price) < _decimal(red)


def _line_out_of_stock(line):
    """单行是否缺货；优先用下发时快照 dispatch_stock_on_hand。"""
    qty = int(_row_get(line, "qty") or 0)
    if qty <= 0:
        return False
    stock = _row_get(line, "dispatch_stock_on_hand")
    if stock is None:
        stock = _row_get(line, "stock_on_hand")
    if stock is None:
        return False
    return int(stock) < qty


def _has_sample_line(order_lines):
    """订单明细是否含样品行。"""
    for row in order_lines or []:
        if int(_row_get(row, "is_protocol_sample") or 0) == 1:
            return True
    return False


def _has_receive_diff(order_lines):
    """任一行实收数量已回填且与销售数量不一致。"""
    for row in order_lines or []:
        if _row_get(row, "received_qty") is None:
            continue
        if int(_row_get(row, "received_qty")) != int(_row_get(row, "qty") or 0):
            return True
    return False


def _order_amount_usd(order, exchange_rate_map=None):
    """主单含税金额折算 USD；缺汇率时返回 None（跳过大额标签）。"""
    amt = _row_get(order, "order_amount_with_vat")
    if amt is None:
        return None
    currency = (_row_get(order, "currency") or "USD").strip().upper() or "USD"
    if currency == "USD":
        return _decimal(amt)
    rate_map = exchange_rate_map or {}
    rate = rate_map.get(currency) or rate_map.get(currency.lower())
    if rate is None:
        return None
    try:
        rate_dec = Decimal(str(rate))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if rate_dec == 0:
        return None
    return _decimal(amt) / rate_dec


def _is_qy_status_urgent_eligible(order_status):
    """千易待审/待付/待发货，或未同步（None/空）时允许打紧急标。"""
    if order_status is None:
        return True
    status = str(order_status).strip()
    if not status:
        return True
    return status.upper() in _QY_URGENT_STATUSES


def compute_order_tags_bitmask(
        order,
        quote_lines,
        order_lines,
        *,
        has_child_orders=False,
        today=None,
        exchange_rate_map=None,
):
    """
    同步重算单条订单 tags_bitmask。

    规则与 apps.system.distribution_order.distribution_order_tags.compute_tags_bitmask
    保持一致；本脚本用 YYDB 游标 dict 行，供定时任务 / --tags-only 批量刷数。

    :param order: 主单 dict（status、order_status、金额、日期、附件等）
    :param quote_lines: 报价明细 dict 列表
    :param order_lines: 订单明细 dict 列表（含 received_qty、库存字段）
    :param has_child_orders: 是否存在子单（拆单标签）
    :param today: 计算回款超期的基准日，默认当天
    :param exchange_rate_map: currency -> rate，用于大额标签
    :return: 新位图；全 0 时返回 None
    """
    mask = 0
    today = today or datetime.date.today()
    status = int(_row_get(order, "status") or 0)
    order_status = _row_get(order, "order_status")

    # 价偏：报价 + 订单明细任一 SKU
    for line in list(quote_lines or []) + list(order_lines or []):
        if _line_price_below_red(line):
            mask |= TAG_PRICE_DEVIATION
            break

    # 大额
    amount_usd = _order_amount_usd(order, exchange_rate_map)
    if amount_usd is not None and amount_usd > LARGE_AMOUNT_USD_THRESHOLD:
        mask |= TAG_LARGE_AMOUNT

    # 样品
    if _has_sample_line(order_lines):
        mask |= TAG_SAMPLE

    # 缺货（待下发及之后、非作废）
    if status >= STATUS_PENDING_DISPATCH and status != STATUS_VOIDED:
        for line in order_lines or []:
            if _line_out_of_stock(line):
                mask |= TAG_OUT_OF_STOCK
                break

    # 拆单
    if has_child_orders:
        mask |= TAG_SPLIT

    # 特殊作业
    ship_remark = (_row_get(order, "ship_remark") or "").strip()
    if ship_remark or not _attachments_empty(_row_get(order, "ship_guide_attachments")):
        mask |= TAG_SPECIAL_OPS

    # 紧急：已过期望出库日，或距期望出库日不足 48h，且千易未发货或未同步
    expected_ship_date = _row_get(order, "expected_ship_date")
    if (
        expected_ship_date
        and _is_qy_status_urgent_eligible(order_status)
        and is_ship_date_urgent(expected_ship_date)
    ):
        mask |= TAG_URGENT

    # 实收差异（确认实收后 received_qty 落库）
    if _has_receive_diff(order_lines):
        mask |= TAG_RECEIVE_DIFF

    # 回款超期
    expected_payment_date = _parse_date(_row_get(order, "expected_payment_date"))
    if expected_payment_date and today > expected_payment_date and status == STATUS_PENDING_PAYMENT:
        mask |= TAG_PAYMENT_OVERDUE

    return _mask_to_db(mask)


def fetch_exchange_rate_map(client):
    """
    从 BI 只读库拉汇率，供大额标签折算 USD。

    :return: {currency: Decimal(rate)}，含 USD=1
    """
    rate_map = {"USD": Decimal("1")}
    try:
        df = client.get_df_by_sql(
            """
            SELECT currency, exchange_rate
            FROM bi.yy_exchange_rate
            """
        )
    except Exception as exc:
        logger.warning(f"汇率查询失败，大额标签可能不完整: {exc}")
        return rate_map
    if df is None or getattr(df, "empty", True):
        return rate_map
    for rec in df.to_dict("records"):
        cur = (rec.get("currency") or "").strip().upper()
        if not cur:
            continue
        try:
            rate_map[cur] = Decimal(str(rec.get("exchange_rate")))
        except (ArithmeticError, ValueError, TypeError):
            continue
    return rate_map


def build_stock_snapshot_map(stock_df):
    """(sku, country) -> {stock_on_hand, stock_in_transit, stock_planned}。"""
    stock_map = {}
    if stock_df is None or getattr(stock_df, "empty", True):
        return stock_map
    for rec in stock_df.to_dict("records"):
        sku = (rec.get("sku") or "").strip().upper()
        if not sku:
            continue
        country = _norm_country(rec.get("country"))
        stock_map[(sku, country)] = {
            "stock_on_hand": _stock_int(rec.get("stock_on_hand")),
            "stock_in_transit": _stock_int(rec.get("stock_in_transit")),
            "stock_planned": _stock_int(rec.get("stock_planned")),
        }
    return stock_map


def _stock_int(val):
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def build_stock_map(stock_df):
    """(sku, country) -> 在库库存。兼容缺货标签逻辑。"""
    snapshot = build_stock_snapshot_map(stock_df)
    return {
        key: vals["stock_on_hand"]
        for key, vals in snapshot.items()
        if vals.get("stock_on_hand") is not None
    }


def lookup_line_stock(sku, country, stock_snapshot_map):
    snap = stock_snapshot_map.get(
        ((sku or "").strip().upper(), _norm_country(country)),
    ) or {}
    return (
        snap.get("stock_on_hand"),
        snap.get("stock_in_transit"),
        snap.get("stock_planned"),
    )


def fetch_distribution_stock_df(client, min_total_stock=0):
    """拉取分销库位 SKU 库存快照（BI 只读库）。"""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    having_sql = ""
    if min_total_stock > 0:
        having_sql = """
              HAVING
                  COALESCE(stock_on_hand, 0) +
                  COALESCE(stock_planned, 0) +
                  COALESCE(stock_in_transit, 0) > 0
        """
    sql = """
          WITH
              base_products AS (
                  SELECT
                      a._id,
                      a.product_code,
                      a.nation,
                      loc.org_group,
                      ware.warehouse_type,
                      ware.store_code,
                      loc.storage_location
                  FROM bi.data_info_product_level a
                           LEFT JOIN internal_app.data_orggroup_store_mapping ware
                                     ON a.nation = ware.nation
                                         AND ware.invalid_ind = 0
                                         AND ware.enable = 1
                           LEFT JOIN internal_app.data_sys_warehouse_storage_location loc
                                     ON ware.store_code = loc.warehouse
                  WHERE
                      a.invalid_ind = 0
                    AND a.product_code <> ''
                    AND a.product_code IS NOT NULL
                    AND loc.org_group= "分销"
              ),
              stock_locations AS (
                  SELECT
                      product_code, warehouse, warehouse_location_code,
                      update_time, available_quantity
                  FROM bi.yy_stock_item_warehouse_location
                  WHERE warehouse_location_code = "分销" and available_quantity > 0
              ),
              shipping_items AS (
                  SELECT
                      sku, shippingQuantity, warehouse
                  FROM bi.data_history_storeitem
                  WHERE shippingQuantity > 0
              ),
              temu_items AS (
                  SELECT
                      sku_item_id,
                      SUM(warehouse_inventory_num) AS warehouse_inventory_num,
                      SUM(wait_receive_num) AS wait_receive_num
                  FROM bi.temu_sale_management_history
                  WHERE update_date='__TEMU_DATE__'
                    AND (warehouse_inventory_num > 0 OR wait_receive_num > 0)
                  GROUP BY sku_item_id
              ),
              operation_data AS (
                  SELECT
                      op.sku,
                      op.expectation_warehouse,
                      loc.storage_location,
                      org.warehouse_type,
                      SUM(CASE
                              WHEN ((op.transit_warehouse_date IS NULL AND org.warehouse_type in (1,6) AND org.geographic_location = 0) OR
                                    (op.actual_arrival_date IS NULL AND org.warehouse_type = 2 AND org.geographic_location = 1 ) OR
                                    (op.receipt_date IS NULL AND org.warehouse_type = 3 AND org.geographic_location = 1) OR
                                    (op.verify_date IS NULL AND org.warehouse_type = 5 AND org.geographic_location = 1) ) AND op.verify_date is NOT null
                                  THEN COALESCE(op.actual_quantity, op.receipt_quantity, op.pick_up_quantity_split, op.allocate_quantity)
                              WHEN org.warehouse_type != 4 THEN 0
                              ELSE 0
                          END) AS verify_plan_quantity,
                      SUM(CASE
                              WHEN ((op.transit_warehouse_date IS NULL AND org.warehouse_type  in (1,6) AND org.geographic_location = 0) OR
                                    (op.actual_arrival_date IS NULL AND org.warehouse_type = 2 AND org.geographic_location = 1 ) OR
                                    (op.receipt_date IS NULL AND org.warehouse_type = 3 AND org.geographic_location = 1) OR
                                    (op.verify_date IS NULL AND org.warehouse_type = 5 AND org.geographic_location = 1) ) AND op.verify_date is null
                                  THEN COALESCE(op.actual_quantity, op.receipt_quantity, op.pick_up_quantity_split, op.allocate_quantity)
                              WHEN org.warehouse_type != 4 THEN 0
                              ELSE 0
                          END) AS not_verify_plan_quantity,
                      SUM(CASE
                              WHEN (op.transit_warehouse_date IS NULL AND org.warehouse_type in (1,6) AND org.geographic_location = 0) OR
                                   (op.actual_arrival_date IS NULL AND org.warehouse_type = 2 AND org.geographic_location = 1) OR
                                   (op.receipt_date IS NULL AND org.warehouse_type = 3 AND org.geographic_location = 1) OR
                                   (op.verify_date IS NULL AND org.warehouse_type = 5 AND org.geographic_location = 1)
                                  THEN COALESCE(op.actual_quantity, op.receipt_quantity, op.pick_up_quantity_split, op.allocate_quantity)
                              WHEN org.warehouse_type != 4 THEN 0
                              ELSE 0
                          END) AS plan_quantity,
                      SUM(CASE
                              WHEN op.transit_warehouse_date IS NOT NULL
                                  AND (loc.is_business_group = 0 OR (loc.is_business_group = 1 AND loc.is_default = 1))
                                  AND org.warehouse_type in (1,6) AND org.geographic_location = 0
                                  AND op.add_store_date IS NULL
                                  THEN
                                  GREATEST(COALESCE(op.actual_quantity, op.receipt_quantity, op.pick_up_quantity_split, op.allocate_quantity),0)
                              WHEN op.transit_warehouse_date IS NOT NULL
                                  AND loc.is_business_group = 1 AND org.warehouse_type in (1,6) AND org.geographic_location = 0 AND loc.is_default != 1
                      THEN
                                  GREATEST(COALESCE(op.actual_quantity, op.receipt_quantity, op.pick_up_quantity_split, op.allocate_quantity) - IFNULL(adj.quantity, 0),0)
                              WHEN org.warehouse_type not in (1,6) THEN 0
                              ELSE 0
                          END) AS transit_quantity,
                      SUM(CASE
                              WHEN (op.receipt_date IS NOT NULL AND org.warehouse_type = 3 AND org.geographic_location = 1) OR
                                   (op.verify_date IS NOT NULL AND org.warehouse_type = 5 AND org.geographic_location = 1)
                                  THEN COALESCE(op.actual_quantity, op.receipt_quantity, op.pick_up_quantity_split, op.allocate_quantity)
                              ELSE 0
                          END) AS op_transfer_transit_quantity
                  FROM
                      internal_app.operation_pick_up_order_info op
                          LEFT JOIN internal_app.data_sys_warehouse_storage_location loc
                                    ON op.expectation_storage_location_id = loc._id
                          LEFT JOIN internal_app.data_orggroup_store_mapping org
                                    ON op.expectation_warehouse = org.store_code
                          LEFT JOIN (
                          SELECT
                              pick_up_number,
                              SUM(quantity) AS quantity
                          FROM internal_app.data_qianyi_adjustment_record
                          WHERE quantity > 0
                          GROUP BY pick_up_number
                      ) adj ON CONCAT('YY', op.purchase_number, '_', op._id) = adj.pick_up_number
                  WHERE
                      op.invalid_ind = 0
                    AND op.collaboration_status NOT IN (10, -2)
                    AND CONCAT(op.sku, op.expectation_warehouse, loc.storage_location) IS NOT NULL
                    AND loc.org_group = "分销"
                  GROUP BY
                      op.sku, op.expectation_warehouse, loc.storage_location, org.warehouse_type
              ),
              final_result AS (
                  SELECT
                      base.product_code sku,
                      base.nation country,
                      CASE
                          WHEN base.warehouse_type = 6 THEN SUM(IFNULL(loc.available_quantity, 0)- IFNULL(ware.shippingQuantity, 0))
                          ELSE SUM(IFNULL(loc.available_quantity, 0)) end AS stock_on_hand,
                      CASE
                          WHEN base.warehouse_type IN (1,2,3,5,6) AND base.storage_location != "Unavailable LOC" THEN
                              SUM(IFNULL(op.plan_quantity, 0))
                          ELSE NULL
                          END AS stock_planned,
                      CASE
                          WHEN base.storage_location = "Unavailable LOC" THEN NULL
                          WHEN base.warehouse_type in (1,6) THEN SUM(IFNULL(op.transit_quantity, 0))
                          WHEN base.store_code = "Temu广东平台发货仓" THEN SUM(IFNULL(temu.wait_receive_num, 0))
                          ELSE NULL
                          END AS stock_in_transit
                  FROM
                      base_products base
                          LEFT JOIN internal_app.data_code_mstr_static dcms
                                    ON base.warehouse_type = dcms.code_mstr
                                        AND dcms.code_type = 'Warehouse_type'
                          LEFT JOIN stock_locations loc
                                    ON base.product_code = loc.product_code
                                        AND base.store_code = loc.warehouse
                                        AND base.storage_location = loc.warehouse_location_code
                          LEFT JOIN shipping_items ware
                                    ON base.product_code = ware.sku
                                        AND base.store_code = ware.warehouse
                                        AND base.warehouse_type = 6
                                        AND base.storage_location = "货架"
                          LEFT JOIN temu_items temu
                                    ON base.product_code = temu.sku_item_id
                                        AND base.store_code = "Temu广东平台发货仓"
                                        AND base.storage_location = "SYS LOC"
                          LEFT JOIN operation_data op
                                    ON base.product_code = op.sku
                                        AND base.store_code = op.expectation_warehouse
                                        AND base.storage_location = op.storage_location
                  GROUP BY
                      base.product_code,
                      base.nation
              __HAVING__
              )
          SELECT * FROM final_result; \
          """.replace("__TEMU_DATE__", today_str).replace("__HAVING__", having_sql)
    return client.get_df_by_sql(sql)


def is_order_out_of_stock(lines, country, stock_map):
    """
    下发前：同 SKU 待发数量加总后与在库库存比较（库存不按行累加）。
    """
    country_key = _norm_country(country)
    need_by_sku = {}
    for line in lines:
        qty = int(line.get("qty") or 0) - int(line.get("dispatched_qty") or 0)
        if qty <= 0:
            continue
        sku = (line.get("sku") or "").strip().upper()
        need_by_sku[sku] = int(need_by_sku.get(sku) or 0) + qty
    for sku, need in need_by_sku.items():
        stock = stock_map.get((sku, country_key))
        if stock is None or int(stock) < need:
            return True
    return False


class UpdateDistributionOrderData(object):
    """
    分销订单定时同步：千易状态、预计回款、标签。

    标签两种模式：
    - 增量 patch：update_urgent_tags_from_qianyi / update_out_of_stock_tags（cron 默认）
    - 全量重算：refresh_tags_bitmask（--tags-only，含实收差异等全部 10 位）
    """

    def __init__(self):
        # 建议使用只读游标进行查询，写游标用于更新
        self.rdbconn, self.rcursor = YYDB.new_db_conn(host=settings.READ_ONLY_HOST)
        self.dbconn, self.cursor = YYDB.new_db_conn()

    def get_distribution_order_number(self):
        sql = """
              SELECT system_tracking_number
              FROM internal_app.data_distribution_order
              WHERE system_tracking_number is not null \
                 or system_tracking_number != "" \
              """
        self.rcursor.execute(sql)
        rows = self.rcursor.fetchall()

        return [row['system_tracking_number'] for row in rows]

    def get_distribution_order_info(self):
        sql = """
              SELECT o.system_tracking_number, o.settlement_method, os.settlement_days, os.effective_node
              FROM internal_app.data_distribution_order o
                       LEFT JOIN internal_app.data_distribution_order_snapshot os on o._id = os.order_id
              WHERE o.system_tracking_number is not null \
                 or o.system_tracking_number != "" \
              """

        df = read_client.get_df_by_sql(sql)

        return df

    def get_stock_info(self):
        return fetch_distribution_stock_df(read_client, min_total_stock=0)

    def get_order_status_from_qianyi(self, system_tracking_numbers):
        if not system_tracking_numbers:
            return []

        placeholders = ",".join(["%s"] * len(system_tracking_numbers))
        sql = """
            SELECT system_tracking_number, order_status, logistic_status, warehouse,
                   online_status, DATE(wms_ship_time) AS actual_ship_date
            FROM bi.yy_erp_qianyiapi_history
            WHERE system_tracking_number IN (%s)
            GROUP BY system_tracking_number
        """ % placeholders
        self.rcursor.execute(sql, tuple(system_tracking_numbers))
        result = self.rcursor.fetchall()

        dis_df = self.get_distribution_order_info()
        dis_info_map = {}
        if not dis_df.empty:
            for rec in dis_df.to_dict("records"):
                dis_info_map[rec["system_tracking_number"]] = rec

        for item in result:
            tracking_no = item["system_tracking_number"]
            info = dis_info_map.get(tracking_no) or {}
            ship_date = _parse_date(item.get("actual_ship_date"))
            item["actual_ship_date"] = ship_date
            item["expected_payment_date"] = calc_expected_payment_date(
                ship_date,
                info.get("settlement_method"),
                info.get("settlement_days"),
                info.get("effective_node"),
            )

        return result

    def update_urgent_tags_from_qianyi(self, status_data):
        """千易已出库(SHIPPED)时去掉紧急标签（增量 patch，非全量重算）。"""
        shipped_nos = [
            row["system_tracking_number"]
            for row in (status_data or [])
            if (row.get("order_status") or "").strip().upper() == QY_ORDER_STATUS_SHIPPED
               and row.get("system_tracking_number")
        ]
        if not shipped_nos:
            return 0

        placeholders = ",".join(["%s"] * len(shipped_nos))
        self.rcursor.execute(
            """
            SELECT _id, tags_bitmask
            FROM internal_app.data_distribution_order
            WHERE is_delete = 0 AND system_tracking_number IN (%s)
            """ % placeholders,
            tuple(shipped_nos),
        )
        rows = self.rcursor.fetchall()
        updates = []
        for row in rows:
            old_mask = int(row.get("tags_bitmask") or 0)
            if not (old_mask & TAG_URGENT):
                continue
            new_mask = patch_tag_bit(old_mask, TAG_URGENT, False)
            updates.append((_mask_to_db(new_mask), row["_id"]))
        if not updates:
            return 0

        self.cursor.executemany(
            """
            UPDATE internal_app.data_distribution_order
            SET tags_bitmask = %s
            WHERE _id = %s
            """,
            updates,
        )
        return len(updates)

    def update_out_of_stock_tags(self):
        """待下发订单：按最新分销在库库存重算缺货标签（增量 patch，非全量重算）。"""
        self.rcursor.execute(
            """
            SELECT _id, tags_bitmask, customer_country
            FROM internal_app.data_distribution_order
            WHERE is_delete = 0
              AND status = %s
            """,
            (STATUS_PENDING_DISPATCH,),
        )
        orders = self.rcursor.fetchall()
        if not orders:
            return 0

        order_ids = [row["_id"] for row in orders]
        placeholders = ",".join(["%s"] * len(order_ids))
        self.rcursor.execute(
            """
            SELECT order_id, sku, qty, dispatched_qty
            FROM internal_app.data_distribution_order_item_detail
            WHERE is_delete = 0 AND order_id IN (%s)
            """ % placeholders,
            tuple(order_ids),
        )
        lines_by_order = {}
        for line in self.rcursor.fetchall():
            lines_by_order.setdefault(line["order_id"], []).append(line)

        stock_map = build_stock_map(self.get_stock_info())
        updates = []
        for order in orders:
            lines = lines_by_order.get(order["_id"]) or []
            if not lines:
                continue
            out_of_stock = is_order_out_of_stock(
                lines, order.get("customer_country"), stock_map,
            )
            old_mask = int(order.get("tags_bitmask") or 0)
            new_mask = patch_tag_bit(old_mask, TAG_OUT_OF_STOCK, out_of_stock)
            if int(new_mask) != old_mask:
                updates.append((_mask_to_db(new_mask), order["_id"]))

        if not updates:
            return 0

        self.cursor.executemany(
            """
            UPDATE internal_app.data_distribution_order
            SET tags_bitmask = %s
            WHERE _id = %s
            """,
            updates,
        )
        return len(updates)

    # ----- 全量标签重算（对应 API 侧 refresh_order_tags，不走 ORM Session） -----

    def _fetch_orders_for_tags(self, order_ids=None):
        """拉主单标签计算所需字段；order_ids 为空则全表未删订单。"""
        if order_ids:
            placeholders = ",".join(["%s"] * len(order_ids))
            self.rcursor.execute(
                """
                SELECT _id, order_sn, status, order_status, order_amount_with_vat, currency,
                       ship_remark, ship_guide_attachments, expected_ship_date,
                       expected_payment_date, tags_bitmask
                FROM internal_app.%s
                WHERE is_delete = 0 AND _id IN (%s)
                """ % (ORDER_TABLE, placeholders),
                tuple(order_ids),
            )
        else:
            self.rcursor.execute(
                """
                SELECT _id, order_sn, status, order_status, order_amount_with_vat, currency,
                       ship_remark, ship_guide_attachments, expected_ship_date,
                       expected_payment_date, tags_bitmask
                FROM internal_app.%s
                WHERE is_delete = 0
                """ % ORDER_TABLE,
            )
        return self.rcursor.fetchall()

    def _fetch_lines_by_order(self, table_name, order_ids):
        """按 order_id 分组明细行；table_name 为报价/订单明细表。"""
        if not order_ids:
            return {}
        placeholders = ",".join(["%s"] * len(order_ids))
        self.rcursor.execute(
            """
            SELECT *
            FROM internal_app.%s
            WHERE is_delete = 0 AND order_id IN (%s)
            """ % (table_name, placeholders),
            tuple(order_ids),
        )
        grouped = {}
        for row in self.rcursor.fetchall():
            grouped.setdefault(row["order_id"], []).append(row)
        return grouped

    def _fetch_child_order_ids(self, order_ids):
        """存在子单的主单 _id 集合（拆单标签）。"""
        if not order_ids:
            return set()
        placeholders = ",".join(["%s"] * len(order_ids))
        self.rcursor.execute(
            """
            SELECT DISTINCT parent_order_id
            FROM internal_app.%s
            WHERE is_delete = 0 AND parent_order_id IN (%s)
            """ % (ORDER_TABLE, placeholders),
            tuple(order_ids),
        )
        return {int(row["parent_order_id"]) for row in self.rcursor.fetchall() if row.get("parent_order_id")}

    def refresh_tags_bitmask(self, order_ids=None, dry_run=False, exchange_rate_map=None):
        """
        全量重算 tags_bitmask 并写主库。

        与 update_urgent_tags / update_out_of_stock_tags 的增量 patch 不同，
        本方法按 compute_order_tags_bitmask 覆盖全部 9 个标签位，适用于：
        - 历史数据修复（如实收差异未打标）
        - 命令行 --tags-only / refresh_distribution_order_tags.py

        不在此方法内 commit，由调用方提交事务。

        :param order_ids: 指定主单 _id 列表；None 表示全表
        :param dry_run: True 时只统计将变更条数
        :param exchange_rate_map: 可选汇率；None 时从 BI 拉取
        :return: 实际更新（或将更新）的订单数；差异明细见 log（log_tag_refresh_changes）
        """
        orders = self._fetch_orders_for_tags(order_ids)
        if not orders:
            logger.info("没有需要刷新标签的订单")
            return 0

        ids = [row["_id"] for row in orders]
        # 批量预取关联数据，避免逐单查询
        quote_by_order = self._fetch_lines_by_order(QUOTE_DETAIL_TABLE, ids)
        item_by_order = self._fetch_lines_by_order(ITEM_DETAIL_TABLE, ids)
        child_parent_ids = self._fetch_child_order_ids(ids)
        if exchange_rate_map is None:
            exchange_rate_map = fetch_exchange_rate_map(read_client)

        updates = []
        changes = []
        for order in orders:
            oid = order["_id"]
            new_mask = compute_order_tags_bitmask(
                order,
                quote_by_order.get(oid) or [],
                item_by_order.get(oid) or [],
                has_child_orders=oid in child_parent_ids,
                exchange_rate_map=exchange_rate_map,
            )
            old_mask = _mask_to_db(order.get("tags_bitmask"))
            if old_mask != new_mask:
                updates.append((new_mask, oid))
                changes.append(build_tag_refresh_change(
                    oid, order.get("order_sn"), old_mask, new_mask,
                ))

        if dry_run:
            log_tag_refresh_changes(changes, dry_run=True)
            logger.info("dry-run: 将刷新 %s 条订单标签（共 %s 单）" % (len(updates), len(orders)))
            return len(updates)

        if not updates:
            logger.info("标签无变化，共检查 %s 单" % len(orders))
            return 0

        log_tag_refresh_changes(changes, dry_run=False)
        self.cursor.executemany(
            """
            UPDATE internal_app.%s
            SET tags_bitmask = %%s
            WHERE _id = %%s
            """ % ORDER_TABLE,
            updates,
        )
        logger.info("全量标签重算完成：更新 %s / %s 单" % (len(updates), len(orders)))
        return len(updates)

    def update_distribution_order(self):
        try:
            status_data = []
            tracking_numbers = self.get_distribution_order_number()
            if tracking_numbers:
                status_data = self.get_order_status_from_qianyi(tracking_numbers) or []
            else:
                logger.info("没有千易单号，跳过状态同步")

            if status_data:
                update_sql = """
                             UPDATE internal_app.data_distribution_order
                             SET order_status          = %s, \
                                 logistic_status       = %s, \
                                 warehouse             = %s, \
                                 online_status         = %s,
                                 actual_ship_date      = %s, \
                                 expected_payment_date = %s
                             WHERE system_tracking_number = %s \
                             """
                update_params = [
                    (
                        row["order_status"],
                        row["logistic_status"],
                        row["warehouse"],
                        row["online_status"],
                        row.get("actual_ship_date"),
                        row.get("expected_payment_date"),
                        row["system_tracking_number"],
                    )
                    for row in status_data
                ]
                self.cursor.executemany(update_sql, update_params)
                logger.info(f"成功更新 {len(update_params)} 条订单状态")
            elif tracking_numbers:
                logger.info("未查询到千易订单状态")

            urgent_n = self.update_urgent_tags_from_qianyi(status_data)
            oos_n = self.update_out_of_stock_tags()
            self.dbconn.commit()
            logger.info(f"标签更新：紧急去标 {urgent_n} 条，缺货重算 {oos_n} 条")
        except Exception as e:
            self.dbconn.rollback()
            logger.error(f"更新分销订单失败: {e}")

    def close(self):
        """安全关闭数据库连接"""
        if self.rcursor: self.rcursor.close()
        if self.rdbconn: self.rdbconn.close()
        if self.cursor: self.cursor.close()
        if self.dbconn: self.dbconn.close()


class UpdateDistributionOrderStockData(object):
    """下发前订单：刷新报价/订单明细库存快照。"""

    def __init__(self):
        self.rdbconn, self.rcursor = YYDB.new_db_conn(host=settings.READ_ONLY_HOST)
        self.dbconn, self.cursor = YYDB.new_db_conn()

    def get_pre_dispatch_orders(self):
        self.rcursor.execute(
            """
            SELECT _id, customer_country
            FROM internal_app.data_distribution_order
            WHERE is_delete = 0
              AND status < %s
            """,
            (STATUS_FULFILLING,),
        )
        return self.rcursor.fetchall()

    def _fetch_detail_lines(self, table_name, order_ids):
        if not order_ids:
            return []
        placeholders = ",".join(["%s"] * len(order_ids))
        self.rcursor.execute(
            """
            SELECT _id, order_id, sku, stock_on_hand, stock_in_transit, stock_planned
            FROM internal_app.%s
            WHERE is_delete = 0 AND order_id IN (%s)
            """ % (table_name, placeholders),
            tuple(order_ids),
        )
        return self.rcursor.fetchall()

    def _build_detail_stock_updates(self, lines, order_country_map, stock_snapshot_map):
        updates = []
        for line in lines:
            country = order_country_map.get(line["order_id"])
            on_hand, in_transit, planned = lookup_line_stock(
                line.get("sku"), country, stock_snapshot_map,
            )
            old = (
                _stock_int(line.get("stock_on_hand")),
                _stock_int(line.get("stock_in_transit")),
                _stock_int(line.get("stock_planned")),
            )
            new = (on_hand, in_transit, planned)
            if old == new:
                continue
            updates.append((on_hand, in_transit, planned, line["_id"]))
        return updates

    def _apply_detail_stock_updates(self, table_name, updates):
        if not updates:
            return 0
        self.cursor.executemany(
            """
            UPDATE internal_app.%s
            SET stock_on_hand = %%s, stock_in_transit = %%s, stock_planned = %%s
            WHERE _id = %%s
            """ % table_name,
            updates,
        )
        return len(updates)

    def update_line_stock(self):
        orders = self.get_pre_dispatch_orders()
        if not orders:
            logger.info("没有下发前订单，跳过库存快照更新")
            return 0, 0

        order_country_map = {row["_id"]: row.get("customer_country") for row in orders}
        order_ids = list(order_country_map.keys())
        stock_snapshot_map = build_stock_snapshot_map(
            fetch_distribution_stock_df(read_client, min_total_stock=0),
        )

        quote_lines = self._fetch_detail_lines(QUOTE_DETAIL_TABLE, order_ids)
        item_lines = self._fetch_detail_lines(ITEM_DETAIL_TABLE, order_ids)
        quote_updates = self._build_detail_stock_updates(
            quote_lines, order_country_map, stock_snapshot_map,
        )
        item_updates = self._build_detail_stock_updates(
            item_lines, order_country_map, stock_snapshot_map,
        )
        quote_n = self._apply_detail_stock_updates(QUOTE_DETAIL_TABLE, quote_updates)
        item_n = self._apply_detail_stock_updates(ITEM_DETAIL_TABLE, item_updates)
        return quote_n, item_n

    def update_distribution_order_stock(self):
        try:
            quote_n, item_n = self.update_line_stock()
            self.dbconn.commit()
            logger.info(
                f"库存快照更新：报价明细 {quote_n} 条，订单明细 {item_n} 条",
            )
        except Exception as e:
            self.dbconn.rollback()
            logger.error(f"更新分销订单库存快照失败: {e}")

    def close(self):
        if self.rcursor:
            self.rcursor.close()
        if self.rdbconn:
            self.rdbconn.close()
        if self.cursor:
            self.cursor.close()
        if self.dbconn:
            self.dbconn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stock-only",
        action="store_true",
        help="仅刷新下发前明细库存快照",
    )
    parser.add_argument(
        "--order-only",
        action="store_true",
        help="仅同步千易状态/标签/预计回款",
    )
    parser.add_argument(
        "--tags-only",
        action="store_true", default=1,
        help="仅全量重算 tags_bitmask",
    )
    parser.add_argument(
        "--order-id", type=int, action="append", dest="order_ids",
        help="指定订单 _id，可多次传入（配合 --tags-only）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅统计将更新的订单数，不写库",
    )
    args = parser.parse_args()

    if args.tags_only:
        # 独立入口：全量标签重算（含实收差异等），不跑千易同步
        updater = UpdateDistributionOrderData()
        try:
            n = updater.refresh_tags_bitmask(
                order_ids=args.order_ids, dry_run=args.dry_run,
            )
            if not args.dry_run:
                updater.dbconn.commit()
            logger.info("标签全量刷新结束，变更 %s 单" % n)
        except Exception as e:
            updater.dbconn.rollback()
            logger.error(f"标签全量刷新失败: {e}")
        finally:
            updater.close()
        sys.exit(0)

    run_stock = args.stock_only or (not args.order_only and not args.tags_only)
    run_order = args.order_only or (not args.stock_only and not args.tags_only)

    stock_updater = UpdateDistributionOrderStockData() if run_stock else None
    order_updater = UpdateDistributionOrderData() if run_order else None
    try:
        if stock_updater:
            stock_updater.update_distribution_order_stock()
        if order_updater:
            order_updater.update_distribution_order()
    finally:
        if stock_updater:
            stock_updater.close()
        if order_updater:
            order_updater.close()