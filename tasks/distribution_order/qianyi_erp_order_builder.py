# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/2
# @Author  : Zhu Yaming
# @File    : qianyi_erp_order_builder.py
# @Description : 分销订单 → 千易 CREATE_SALES_ORDER bizParam 字段映射
"""
from __future__ import annotations

import datetime
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence, Tuple

from apps.system.distribution_order.errors import QianyiErpError
from apps.system.distribution_order.models import (
    DistributionOrder, DistributionOrderItemDetail, DistributionOrderSnapshot,
)

PAYMENT_METHOD_ONLINE = "PAY_ONLINE"
CUSTOMER_PAY_FREIGHT = 2
_Q4 = Decimal("0.0001")


def _d4(val: Any) -> float:
    if val is None:
        return 0.0
    return float(Decimal(str(val)).quantize(_Q4, rounding=ROUND_HALF_UP))


def _format_pay_time(dt: Optional[datetime.datetime]) -> str:
    base = dt or datetime.datetime.now()
    if base.tzinfo is None:
        return base.strftime("%Y-%m-%d %H:%M:%S+08:00")
    return base.strftime("%Y-%m-%d %H:%M:%S%z")


def _resolve_pay_time(
    pay_time: Optional[datetime.datetime],
    order: DistributionOrder,
) -> datetime.datetime:
    """
    千易 createTime 为接收订单时刻；payTime 若取 order.create_time 会早于 createTime。
    下发默认用当前时间；若创建时间晚于付款时间，或付款时间在未来，也改用当前时间。
    """
    now = datetime.datetime.now()
    if pay_time is None:
        return now
    candidate = pay_time
    create_t = getattr(order, "create_time", None)
    if create_t and create_t > candidate:
        return now
    if candidate > now:
        return now
    return candidate


def _format_ship_guide_attachments(val: Any) -> str:
    """从发货指导附件 JSON 提取 URL/文件名，用于拼接到卖家备注。"""
    if val is None:
        return ""
    items: Any = val
    if isinstance(val, str):
        s = val.strip()
        if not s or s.lower() in ("null", "none", "[]", "{}"):
            return ""
        try:
            items = json.loads(s)
        except (ValueError, TypeError):
            return s
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, (list, tuple)):
        return str(items).strip()
    parts: List[str] = []
    for item in items:
        if isinstance(item, str):
            part = item.strip()
        elif isinstance(item, dict):
            part = (
                (item.get("url") or item.get("file_url") or item.get("name") or "")
            ).strip()
        else:
            part = str(item).strip()
        if part:
            parts.append(part)
    return "；".join(parts)


def _build_seller_remarks(order: DistributionOrder) -> str:
    parts: List[str] = []
    if order.expected_ship_date:
        parts.append("【期望出库日期】%s" % order.expected_ship_date.isoformat())
    if order.ship_remark:
        parts.append("【发货备注】%s" % order.ship_remark.strip())
    guide_text = _format_ship_guide_attachments(getattr(order, "ship_guide_attachments", None))
    if guide_text:
        parts.append("【发货指导文件】%s" % guide_text)
    return " ".join(parts).strip()


def _build_buyer(snapshot: Optional[DistributionOrderSnapshot], order: DistributionOrder) -> Dict[str, Any]:
    snap = snapshot
    buyer_id = (order.customer_code or "").strip()
    if not buyer_id:
        raise QianyiErpError(40000, "客户编码为空，无法下发千易")
    receiver = (getattr(snap, "name", None) or buyer_id).strip()
    if not receiver:
        raise QianyiErpError(40000, "收件人姓名为空，无法下发千易")
    country = (getattr(snap, "country", None) or order.customer_country or "").strip()
    if not country:
        raise QianyiErpError(40000, "收货国家为空，无法下发千易")
    address1 = (getattr(snap, "address", None) or "").strip()
    if not address1:
        raise QianyiErpError(40000, "收货地址为空，无法下发千易")
    buyer: Dict[str, Any] = {
        "buyerId": buyer_id,
        "receiverName": receiver,
        "country": country,
        "address1": address1,
    }
    phone = (getattr(snap, "contact_info", None) or "").strip()
    if phone:
        buyer["phone"] = phone
    province = (getattr(snap, "province", None) or "").strip()
    if province:
        buyer["province"] = province
    city = (getattr(snap, "city", None) or "").strip()
    if city:
        buyer["city"] = city
    district = (getattr(snap, "district", None) or "").strip()
    if district:
        buyer["district"] = district
    post_code = (getattr(snap, "post_code", None) or "").strip()
    if post_code:
        buyer["postCode"] = post_code
    return buyer


def _line_dispatch_goods_amount(
    line: DistributionOrderItemDetail,
    dispatch_qty: int,
) -> Decimal:
    """行货款：优先 amount_with_vat，部分下发按数量比例折算。"""
    line_qty = int(line.qty or 0)
    if line_qty <= 0 or dispatch_qty <= 0:
        return Decimal("0")
    stored = getattr(line, "amount_with_vat", None)
    if stored is not None:
        ratio = Decimal(dispatch_qty) / Decimal(line_qty)
        return (Decimal(str(stored)) * ratio).quantize(_Q4, rounding=ROUND_HALF_UP)
    unit_price = Decimal(str(line.price_with_vat or 0))
    return (unit_price * dispatch_qty).quantize(_Q4, rounding=ROUND_HALF_UP)


def _line_dispatch_freight(
    line: DistributionOrderItemDetail,
    qty: int,
    *,
    idx: int,
    line_count: int,
    order_freight: Decimal,
) -> Decimal:
    """行运费：优先用已分摊 freight_with_vat，按本次下发数量占行 qty 比例折算。"""
    line_qty = int(line.qty or 0)
    stored = getattr(line, "freight_with_vat", None)
    if stored is not None and line_qty > 0:
        ratio = Decimal(qty) / Decimal(line_qty)
        return (Decimal(str(stored)) * ratio).quantize(_Q4, rounding=ROUND_HALF_UP)
    freight_per = (
        order_freight / line_count
    ).quantize(_Q4, rounding=ROUND_HALF_UP) if line_count else Decimal("0")
    if idx < line_count - 1:
        return freight_per
    remainder = order_freight - freight_per * (line_count - 1)
    return max(Decimal("0"), remainder)


def _allocate_by_weights(total: Decimal, weights: Sequence[Decimal]) -> List[Decimal]:
    """按权重分摊 total（4 位小数），最后一项吃尾差，保证 parts 之和 == total。"""
    n = len(weights)
    if n == 0:
        return []
    if total <= 0:
        return [Decimal("0")] * n
    weight_sum = sum((w for w in weights), Decimal("0"))
    if weight_sum <= 0:
        per = (total / n).quantize(_Q4, rounding=ROUND_HALF_UP)
        parts = [per] * (n - 1)
        parts.append(max(Decimal("0"), total - per * (n - 1)))
        return parts
    parts: List[Decimal] = []
    allocated = Decimal("0")
    for i, w in enumerate(weights):
        if i < n - 1:
            part = (total * w / weight_sum).quantize(_Q4, rounding=ROUND_HALF_UP)
            parts.append(part)
            allocated += part
        else:
            parts.append(max(Decimal("0"), total - allocated))
    return parts


def _collect_dispatch_line_amounts(
    dispatchable: Sequence[DistributionOrderItemDetail],
    order_freight: Decimal,
) -> List[Dict[str, Any]]:
    """逐明细行计算本次下发数量、货款、行运费（合并前）。"""
    line_count = len(dispatchable)
    rows: List[Dict[str, Any]] = []
    for dispatch_idx, line in enumerate(dispatchable):
        qty = int(line.qty or 0) - int(line.dispatched_qty or 0)
        if qty <= 0:
            continue
        sku = (line.sku or "").strip()
        if not sku:
            raise QianyiErpError(40000, "存在 SKU 编码为空的明细行，无法下发千易")
        goods_amount = _line_dispatch_goods_amount(line, qty)
        line_freight = _line_dispatch_freight(
            line, qty, idx=dispatch_idx, line_count=line_count, order_freight=order_freight,
        )
        if line_freight < 0:
            line_freight = Decimal("0")
        rows.append({
            "sku": sku,
            "qty": qty,
            "goods_amount": goods_amount,
            "line_freight": line_freight,
        })
    if not rows:
        raise QianyiErpError(40000, "无可下发数量的订单明细")
    return rows


def _merge_dispatch_rows_by_sku(
    rows: Sequence[Dict[str, Any]],
) -> Tuple[List[str], Dict[str, Dict[str, Decimal]], Decimal]:
    """同 SKU 合并：数量与货款加总；运费池为合并前行运费之和（后续按货款占比重摊）。"""
    merged: Dict[str, Dict[str, Decimal]] = {}
    sku_order: List[str] = []
    freight_pool = Decimal("0")
    for row in rows:
        sku = row["sku"]
        freight_pool += row["line_freight"]
        if sku not in merged:
            merged[sku] = {"qty": Decimal("0"), "goods": Decimal("0")}
            sku_order.append(sku)
        merged[sku]["qty"] += Decimal(int(row["qty"]))
        merged[sku]["goods"] += row["goods_amount"]
    return sku_order, merged, freight_pool


def _finalize_merged_sku_payload(
    sku: str,
    qty: int,
    goods_amount: Decimal,
    line_freight: Decimal,
) -> Dict[str, Any]:
    """
    千易 sku 行：payAmount 为准（接口文档以 payAmount 优先于 paymentPrice）。
    paymentPrice = 合并后加权不含运单价；payAmount = 货款 + 行运费。
    """
    if qty <= 0:
        raise QianyiErpError(40000, "SKU %s 下发数量为 0" % (sku or "?"))
    goods_amount = goods_amount.quantize(_Q4, rounding=ROUND_HALF_UP)
    line_freight = line_freight.quantize(_Q4, rounding=ROUND_HALF_UP)
    if line_freight < 0:
        line_freight = Decimal("0")
    pay_amount = goods_amount + line_freight
    if pay_amount < 0:
        raise QianyiErpError(
            40000,
            "SKU %s 实付金额为负(%s)，由本平台 amount_with_vat+行运费 折算，"
            "请检查明细行金额/行运费；非千易侧重算" % (sku, pay_amount),
        )
    unit_price = (goods_amount / Decimal(qty)).quantize(_Q4, rounding=ROUND_HALF_UP)
    return {
        "sku": sku,
        "quantity": qty,
        "paymentPrice": _d4(unit_price),
        "payAmount": _d4(pay_amount),
        "shippingPrice": _d4(line_freight),
        "promotionDiscount": 0.0,
    }


def _build_sku_list(
    lines: Sequence[DistributionOrderItemDetail],
    freight: Decimal,
) -> Tuple[List[Dict[str, Any]], Decimal]:
    """
    组装千易 skuList，并返回本次实际分摊的运费合计（= sum(shippingPrice)）。

    同 SKU（忽略单价差异）合并为 1 行：
    - quantity：销售数量加总
    - 货款：各行 amount_with_vat（按本次下发比例）加总
    - 运费：先汇总合并前各行运费为 freight_pool，再按合并后货款占比重摊
    - paymentPrice：合并货款 / 合并数量（加权均价，不含运费）
    """
    active = [ln for ln in lines if int(getattr(ln, "is_delete", 0) or 0) == 0]
    if not active:
        raise QianyiErpError(40000, "订单明细为空，无法下发千易")
    dispatchable = [
        ln for ln in active
        if int(ln.qty or 0) - int(ln.dispatched_qty or 0) > 0
    ]
    if not dispatchable:
        raise QianyiErpError(40000, "无可下发数量的订单明细")

    line_rows = _collect_dispatch_line_amounts(dispatchable, freight)
    sku_order, merged, freight_pool = _merge_dispatch_rows_by_sku(line_rows)
    goods_weights = [merged[s]["goods"] for s in sku_order]
    freight_parts = _allocate_by_weights(freight_pool, goods_weights)

    sku_list: List[Dict[str, Any]] = []
    for sku, line_freight in zip(sku_order, freight_parts):
        qty = int(merged[sku]["qty"])
        payload = _finalize_merged_sku_payload(
            sku, qty, merged[sku]["goods"], line_freight,
        )
        sku_list.append(payload)

    if not sku_list:
        raise QianyiErpError(40000, "无可下发数量的订单明细")

    allocated_freight = sum(
        (Decimal(str(item["shippingPrice"])) for item in sku_list),
        Decimal("0"),
    )
    if freight_pool > 0 and abs(allocated_freight - freight_pool) > Decimal("0.0002"):
        raise QianyiErpError(
            40000,
            "运费分摊尾差异常：pool=%s allocated=%s" % (freight_pool, allocated_freight),
        )
    return sku_list, freight_pool


def build_create_sales_order_biz_param(
    order: DistributionOrder,
    snapshot: Optional[DistributionOrderSnapshot],
    lines: Sequence[DistributionOrderItemDetail],
    *,
    shop_name: str,
    pay_time: Optional[datetime.datetime] = None,
    payment_method: str = PAYMENT_METHOD_ONLINE,
    logistics_selected: Optional[str] = None,
    creator_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    将分销订单组装为千易 CREATE_SALES_ORDER 的 bizParam。
    shop_name：千易店铺名称（主表 shop_id 需在外部解析为店铺名后传入）。
    """
    shop = (shop_name or "").strip()
    if not shop:
        raise QianyiErpError(40000, "出库店铺名称为空，无法下发千易")
    order_sn = (order.order_sn or "").strip()
    if not order_sn:
        raise QianyiErpError(40000, "分销单号为空，无法下发千易")
    currency = (order.currency or "").strip()
    if not currency:
        raise QianyiErpError(40000, "币种为空，无法下发千易")

    freight = Decimal("0")
    customer_pays_freight = int(order.order_delivery_fee_payment or 0) == CUSTOMER_PAY_FREIGHT
    if not customer_pays_freight:
        freight = Decimal(str(order.freight_with_vat or 0))

    sku_list, freight_allocated = _build_sku_list(lines, freight)
    # 千易要求订单 freight 与各行 shippingPrice 之和一致，用实际分摊结果回填
    order_freight_for_qianyi = Decimal("0") if customer_pays_freight else freight_allocated

    biz: Dict[str, Any] = {
        "shop": shop,
        "onlineOrderNumber": order_sn,
        "trackingNumber": order_sn,
        "paymentMethod": payment_method,
        "currency": currency,
        "freight": _d4(order_freight_for_qianyi),
        "payTime": _format_pay_time(_resolve_pay_time(pay_time, order)),
        "buyer": _build_buyer(snapshot, order),
        "skuList": sku_list,
    }
    creator = (creator_name or "").strip()
    if creator:
        biz["creator"] = creator
    seller_remarks = _build_seller_remarks(order)
    if seller_remarks:
        biz["sellerRemarks"] = seller_remarks
    if logistics_selected:
        biz["logisticsSelected"] = logistics_selected.strip()
    elif order.ship_method:
        biz["logisticsSelected"] = order.ship_method.strip()
    return biz
