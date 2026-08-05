# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/1
# @Author  : Zhu Yaming
# @File    : distribution_order_tags.py
# @Description : 分销订单 tags_bitmask 重算、列表回显（design §2.2）
"""
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.system.distribution_order.constants import (
    TAG_BITS,
    TAG_LABELS,
    TAG_LARGE_AMOUNT,
    TAG_OUT_OF_STOCK,
    TAG_PAYMENT_OVERDUE,
    TAG_PRICE_DEVIATION,
    TAG_RECEIVE_DIFF,
    TAG_SAMPLE,
    TAG_SPECIAL_OPS,
    TAG_SPLIT,
    TAG_URGENT,
    LARGE_AMOUNT_USD_THRESHOLD,
)
from apps.system.distribution_order.distribution_order_line_service import (
    _load_alive_lines,
)
from apps.system.distribution_order.distribution_order_workflow_engine import (
    STATUS_PENDING_DISPATCH,
    STATUS_PENDING_PAYMENT,
    STATUS_VOIDED,
)
from apps.system.distribution_order.models import (
    DistributionOrder,
    DistributionOrderItemDetail,
    DistributionOrderQuoteDetail,
)

_URGENT_HOURS = 48
_QY_URGENT_STATUSES = ("WAIT_PAYMENT", "WAIT_AUDIT", "WAIT_SHIP")


def _is_qy_status_urgent_eligible(order_status):
    """千易待审/待付/待发货，或未同步（None/空）时允许打紧急标。"""
    if order_status is None:
        return True
    status = str(order_status).strip()
    if not status:
        return True
    return status.upper() in _QY_URGENT_STATUSES


def _ship_date_only(val):
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    return None


def is_ship_date_urgent(expected_ship_date, *, now=None):
    """
    期望出库日紧急判定：已过期望出库日，或距当日 24:00 不足 48h。
    """
    ship_date = _ship_date_only(expected_ship_date)
    if ship_date is None:
        return False
    now = now or datetime.datetime.now()
    if now.date() > ship_date:
        return True
    deadline = datetime.datetime.combine(ship_date, datetime.time(23, 59, 59))
    hours_left = (deadline - now).total_seconds() / 3600.0
    return hours_left < _URGENT_HOURS


def decode_tags(mask: Optional[int]) -> List[int]:
    if not mask:
        return []
    bits = []
    for bit in TAG_BITS:
        if int(mask) & int(bit):
            bits.append(int(bit))
    return bits


def tags_to_labels(bits: Sequence[int]) -> List[str]:
    return [TAG_LABELS[int(b)] for b in bits if int(b) in TAG_LABELS]


def attach_tags_display(data: Dict[str, Any]) -> None:
    """列表/详情行：tags_bitmask + tags + tags_str。"""
    bits = decode_tags(data.get("tags_bitmask"))
    data["tags"] = bits
    data["tags_str"] = tags_to_labels(bits)


def _d(val: Any) -> Decimal:
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def _attachments_empty(val: Any) -> bool:
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
            parsed = json.loads(s)
            return _attachments_empty(parsed)
        except (ValueError, TypeError):
            return False
    return False


def _parse_rate_value(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    if isinstance(val, dict):
        for key in ("exchange_rate", "rate", "value"):
            if key in val:
                parsed = _parse_rate_value(val[key])
                if parsed is not None:
                    return parsed
        return None
    try:
        return Decimal(str(val))
    except (ArithmeticError, ValueError, TypeError):
        return None


def lookup_exchange_rate(
    currency: Optional[str],
    exchange_rate_dict: Optional[Dict[Any, Any]],
) -> Optional[Decimal]:
    """查 yy_exchange_rate 汇率：本币金额 / rate = USD。"""
    cur = (currency or "USD").strip().upper() or "USD"
    if cur == "USD":
        return Decimal("1")
    if not exchange_rate_dict:
        return None
    for key in (cur, cur.lower()):
        if key not in exchange_rate_dict:
            continue
        rate = _parse_rate_value(exchange_rate_dict[key])
        if rate is not None and rate != 0:
            return rate
    return None


def order_amount_usd(
    order: DistributionOrder,
    exchange_rate_dict: Optional[Dict[Any, Any]] = None,
) -> Optional[Decimal]:
    amt = order.order_amount_with_vat
    if amt is None:
        return None
    rate = lookup_exchange_rate(order.currency, exchange_rate_dict)
    if rate is None:
        return None
    return _d(amt) / rate


def _line_price_below_red(line: Any) -> bool:
    price = getattr(line, "price_with_vat", None)
    red = getattr(line, "red_line_price", None)
    if price is None or red is None:
        return False
    return _d(price) < _d(red)


def _line_out_of_stock(line: Any) -> bool:
    qty = int(getattr(line, "qty", 0) or 0)
    if qty <= 0:
        return False
    stock = getattr(line, "dispatch_stock_on_hand", None)
    if stock is None:
        stock = getattr(line, "stock_on_hand", None)
    if stock is None:
        return False
    return int(stock) < qty


def _order_lines_out_of_stock(order_lines: Sequence[Any]) -> bool:
    """同 SKU 多行：数量加总，库存取快照（不累加）后比较。"""
    by_sku: Dict[str, Dict[str, Any]] = {}
    for line in order_lines or []:
        qty = int(getattr(line, "qty", 0) or 0)
        if qty <= 0:
            continue
        sku = (getattr(line, "sku", None) or "").strip() or "?"
        bucket = by_sku.get(sku)
        if bucket is None:
            bucket = {"need": 0, "stock": None}
            by_sku[sku] = bucket
        bucket["need"] = int(bucket["need"]) + qty
        stock = getattr(line, "dispatch_stock_on_hand", None)
        if stock is None:
            stock = getattr(line, "stock_on_hand", None)
        if stock is not None:
            stock_i = int(stock)
            if bucket["stock"] is None:
                bucket["stock"] = stock_i
            else:
                bucket["stock"] = min(int(bucket["stock"]), stock_i)
    for bucket in by_sku.values():
        available = bucket["stock"]
        if available is None:
            continue
        if int(available) < int(bucket["need"]):
            return True
    return False


def _has_sample_line(order_lines: Sequence[Any]) -> bool:
    for row in order_lines:
        if int(getattr(row, "is_protocol_sample", 0) or 0) == 1:
            return True
    return False


def _has_receive_diff(order_lines: Sequence[Any]) -> bool:
    for row in order_lines:
        if getattr(row, "received_qty", None) is None:
            continue
        if int(row.received_qty) != int(row.qty or 0):
            return True
    return False


def compute_tags_bitmask(
    order: DistributionOrder,
    quote_lines: Sequence[Any],
    order_lines: Sequence[Any],
    *,
    has_child_orders: bool = False,
    today: Optional[datetime.date] = None,
    exchange_rate_dict: Optional[Dict[Any, Any]] = None,
) -> Optional[int]:
    mask = 0
    today = today or datetime.date.today()
    status = int(order.status or 0)
    order_status = order.order_status

    for line in list(quote_lines) + list(order_lines):
        if _line_price_below_red(line):
            mask |= TAG_PRICE_DEVIATION
            break

    amount_usd = order_amount_usd(order, exchange_rate_dict)
    if amount_usd is not None and amount_usd > LARGE_AMOUNT_USD_THRESHOLD:
        mask |= TAG_LARGE_AMOUNT

    if _has_sample_line(order_lines):
        mask |= TAG_SAMPLE

    if status >= STATUS_PENDING_DISPATCH and status != STATUS_VOIDED:
        if _order_lines_out_of_stock(order_lines):
            mask |= TAG_OUT_OF_STOCK

    if has_child_orders:
        mask |= TAG_SPLIT

    ship_remark = (order.ship_remark or "").strip()
    if ship_remark or not _attachments_empty(order.ship_guide_attachments):
        mask |= TAG_SPECIAL_OPS

    if (
        order.expected_ship_date
        and _is_qy_status_urgent_eligible(order_status)
        and is_ship_date_urgent(order.expected_ship_date)
    ):
        mask |= TAG_URGENT

    if _has_receive_diff(order_lines):
        mask |= TAG_RECEIVE_DIFF

    if (
        order.expected_payment_date
        and today > order.expected_payment_date
        and status == STATUS_PENDING_PAYMENT
    ):
        mask |= TAG_PAYMENT_OVERDUE

    return mask if mask else None


async def refresh_order_tags(
    session: AsyncSession,
    order_id: int,
    *,
    order: Optional[DistributionOrder] = None,
    exchange_rate_dict: Optional[Dict[Any, Any]] = None,
) -> Optional[int]:
    """重算并写入主表 tags_bitmask，返回新位图。"""
    if order is None:
        row = (
            await session.execute(
                select(DistributionOrder).where(
                    DistributionOrder._id == int(order_id),
                    DistributionOrder.is_delete == 0,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        order = row

    quote_lines = await _load_alive_lines(
        session, int(order._id), DistributionOrderQuoteDetail,
    )
    order_lines = await _load_alive_lines(
        session, int(order._id), DistributionOrderItemDetail,
    )
    child_cnt = int(
        await session.scalar(
            select(func.count(DistributionOrder._id)).where(
                DistributionOrder.parent_order_id == int(order._id),
                DistributionOrder.is_delete == 0,
            )
        ) or 0
    )
    mask = compute_tags_bitmask(
        order,
        quote_lines,
        order_lines,
        has_child_orders=child_cnt > 0,
        exchange_rate_dict=exchange_rate_dict,
    )
    order.tags_bitmask = mask
    return mask


async def refresh_order_tags_batch(
    session: AsyncSession,
    order_ids: Optional[Sequence[int]] = None,
    *,
    exchange_rate_dict: Optional[Dict[Any, Any]] = None,
) -> int:
    """批量刷新；order_ids 为空则全表未删订单。"""
    if order_ids:
        ids = [int(x) for x in order_ids]
    else:
        ids = [
            int(r[0])
            for r in (
                await session.execute(
                    select(DistributionOrder._id).where(
                        DistributionOrder.is_delete == 0,
                    )
                )
            ).all()
        ]
    for oid in ids:
        await refresh_order_tags(
            session, oid, exchange_rate_dict=exchange_rate_dict,
        )
    return len(ids)
