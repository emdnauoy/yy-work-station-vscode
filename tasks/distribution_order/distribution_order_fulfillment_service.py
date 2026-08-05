# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/27
# @Author  : Zhu Yaming
# @File    : distribution_order_fulfillment_service.py
# @Description : 预付/实收/回款/拆单/手工调整
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import datetime
from decimal import Decimal

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.system.distribution_order.distribution_order_line_service import (
    _load_alive_lines, _load_order, _q2 as _line_q2, apply_line_order_amounts,
    apply_order_line_amounts, build_split_order_item, copy_line_details_from_order,
    list_line_details, recalc_order_goods_amounts_from_lines,
    split_line_freight_by_qty, sync_order_freight_from_lines,
)
from apps.system.distribution_order.distribution_order_service import (
    clone_order_for_split, clone_snapshot_for_split, _load_snapshot,
    ensure_sql_null_order_json_from_parent,
    sanitize_order_json_columns,
)
from apps.system.distribution_order.constants import ADJUSTMENT_ALLOWED_STATUSES, STATUS_LABELS
from apps.system.distribution_order.distribution_order_workflow_engine import (
    ACTION_DISPATCH, ACTION_PAYMENT_CONFIRM, ACTION_PREPAY_CONFIRM, ACTION_RECEIVE_CONFIRM,
    OPERATOR_ADMIN, TRIGGER_MANUAL,
    STATUS_COMPLETED, STATUS_FULFILLING, STATUS_PENDING_DISPATCH,
    STATUS_PENDING_PAYMENT, STATUS_PREPAY,
    apply_transition,
)
from apps.system.distribution_order.errors import DistributionOrderError, QianyiErpError
from apps.system.distribution_order.models import (
    DistributionOrder, DistributionOrderAdjustment,
    DistributionOrderBalancePayment,
    DistributionOrderItemDetail, DistributionOrderPrepayment,
)
from apps.system.distribution_order.distribution_order_tags import refresh_order_tags
from apps.system.distribution_order.schemas import (
    AdjustmentBatchSaveIn, AdjustmentIn, AdjustmentLineIn,
    DispatchIn, PaymentConfirmIn, PaymentConfirmOut,
    PrepayConfirmIn, PrepayConfirmOut, ReceiveConfirmOut,
    SplitChildOrderOut, ReceiveConfirmIn, SplitIn,
)
from apps.system.distribution_order.qianyi_erp_client import QianyiErpClient
from apps.system.distribution_order.qianyi_erp_order_builder import build_create_sales_order_biz_param

def _as_decimal(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception as e:
        logger.exception(f"_as_decimal 转换失败: val={val!r}, err={e}")
        return None


def _q2(val: Optional[Decimal]) -> Optional[Decimal]:
    if val is None:
        return None
    return _line_q2(val)


def _sum_decimal(vals) -> Decimal:
    total = Decimal("0")
    for v in vals:
        dv = _as_decimal(v)
        if dv is not None:
            total += dv
    return total


def _alloc(total: Optional[Decimal], ratio: Decimal) -> Optional[Decimal]:
    if total is None:
        return None
    return _q2(_as_decimal(total) * ratio)


def _receive_transition_remark(lines: List[Any]) -> Optional[str]:
    """汇总行级实收差异原因，写入状态迁移日志 remark。"""
    parts: List[str] = []
    for ln in lines or []:
        text = (getattr(ln, "receive_diff_remark", None) or "").strip()
        if not text:
            continue
        sku = (getattr(ln, "sku", None) or "").strip()
        parts.append("%s:%s" % (sku or getattr(ln, "id", ""), text))
    return "; ".join(parts) if parts else None


async def confirm_prepay(
    session: AsyncSession,
    body: PrepayConfirmIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    order = await _load_order(session, body.order_id)
    if int(order.status) != STATUS_PREPAY:
        raise DistributionOrderError(40000, "当前状态不允许确认预付")

    row = (
        await session.execute(
            select(DistributionOrderPrepayment).where(
                DistributionOrderPrepayment.order_id == body.order_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DistributionOrderPrepayment(order_id=body.order_id)
        session.add(row)
        await session.flush()
    row.amount_due = _as_decimal(order.prepay_amount)
    row.amount_paid = _as_decimal(body.amount_paid)
    # row.payment_date = body.payment_date
    row.diff_remark = body.diff_remark
    row.attachments = body.attachments
    row.system_tracking_number = (
        (body.system_tracking_number or "").strip()
        or (order.system_tracking_number or "").strip()
        or None
    )
    row.create_by = operator_id

    await apply_transition(
        session,
        order_id=body.order_id,
        action=ACTION_PREPAY_CONFIRM,
        operator_id=operator_id,
        operator_role=OPERATOR_ADMIN,
        remark=body.diff_remark,
        trigger_type=TRIGGER_MANUAL,
    )
    return {"order_id": body.order_id, "to_status": STATUS_PENDING_DISPATCH}


async def confirm_receive(
    session: AsyncSession,
    body: ReceiveConfirmIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    order = await _load_order(session, body.order_id)
    if int(order.status) != STATUS_FULFILLING:
        raise DistributionOrderError(40000, "当前状态不允许确认实收")

    lines = body.lines or []
    if not lines:
        raise DistributionOrderError(40000, "明细行不能为空")

    existing = {
        int(r._id): r
        for r in await _load_alive_lines(session, body.order_id, DistributionOrderItemDetail)
    }
    sku_to_row = {
        (r.sku or "").strip(): r for r in existing.values() if (r.sku or "").strip()
    }

    touched = 0
    for ln in lines:
        lid = getattr(ln, "id", None)
        sku = (getattr(ln, "sku", None) or "").strip()
        row = None
        if lid is not None:
            try:
                row = existing.get(int(lid))
            except Exception as e:
                logger.exception(f"确认实收：明细行_id非法: {lid!r}, err={e}")
                row = None
        elif sku:
            row = sku_to_row.get(sku)
        if row is None:
            raise DistributionOrderError(40000, "订单明细行无效或不属于本单")
        if ln.received_qty is None:
            raise DistributionOrderError(40000, "实收数量不能为空")
        row.received_qty = int(ln.received_qty)
        if getattr(ln, "__fields_set__", None) and "receive_diff_remark" in ln.__fields_set__:
            row.receive_diff_remark = (ln.receive_diff_remark or "").strip() or None
        touched += 1

    order.update_by = operator_id

    await apply_transition(
        session,
        order_id=body.order_id,
        action=ACTION_RECEIVE_CONFIRM,
        operator_id=operator_id,
        operator_role=OPERATOR_ADMIN,
        remark=_receive_transition_remark(lines),
        trigger_type=TRIGGER_MANUAL,
    )
    return {"order_id": body.order_id, "updated_lines": touched, "to_status": STATUS_PENDING_PAYMENT}


async def confirm_payment(
    session: AsyncSession,
    body: PaymentConfirmIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    order = await _load_order(session, body.order_id)
    if int(order.status) != STATUS_PENDING_PAYMENT:
        raise DistributionOrderError(40000, "当前状态不允许确认回款")

    row = (
        await session.execute(
            select(DistributionOrderBalancePayment).where(
                DistributionOrderBalancePayment.order_id == body.order_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DistributionOrderBalancePayment(order_id=body.order_id)
        session.add(row)
        await session.flush()
    row.amount_due = _as_decimal(order.adjusted_balance_amount) or _as_decimal(order.balance_amount)
    row.amount_paid = _as_decimal(body.amount_paid)
    row.payment_date = body.payment_date
    row.diff_remark = body.diff_remark
    row.attachments = body.attachments
    row.system_tracking_number = (
        (body.system_tracking_number or "").strip()
        or (order.system_tracking_number or "").strip()
        or None
    )
    row.create_by = operator_id

    order.actual_payment_date = body.payment_date
    order.update_by = operator_id

    await apply_transition(
        session,
        order_id=body.order_id,
        action=ACTION_PAYMENT_CONFIRM,
        operator_id=operator_id,
        operator_role=OPERATOR_ADMIN,
        remark=body.diff_remark,
        trigger_type=TRIGGER_MANUAL,
    )
    return {"order_id": body.order_id, "to_status": STATUS_COMPLETED}


def _ship_qty(line: DistributionOrderItemDetail) -> int:
    return max(0, int(line.qty or 0) - int(line.dispatched_qty or 0))


def _assert_dispatch_stock(lines: List[DistributionOrderItemDetail]) -> None:
    """
    下发前校验可用库存。
    同 SKU 多行（不同价）时：待发数量加总，库存取该 SKU 快照（不累加），再比较。
    """
    # sku -> {need, stock}；stock 取同 SKU 仓位快照（不求和；不一致时取较小值）
    by_sku: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        need = _ship_qty(line)
        if need <= 0:
            continue
        sku = (line.sku or "").strip() or "?"
        bucket = by_sku.get(sku)
        if bucket is None:
            bucket = {"need": 0, "stock": None}
            by_sku[sku] = bucket
        bucket["need"] = int(bucket["need"]) + need
        available = line.stock_on_hand
        if available is not None:
            avail_i = int(available)
            if bucket["stock"] is None:
                bucket["stock"] = avail_i
            else:
                bucket["stock"] = min(int(bucket["stock"]), avail_i)

    for sku, bucket in by_sku.items():
        need = int(bucket["need"])
        available = bucket["stock"]
        if available is None or int(available) < need:
            raise DistributionOrderError(40000, "可用库存不足，无法下发订单（SKU: %s）" % sku)


async def _load_order_for_update(
    session: AsyncSession, order_id: int,
) -> DistributionOrder:
    """下发等写操作：行锁，避免双击并发各改一半。"""
    row = (
        await session.execute(
            select(DistributionOrder).where(
                DistributionOrder._id == order_id,
                DistributionOrder.is_delete == 0,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not row:
        raise DistributionOrderError(40400, "订单不存在")
    return row


async def dispatch_order_test(
    session: AsyncSession,
    body: DispatchIn,
    *,
    operator_id: Optional[int] = None,
    operator_name: Optional[str] = None,
    shop_dict: Optional[Dict[Any, Any]] = None,
) -> Dict[str, Any]:
    order = await _load_order_for_update(session, body.order_id)
    if int(order.status) != STATUS_PENDING_DISPATCH:
        raise DistributionOrderError(40000, "当前状态不允许下发，仅待下发可操作")
    if not order.shop_id:
        raise DistributionOrderError(40000, "出库店铺未选择，无法下发")

    lines = list(await _load_alive_lines(session, body.order_id, DistributionOrderItemDetail))
    shippable = [ln for ln in lines if _ship_qty(ln) > 0]
    if not shippable:
        raise DistributionOrderError(40000, "无可下发数量的订单明细")

    _assert_dispatch_stock(shippable)
    snapshot = await _load_snapshot(session, body.order_id)
    sid = int(order.shop_id)
    shop_name = str((shop_dict or {}).get(sid) or (shop_dict or {}).get(str(sid)) or "").strip()
    if not shop_name:
        raise DistributionOrderError(40000, "未找到出库店铺对应的千易店铺名")
    biz_param = build_create_sales_order_biz_param(
        order,
        snapshot,
        shippable,
        shop_name=shop_name,
        creator_name=operator_name,
    )
    logger.info(f"千易推送单信息: {biz_param}")

    # client = QianyiErpClient()
    # try:
    #     loop = asyncio.get_event_loop()
    #     qianyi_result = await loop.run_in_executor(
    #         None, client.create_sales_order, biz_param,
    #     )
    # except QianyiErpError as exc:
    #     raise DistributionOrderError(exc.code, exc.msg) from exc

    # tracking_no = (qianyi_result.get("order_number") or "").strip() or None
    # order.system_tracking_number = tracking_no
    order.update_by = operator_id
    for line in shippable:
        need = _ship_qty(line)
        line.dispatched_qty = int(line.dispatched_qty or 0) + need
        line.dispatch_stock_on_hand = int(line.stock_on_hand or 0)

    await apply_transition(
        session,
        order_id=body.order_id,
        action=ACTION_DISPATCH,
        operator_id=operator_id,
        operator_role=OPERATOR_ADMIN,
        trigger_type=TRIGGER_MANUAL,
    )

    return {
        "order_id": body.order_id,
        "order_sn": order.order_sn,
        # "system_tracking_number": tracking_no,
        # "online_order_number": qianyi_result.get("online_order_number") or order.order_sn,
        # "to_status": STATUS_FULFILLING,
        # "qianyi_request_id": qianyi_result.get("request_id"),
    }


async def _resolve_order_creator_name(
    session: AsyncSession, order: DistributionOrder,
) -> str:
    """订单 create_by 对应用户名，供千易 creator 字段。"""
    uid = getattr(order, "create_by", None)
    if not uid:
        return ""
    from apps.system.distribution_order.distribution_order_workflow_engine import (
        _resolve_operator_name,
    )
    name = await _resolve_operator_name(session, uid)
    return (name or "").strip()


async def dispatch_order(
    session: AsyncSession,
    body: DispatchIn,
    *,
    operator_id: Optional[int] = None,
    operator_name: Optional[str] = None,
    shop_dict: Optional[Dict[Any, Any]] = None,
) -> Dict[str, Any]:
    order = await _load_order_for_update(session, body.order_id)
    if int(order.status) != STATUS_PENDING_DISPATCH:
        raise DistributionOrderError(40000, "当前状态不允许下发，仅待下发可操作")
    if not order.shop_id:
        raise DistributionOrderError(40000, "出库店铺未选择，无法下发")

    lines = list(await _load_alive_lines(session, body.order_id, DistributionOrderItemDetail))
    shippable = [ln for ln in lines if _ship_qty(ln) > 0]
    if not shippable:
        raise DistributionOrderError(40000, "无可下发数量的订单明细")

    _assert_dispatch_stock(shippable)
    snapshot = await _load_snapshot(session, body.order_id)
    sid = int(order.shop_id)
    shop_name = str((shop_dict or {}).get(sid) or (shop_dict or {}).get(str(sid)) or "").strip()
    if not shop_name:
        raise DistributionOrderError(40000, "未找到出库店铺对应的千易店铺名")
    biz_param = build_create_sales_order_biz_param(
        order,
        snapshot,
        shippable,
        shop_name=shop_name,
        creator_name=operator_name,
    )
    logger.info(f"千易推送单信息: {biz_param}")

    client = QianyiErpClient()
    try:
        loop = asyncio.get_event_loop()
        qianyi_result = await loop.run_in_executor(
            None, client.create_sales_order, biz_param,
        )
    except QianyiErpError as exc:
        raise DistributionOrderError(exc.code, exc.msg) from exc

    tracking_no = (qianyi_result.get("order_number") or "").strip() or None
    order.system_tracking_number = tracking_no
    order.update_by = operator_id
    for line in shippable:
        need = _ship_qty(line)
        line.dispatched_qty = int(line.dispatched_qty or 0) + need
        line.dispatch_stock_on_hand = int(line.stock_on_hand or 0)

    await apply_transition(
        session,
        order_id=body.order_id,
        action=ACTION_DISPATCH,
        operator_id=operator_id,
        operator_role=OPERATOR_ADMIN,
        trigger_type=TRIGGER_MANUAL,
    )

    return {
        "order_id": body.order_id,
        "order_sn": order.order_sn,
        "system_tracking_number": tracking_no,
        "online_order_number": qianyi_result.get("online_order_number") or order.order_sn,
        "to_status": STATUS_FULFILLING,
        "qianyi_request_id": qianyi_result.get("request_id"),
    }


async def split_order(
    session: AsyncSession,
    body: SplitIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    parent = await _load_order(session, body.order_id)
    if int(parent.status) != STATUS_PENDING_DISPATCH:
        raise DistributionOrderError(40000, "当前状态不允许拆单，仅待下发可操作")
    lines = body.lines or []
    if not lines:
        raise DistributionOrderError(40000, "拆单信息不能为空")

    parent_items = {
        int(r._id): r
        for r in await _load_alive_lines(session, body.order_id, DistributionOrderItemDetail)
    }
    sku_to_item = {(r.sku or "").strip(): r for r in parent_items.values() if (r.sku or "").strip()}

    split_plan = []
    for ln in lines:
        lid = getattr(ln, "id", None)
        sku = (getattr(ln, "sku", None) or "").strip()
        row = None
        if lid is not None:
            try:
                row = parent_items.get(int(lid))
            except Exception as e:
                logger.exception(f"拆单：明细行_id非法: {lid!r}, err={e}")
                row = None
        elif sku:
            row = sku_to_item.get(sku)
        if row is None:
            raise DistributionOrderError(40000, "订单明细行无效或不属于本单")
        if int(ln.qty) <= 0:
            raise DistributionOrderError(40000, "拆单数量必须大于0")
        if int(row.qty or 0) < int(ln.qty):
            raise DistributionOrderError(40000, "拆单数量超过主单可拆数量")
        split_plan.append((row, int(ln.qty)))

    if len(parent_items) == 1:
        only_row = next(iter(parent_items.values()))
        total_split = sum(
            qty for row, qty in split_plan if int(row._id) == int(only_row._id)
        )
        if int(only_row.qty or 0) - total_split <= 0:
            raise DistributionOrderError(
                40000, "主单仅一个SKU时，拆单后主单须至少保留1件",
            )

    # 子单号后缀：-A/-B/...
    child_count = int(
        await session.scalar(
            select(func.count(DistributionOrder._id)).where(
                DistributionOrder.parent_order_id == parent._id,
                DistributionOrder.is_delete == 0,
            )
        ) or 0
    )
    suffix = chr(ord("A") + child_count)
    child_sn = f"{parent.order_sn}-{suffix}"

    await sanitize_order_json_columns(session, parent)
    child = clone_order_for_split(
        parent,
        order_sn=child_sn,
        parent_order_id=int(parent._id),
        operator_id=operator_id,
    )
    session.add(child)
    await session.flush()
    await ensure_sql_null_order_json_from_parent(
        session, int(child._id), parent, order=child,
    )

    parent_snap = await _load_snapshot(session, int(parent._id))
    if parent_snap is not None:
        session.add(clone_snapshot_for_split(parent_snap, int(child._id)))

    copied_quotes = await copy_line_details_from_order(
        session,
        from_order_id=int(parent._id),
        to_order_id=int(child._id),
        kind="quote",
    )

    # 生成子单行 & 扣减主单行数量；行金额/运费与 order_details/save 同一套计算
    child_items = []
    for src, qty_split in split_plan:
        orig_qty = int(src.qty or 0)
        qty_remain = orig_qty - int(qty_split)
        child_fw, child_fwo = split_line_freight_by_qty(
            src, qty_split=int(qty_split), qty_remain=qty_remain,
        )
        src.qty = qty_remain
        apply_order_line_amounts(parent, src)
        apply_line_order_amounts(src)
        if qty_remain <= 0:
            src.qty = 0
            src.is_delete = 1

        item = build_split_order_item(
            src=src,
            child_order_id=int(child._id),
            qty_split=qty_split,
            order=child,
        )
        item.freight_with_vat = child_fw
        item.freight_without_vat = child_fwo
        apply_line_order_amounts(item)
        session.add(item)
        child_items.append(item)

    await session.flush()

    # 预付/尾款等按商品金额占比分摊；运费按行汇总回整主单
    parent_items_now = await _load_alive_lines(session, body.order_id, DistributionOrderItemDetail)
    parent_goods_with = _sum_decimal([r.amount_with_vat for r in parent_items_now])
    child_goods_with = _sum_decimal([r.amount_with_vat for r in child_items])
    denom = parent_goods_with + child_goods_with
    ratio = (child_goods_with / denom) if denom != 0 else Decimal("0")

    child.prepay_amount = _alloc(parent.prepay_amount, ratio)
    child.ewt_amount = _alloc(parent.ewt_amount, ratio)
    child.balance_amount = _alloc(parent.balance_amount, ratio)
    child.adjusted_balance_amount = _alloc(parent.adjusted_balance_amount, ratio)
    child.expected_payment_date = parent.expected_payment_date
    child.actual_payment_date = parent.actual_payment_date

    def _remain(total: Optional[Decimal], part: Optional[Decimal]) -> Optional[Decimal]:
        t = _as_decimal(total)
        p = _as_decimal(part)
        if t is None:
            return None
        return _q2(t - (p or Decimal("0")))

    parent.prepay_amount = _remain(parent.prepay_amount, child.prepay_amount)
    parent.ewt_amount = _remain(parent.ewt_amount, child.ewt_amount)
    parent.balance_amount = _remain(parent.balance_amount, child.balance_amount)
    parent.adjusted_balance_amount = _remain(
        parent.adjusted_balance_amount, child.adjusted_balance_amount,
    )

    sync_order_freight_from_lines(parent, parent_items_now)
    sync_order_freight_from_lines(child, child_items)
    recalc_order_goods_amounts_from_lines(parent, parent_items_now)
    recalc_order_goods_amounts_from_lines(child, child_items)
    parent.update_by = operator_id
    child.update_by = operator_id
    parent.update_time = datetime.datetime.now()
    child.update_time = datetime.datetime.now()

    await refresh_order_tags(session, int(parent._id), order=parent)
    await refresh_order_tags(session, int(child._id), order=child)

    return {
        "order_id": int(body.order_id),
        "child_order_id": int(child._id),
        "child_order_sn": child.order_sn,
        "copied_quote_details": copied_quotes,
    }


def _adjustment_row_dict(row: DistributionOrderAdjustment) -> Dict[str, Any]:
    return {
        "_id": int(row._id),
        "seq": int(row.seq or 0),
        "adjust_amount": row.adjust_amount,
        "fee_category_id": row.fee_category_id,
        "document_attachments": row.document_attachments,
        "remark": row.remark,
        "adjusted_balance_after": row.adjusted_balance_after,
    }


async def _query_adjustments(
    session: AsyncSession, order_id: int,
) -> List[Dict[str, Any]]:
    rows = (
        await session.execute(
            select(DistributionOrderAdjustment).where(
                DistributionOrderAdjustment.order_id == order_id,
            ).order_by(
                DistributionOrderAdjustment.seq.asc(),
                DistributionOrderAdjustment._id.asc(),
            )
        )
    ).scalars().all()
    return [_adjustment_row_dict(r) for r in rows]


async def list_adjustments(
    session: AsyncSession, order_id: int,
) -> List[Dict[str, Any]]:
    await _load_order(session, order_id)
    return await _query_adjustments(session, order_id)


async def get_prepay_confirm(
    session: AsyncSession, order_id: int,
) -> Optional[Dict[str, Any]]:
    row = (
        await session.execute(
            select(DistributionOrderPrepayment).where(
                DistributionOrderPrepayment.order_id == order_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return PrepayConfirmOut.from_orm(row).dict(by_alias=True)


async def get_payment_confirm(
    session: AsyncSession, order_id: int,
) -> Optional[Dict[str, Any]]:
    row = (
        await session.execute(
            select(DistributionOrderBalancePayment).where(
                DistributionOrderBalancePayment.order_id == order_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return PaymentConfirmOut.from_orm(row).dict(by_alias=True)


def _receive_confirm_payload(
    order_lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = ReceiveConfirmOut(
        lines=[
            {
                "_id": ln.get("_id"),
                "sku": ln.get("sku") or "",
                "qty": int(ln.get("qty") or 0),
                "received_qty": ln.get("received_qty"),
                "receive_diff_remark": ln.get("receive_diff_remark"),
            }
            for ln in order_lines
        ],
    )
    return payload.dict(by_alias=True)


async def build_receive_confirm(
    session: AsyncSession,
    order: DistributionOrder,
    order_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    lines = order_lines
    if lines is None:
        lines = await list_line_details(session, int(order._id), "order")
    return _receive_confirm_payload(lines)


async def list_split_child_orders(
    session: AsyncSession, parent_order_id: int,
) -> List[Dict[str, Any]]:
    rows = (
        await session.execute(
            select(DistributionOrder).where(
                DistributionOrder.parent_order_id == parent_order_id,
                DistributionOrder.is_delete == 0,
            ).order_by(DistributionOrder._id.asc())
        )
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = SplitChildOrderOut.from_orm(row).dict(by_alias=True)
        item["status_str"] = STATUS_LABELS.get(int(row.status), str(row.status))
        out.append(item)
    return out


async def build_fulfillment_detail(
    session: AsyncSession,
    order_id: int,
    order: Optional[DistributionOrder] = None,
    order_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    详情页回显：预付/回款/实收/手工调整/拆单子单。
    同一 AsyncSession 须顺序 await，不可用 gather 并发。
    """
    if order is None:
        order = await _load_order(session, order_id)
    return {
        "prepay_confirm": await get_prepay_confirm(session, order_id),
        "payment_confirm": await get_payment_confirm(session, order_id),
        "adjustments": await _query_adjustments(session, order_id),
        "receive_confirm": await build_receive_confirm(
            session, order, order_lines=order_lines,
        ),
        "split_orders": await list_split_child_orders(session, order_id),
    }


def _adjustment_mark_delete(line: Any) -> bool:
    val = getattr(line, "is_delete", None)
    if val is None:
        return False
    return int(val) != 0


def _validate_adjustment_line(line: AdjustmentLineIn) -> tuple:
    if _adjustment_mark_delete(line):
        raise DistributionOrderError(40000, "删除行不应校验业务字段")
    adjust_amt = _as_decimal(line.adjust_amount)
    if adjust_amt is None or adjust_amt <= 0:
        raise DistributionOrderError(40000, "手工调整金额必须大于0")
    if line.fee_category_id is None or int(line.fee_category_id) <= 0:
        raise DistributionOrderError(40000, "费用项不能为空")
    remark = (line.remark or "").strip()
    if not remark:
        raise DistributionOrderError(40000, "手工调整备注不能为空")
    doc_attachments = getattr(line, "document_attachments", None)
    return adjust_amt, int(line.fee_category_id), remark, doc_attachments


async def _load_adjustment_rows(
    session: AsyncSession, order_id: int,
) -> List[DistributionOrderAdjustment]:
    return (
        await session.execute(
            select(DistributionOrderAdjustment).where(
                DistributionOrderAdjustment.order_id == order_id,
            ).order_by(
                DistributionOrderAdjustment.seq.asc(),
                DistributionOrderAdjustment._id.asc(),
            )
        )
    ).scalars().all()


async def _recalc_adjustment_chain(
    session: AsyncSession,
    order: DistributionOrder,
    order_id: int,
    updates_by_id: Optional[Dict[int, Any]] = None,
) -> Decimal:
    """
    按 seq 从尾款金额重算调整链。
    更新行：running 为本条调整前应得尾款（已等价于还原旧调整），再减新 adjust_amount。
    """
    base = _as_decimal(order.balance_amount)
    if base is None:
        raise DistributionOrderError(40000, "尾款金额未计算，请先保存订单明细")
    pending = updates_by_id or {}
    rows = await _load_adjustment_rows(session, order_id)
    running = base
    for row in rows:
        rid = int(row._id)
        upd = pending.get(rid)
        if upd is not None:
            adjust_amt, fee_id, remark, doc_attachments = _validate_adjustment_line(upd)
            row.adjust_amount = adjust_amt
            row.fee_category_id = fee_id
            row.document_attachments = doc_attachments
            row.remark = remark
        else:
            adjust_amt = _as_decimal(row.adjust_amount) or Decimal("0")
        running = _q2(running - adjust_amt)
        if running is not None and running < 0:
            raise DistributionOrderError(40000, "调整后尾款应收不能为负")
        row.adjusted_balance_after = running
    order.adjusted_balance_amount = running if rows else base
    return order.adjusted_balance_amount


async def save_adjustments(
    session: AsyncSession,
    body: AdjustmentBatchSaveIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    """确认预付~待回款（确认回款前）批量保存：无 _id 新增；有 _id 更新；有 _id 且 is_delete≠0 删除并重算链。"""
    order = await _load_order(session, body.order_id)
    if int(order.status) not in ADJUSTMENT_ALLOWED_STATUSES:
        raise DistributionOrderError(40000, "当前状态不允许手工调整")

    lines = body.lines or []
    if not lines:
        raise DistributionOrderError(40000, "手工调整行不能为空")

    if _as_decimal(order.balance_amount) is None:
        raise DistributionOrderError(40000, "尾款金额未计算，请先保存订单明细")

    existing = {
        int(r._id): r
        for r in await _load_adjustment_rows(session, body.order_id)
    }
    max_seq = max((int(r.seq or 0) for r in existing.values()), default=0)
    saved_ids: List[int] = []
    created_ids: List[int] = []
    updated_ids: List[int] = []
    deleted_ids: List[int] = []
    updates_by_id: Dict[int, Any] = {}
    create_lines: List[Any] = []

    for line in lines:
        lid = getattr(line, "id", None)
        if _adjustment_mark_delete(line):
            if lid is None:
                raise DistributionOrderError(40000, "删除须传 _id")
            rid = int(lid)
            if rid not in existing or int(existing[rid].order_id) != int(body.order_id):
                raise DistributionOrderError(40000, "手工调整_id无效或不属于本单")
            deleted_ids.append(rid)
            continue
        if lid is not None:
            rid = int(lid)
            if rid not in existing or int(existing[rid].order_id) != int(body.order_id):
                raise DistributionOrderError(40000, "手工调整_id无效或不属于本单")
            _validate_adjustment_line(line)
            updates_by_id[rid] = line
            saved_ids.append(rid)
            updated_ids.append(rid)
        else:
            _validate_adjustment_line(line)
            create_lines.append(line)

    for rid in deleted_ids:
        row = existing.pop(rid, None)
        if row is not None:
            await session.delete(row)
    if deleted_ids:
        await session.flush()

    for line in create_lines:
        adjust_amt, fee_id, remark, doc_attachments = _validate_adjustment_line(line)
        max_seq += 1
        row = DistributionOrderAdjustment(
            order_id=body.order_id,
            seq=max_seq,
            adjust_amount=adjust_amt,
            fee_category_id=fee_id,
            document_attachments=doc_attachments,
            remark=remark,
            create_by=operator_id,
        )
        session.add(row)
        await session.flush()
        rid = int(row._id)
        saved_ids.append(rid)
        created_ids.append(rid)

    final_balance = await _recalc_adjustment_chain(
        session, order, body.order_id, updates_by_id=updates_by_id,
    )
    order.update_by = operator_id
    await refresh_order_tags(session, body.order_id, order=order)
    return {
        "order_id": body.order_id,
        "created_count": len(created_ids),
        "updated_count": len(updated_ids),
        "deleted_count": len(deleted_ids),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "deleted_ids": deleted_ids,
        "adjustment_ids": saved_ids,
        "last_seq": max_seq,
        "adjusted_balance_after": final_balance,
    }


async def add_adjustment(
    session: AsyncSession,
    body: AdjustmentIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    """单条新增（兼容旧接口，内部走批量保存）。"""
    batch = AdjustmentBatchSaveIn(
        order_id=body.order_id,
        lines=[
            AdjustmentLineIn(
                adjust_amount=body.adjust_amount,
                fee_category_id=body.fee_category_id,
                document_attachments=body.document_attachments,
                remark=body.remark,
            ),
        ],
    )
    data = await save_adjustments(session, batch, operator_id=operator_id)
    adj_ids = data.get("adjustment_ids") or []
    return {
        "order_id": body.order_id,
        "adjustment_id": int(adj_ids[0]) if adj_ids else None,
        "seq": data.get("last_seq"),
        "adjusted_balance_after": data.get("adjusted_balance_after"),
    }
