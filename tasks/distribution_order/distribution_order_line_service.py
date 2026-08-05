# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : distribution_order_line_service.py
# @Description : 报价/订单明细通用 list / save / delete（同构逻辑）
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.system.distribution_order.constants import (
    EDITABLE_ORDER_DETAIL_STATUSES,
    EDITABLE_QUOTE_DETAIL_STATUSES,
)
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.operation_log import get_log_field_label

from apps.system.distribution_order.models import (
    DistributionOrder,
    DistributionOrderItemDetail,
    DistributionOrderQuoteDetail,
    DistributionOrderSnapshot,
)
from apps.system.distribution_order.distribution_order_workflow_engine import (
    STATUS_ORDER_CREATE,
)
from apps.system.distribution_order.schemas import (
    LineDetailIn, OrderDetailOut, QuoteDetailOut,
)
from apps.system.distribution_order.translate import translate_text

_TSchema = TypeVar("_TSchema", bound=BaseModel)

_KIND_QUOTE = "quote"
_KIND_ORDER = "order"

# 拆单复制行时跳过，由 apply_order_line_amounts / 拆单逻辑按新 qty 重算
_LINE_AMOUNT_ATTRS_ON_SPLIT = frozenset({
    "price_without_vat", "amount_with_vat", "amount_without_vat", "vat_amount",
    "freight_with_vat", "freight_without_vat",
    "order_amount_with_vat", "order_amount_without_vat",
})

# ── 行金额计算（与 API_FRONTEND.md §4.3.1 一致；报价/订单明细共用）────────────
_Q2 = Decimal("0.01")
_LINE_AMOUNT_TOL = Decimal("0.01")


def _line_detail_writable_from_schema() -> Tuple[str, ...]:
    """从 LineDetailIn 入参 schema 推导可写字段（排除控制字段）。"""
    keys = list(getattr(LineDetailIn, "__fields__", {}).keys())
    return tuple(k for k in keys if k not in {"id", "is_delete"})


# 可写字段从 schema 推导，避免手写重复维护
_LINE_DETAIL_WRITABLE = _line_detail_writable_from_schema()


@dataclass(frozen=True)
class _LineKindConfig:
    key: str
    model: Type
    out_schema: Type[_TSchema]
    label: str
    editable_statuses: Tuple[int, ...]
    writable_attrs: Tuple[str, ...]


_LINE_KINDS: Dict[str, _LineKindConfig] = {
    _KIND_QUOTE: _LineKindConfig(
        key=_KIND_QUOTE,
        model=DistributionOrderQuoteDetail,
        out_schema=QuoteDetailOut,
        label="报价明细",
        editable_statuses=EDITABLE_QUOTE_DETAIL_STATUSES,
        writable_attrs=_LINE_DETAIL_WRITABLE,
    ),
    _KIND_ORDER: _LineKindConfig(
        key=_KIND_ORDER,
        model=DistributionOrderItemDetail,
        out_schema=OrderDetailOut,
        label="订单明细",
        editable_statuses=EDITABLE_ORDER_DETAIL_STATUSES,
        writable_attrs=_LINE_DETAIL_WRITABLE + ("is_protocol_sample", "freight_with_vat"),
    ),
}


def line_kind_config(kind: str) -> _LineKindConfig:
    cfg = _LINE_KINDS.get(kind)
    if cfg is None:
        raise DistributionOrderError(
            40001, "明细类型无效，仅支持 quote / order",
        )
    return cfg


async def _load_order(
    session: AsyncSession, order_id: int,
) -> DistributionOrder:
    row = (
        await session.execute(
            select(DistributionOrder).where(
                DistributionOrder._id == order_id,
                DistributionOrder.is_delete == 0,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise DistributionOrderError(40400, "订单不存在")
    return row


async def _load_alive_lines(
    session: AsyncSession, order_id: int, model: Type,
) -> List[Any]:
    return (
        await session.execute(
            select(model).where(
                model.order_id == order_id,
                model.is_delete == 0,
            ).order_by(model._id.asc())
        )
    ).scalars().all()


def _orm_out_dict(
    model_cls: Type[_TSchema], row: Any,
) -> Dict[str, Any]:
    return model_cls.from_orm(row).dict(by_alias=True)


async def list_line_details(
    session: AsyncSession, order_id: int, kind: str,
) -> List[Dict[str, Any]]:
    cfg = line_kind_config(kind)
    await _load_order(session, order_id)
    rows = await _load_alive_lines(session, order_id, cfg.model)
    return [_orm_out_dict(cfg.out_schema, r) for r in rows]


def _assert_alive_sku_unique(
    lines: List[Any],
    existing_by_id: Dict[int, Any],
    *,
    label: str,
) -> None:
    """按本批 upsert 后的 SKU 占用校验（含同批改 SKU 释放旧值）。"""
    sku_to_id: Dict[str, int] = {}
    for row in existing_by_id.values():
        sku = (row.sku or "").strip()
        if sku:
            sku_to_id[sku] = int(row._id)

    for lid in {_line_row_id(ln) for ln in lines if _line_row_id(ln)}:
        for sku, rid in list(sku_to_id.items()):
            if rid == lid:
                del sku_to_id[sku]

    new_seq = 0
    for line in lines:
        sku = (getattr(line, "sku", None) or "").strip()
        if not sku:
            continue
        lid = _line_row_id(line)
        holder = sku_to_id.get(sku)
        if holder is not None and holder != lid:
            raise DistributionOrderError(
                40001, "%sSKU已存在：%s" % (label, sku),
            )
        if lid:
            sku_to_id[sku] = lid
        else:
            new_seq -= 1
            sku_to_id[sku] = new_seq


def _line_row_id(line: Any) -> Optional[int]:
    lid = getattr(line, "id", None)
    if lid is None:
        return None
    try:
        return int(lid)
    except (TypeError, ValueError):
        return None


def _line_mark_delete(line: Any) -> bool:
    val = getattr(line, "is_delete", None)
    if val is None:
        return False
    return int(val) != 0


def _line_patch_dict(line: Any, attrs: Tuple[str, ...]) -> Dict[str, Any]:
    if isinstance(line, BaseModel):
        data = line.dict(exclude_unset=True, by_alias=True)
        for key in ("_id", "id", "is_delete"):
            data.pop(key, None)
        return {k: v for k, v in data.items() if k in attrs}
    out: Dict[str, Any] = {}
    for attr in attrs:
        val = getattr(line, attr, None)
        if val is not None:
            out[attr] = val
    return out


def _apply_writable_fields(row: Any, line: Any, attrs: Tuple[str, ...]) -> None:
    patch = _line_patch_dict(line, attrs)
    for attr, val in patch.items():
        if attr == "sku":
            sku = (val or "").strip()
            if sku:
                row.sku = sku
            continue
        if attr == "qty":
            row.qty = None if val is None else int(val)
        elif attr == "is_protocol_sample":
            row.is_protocol_sample = int(val) if val is not None else 0
        elif attr in (
            "stock_on_hand", "stock_in_transit", "stock_planned",
        ):
            setattr(row, attr, 0 if val is None else int(val))
        else:
            setattr(row, attr, val)


def _d2(val: Optional[Any]) -> Decimal:
    """转为 Decimal，不四舍五入（命名 d2 为历史习惯，非保留 2 位）。"""
    if val is None:
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _q2(val: Decimal) -> Decimal:
    return Decimal(val).quantize(_Q2, rounding=ROUND_HALF_UP)


def _prepayment_ratio_decimal(ratio: Optional[Any]) -> Decimal:
    """预付比例：前端传整数百分比（如 30 表示 30%），计算时除以 100。"""
    return _d2(ratio) / Decimal("100")


def _abs(val: Decimal) -> Decimal:
    return val.copy_abs()


def _assert_decimal_close(
    *,
    field_key: str,
    actual: Optional[Any],
    expected: Optional[Decimal],
    tol: Decimal,
    filter_value: Optional[List[Dict[str, Any]]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    if actual is None or expected is None:
        return
    a = _d2(actual)
    if _abs(a - expected) > tol:
        trans = translation_dict or {}
        field_label = translate_text(
            get_log_field_label(field_key, filter_value),
            is_trans,
            trans,
        )
        part_1 = translate_text("校验失败", is_trans, trans)
        part_2 = translate_text("传入", is_trans, trans)
        part_3 = translate_text("应为", is_trans, trans)
        raise DistributionOrderError(
            40000,
            "%s%s：%s %s，%s %s"
            % (field_label, part_1, part_2, str(a), part_3, str(expected)),
        )


def _vat_rate_for_order(order: DistributionOrder) -> Decimal:
    """主单 VAT 税率：is_tax_free=1 时为 0；否则取 vat_rate（小数，如 0.07=7%）。"""
    if int(order.is_tax_free or 0) == 1:
        return Decimal("0")
    if order.vat_rate is None:
        return Decimal("0")
    return _d2(order.vat_rate)


def _calc_price_without_vat(
    *, price_with_vat: Decimal, vat_rate: Decimal,
) -> Decimal:
    """不含税单价 = 含税单价 / (1 + VAT税率)，四舍五入 2 位小数。"""
    denom = Decimal("1") + vat_rate
    if denom == 0:
        return Decimal("0")
    return _q2(price_with_vat / denom)


def _calc_order_line_amounts(
    *,
    qty: int,
    price_with_vat: Decimal,
    vat_rate: Decimal,
) -> Dict[str, Decimal]:
    """
    报价/订单明细行金额（save 时后端重算并落库；与前端展示公式一致）。

    输入：用户录入 price_with_vat、qty；税率 vat_rate 来自主单。
    price_with_vat 原值参与运算，不对含税单价先行 round2。
    步骤（对齐需求文档 §2.2.0）：
      1. price_without_vat = round2(price_with_vat / (1 + vat_rate))
      2. amount_with_vat    = round2(price_with_vat * qty)
      3. amount_without_vat = round2(price_without_vat * qty)
      4. vat_amount         = round2(amount_with_vat - amount_without_vat)
    round 规则：ROUND_HALF_UP（与 JS toFixed 一致）。
    """
    if not isinstance(price_with_vat, Decimal):
        price_with_vat = _d2(price_with_vat)
    qty = int(qty or 0)
    p_wo = _calc_price_without_vat(price_with_vat=price_with_vat, vat_rate=vat_rate)
    amt_w = _q2(price_with_vat * Decimal(qty))
    amt_wo = _q2(p_wo * Decimal(qty))
    vat_amt = _q2(amt_w - amt_wo)
    return {
        "price_without_vat": p_wo,
        "amount_with_vat": amt_w,
        "amount_without_vat": amt_wo,
        "vat_amount": vat_amt,
    }


def _apply_line_auto_calc_and_validate(
    *,
    order: DistributionOrder,
    row: Any,
    line: Any,
    kind: str = _KIND_ORDER,
    filter_value: Optional[List[Dict[str, Any]]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    """报价/订单明细：按含税单价×数量重算行金额；前端传了则校验，最终以计算值落库。"""
    if _line_mark_delete(line):
        return
    price_with = getattr(line, "price_with_vat", None)
    qty = getattr(line, "qty", None)
    if price_with is None:
        return

    vat_rate = _vat_rate_for_order(order)
    _kw = {
        "filter_value": filter_value,
        "is_trans": is_trans,
        "translation_dict": translation_dict,
    }
    # 报价阶段可不填数量：仅回填不含税单价，行金额留空
    if qty is None:
        if kind != _KIND_QUOTE:
            return
        p_wo = _calc_price_without_vat(price_with_vat=price_with, vat_rate=vat_rate)
        _assert_decimal_close(
            field_key="price_without_vat",
            actual=getattr(line, "price_without_vat", None),
            expected=p_wo,
            tol=_LINE_AMOUNT_TOL,
            **_kw,
        )
        row.price_without_vat = p_wo
        row.amount_with_vat = None
        row.amount_without_vat = None
        row.vat_amount = None
        return

    calc = _calc_order_line_amounts(
        qty=int(qty), price_with_vat=price_with, vat_rate=vat_rate,
    )

    _assert_decimal_close(
        field_key="price_without_vat",
        actual=getattr(line, "price_without_vat", None),
        expected=calc["price_without_vat"],
        tol=_LINE_AMOUNT_TOL,
        **_kw,
    )
    _assert_decimal_close(
        field_key="amount_with_vat",
        actual=getattr(line, "amount_with_vat", None),
        expected=calc["amount_with_vat"],
        tol=_LINE_AMOUNT_TOL,
        **_kw,
    )
    _assert_decimal_close(
        field_key="amount_without_vat",
        actual=getattr(line, "amount_without_vat", None),
        expected=calc["amount_without_vat"],
        tol=_LINE_AMOUNT_TOL,
        **_kw,
    )
    _assert_decimal_close(
        field_key="vat_amount",
        actual=getattr(line, "vat_amount", None),
        expected=calc["vat_amount"],
        tol=_LINE_AMOUNT_TOL,
        **_kw,
    )

    row.price_without_vat = calc["price_without_vat"]
    row.amount_with_vat = calc["amount_with_vat"]
    row.amount_without_vat = calc["amount_without_vat"]
    row.vat_amount = calc["vat_amount"]


def _apply_order_quote_check_passed(row: Any) -> None:
    """
    订单明细 quote_check_passed（保存时后端计算，不入参）：
    协议样品=1；否则含税单价>=红线价=1，缺单价或红线价=0。
    """
    if not hasattr(row, "quote_check_passed"):
        return
    if int(getattr(row, "is_protocol_sample", 0) or 0) == 1:
        row.quote_check_passed = 1
        return
    price = getattr(row, "price_with_vat", None)
    red = getattr(row, "red_line_price", None)
    if price is None or red is None:
        row.quote_check_passed = 0
        return
    row.quote_check_passed = 1 if _d2(price) >= _d2(red) else 0


def _allocate_amount_by_ratio(
    total: Decimal,
    weights: Sequence[Decimal],
) -> List[Decimal]:
    """按权重分摊 total，前 N-1 行四舍五入，最后一行吃尾差。"""
    n = len(weights)
    if n == 0:
        return []
    if total == 0:
        return [Decimal("0")] * n
    weight_sum = sum(weights, Decimal("0"))
    if weight_sum == 0:
        return [Decimal("0")] * n
    parts: List[Decimal] = []
    allocated = Decimal("0")
    for i, w in enumerate(weights):
        if i < n - 1:
            part = _q2(total * w / weight_sum)
            parts.append(part)
            allocated += part
        else:
            parts.append(_q2(total - allocated))
    return parts


def apply_line_order_amounts(row: DistributionOrderItemDetail) -> None:
    """行订单总额 = 商品金额 + 分摊运费。"""
    row.order_amount_with_vat = _q2(
        _d2(row.amount_with_vat) + _d2(row.freight_with_vat),
    )
    row.order_amount_without_vat = _q2(
        _d2(row.amount_without_vat) + _d2(row.freight_without_vat),
    )


def allocate_freight_to_order_lines(
    order: DistributionOrder,
    rows: Sequence[DistributionOrderItemDetail],
) -> None:
    """按行商品金额占比分摊主单运费，写入行级 freight/order_amount。"""
    if not rows:
        return
    freight_with = _d2(order.freight_with_vat)
    freight_without = _d2(order.freight_without_vat)
    weights_with = [_d2(r.amount_with_vat) for r in rows]
    weights_without = [_d2(r.amount_without_vat) for r in rows]
    parts_with = _allocate_amount_by_ratio(freight_with, weights_with)
    parts_without = _allocate_amount_by_ratio(freight_without, weights_without)
    for row, fw, fwo in zip(rows, parts_with, parts_without):
        row.freight_with_vat = fw
        row.freight_without_vat = fwo
        apply_line_order_amounts(row)


def sync_order_freight_from_lines(
    order: DistributionOrder,
    rows: Sequence[DistributionOrderItemDetail],
) -> None:
    """主单运费与存活明细行汇总对齐（拆单回整）。"""
    if not rows:
        order.freight_with_vat = Decimal("0")
        order.freight_without_vat = Decimal("0")
        return
    order.freight_with_vat = _q2(
        sum((_d2(r.freight_with_vat) for r in rows), Decimal("0")),
    )
    order.freight_without_vat = _q2(
        sum((_d2(r.freight_without_vat) for r in rows), Decimal("0")),
    )


def split_line_freight_by_qty(
    src: DistributionOrderItemDetail,
    *,
    qty_split: int,
    qty_remain: int,
) -> Tuple[Decimal, Decimal]:
    """按数量比例从父行拆出运费，返回 (子单行含税运费, 子单行不含税运费)。"""
    orig_qty = int(qty_split) + int(qty_remain)
    if orig_qty <= 0 or qty_split <= 0:
        return Decimal("0"), Decimal("0")
    fw = _d2(src.freight_with_vat)
    fwo = _d2(src.freight_without_vat)
    if qty_remain <= 0:
        return _q2(fw), _q2(fwo)
    child_fw = _q2(fw * Decimal(qty_split) / Decimal(orig_qty))
    child_fwo = _q2(fwo * Decimal(qty_split) / Decimal(orig_qty))
    src.freight_with_vat = _q2(fw - child_fw)
    src.freight_without_vat = _q2(fwo - child_fwo)
    return child_fw, child_fwo


def recalc_order_goods_amounts_from_lines(
    order: DistributionOrder,
    rows: Sequence[Any],
) -> None:
    """按明细行汇总商品金额并刷新订单总额（叠加运费）；order_details/save 与拆单共用。"""
    goods_with = _q2(sum((_d2(r.amount_with_vat) for r in rows), Decimal("0")))
    goods_without = _q2(sum((_d2(r.amount_without_vat) for r in rows), Decimal("0")))
    vat_total = _q2(sum((_d2(r.vat_amount) for r in rows), Decimal("0")))
    order.goods_amount_with_vat = goods_with
    order.goods_amount_without_vat = goods_without
    order.vat_amount_total = vat_total
    freight_with = order.freight_with_vat
    freight_wo = order.freight_without_vat
    order.order_amount_with_vat = _q2(
        goods_with + (_d2(freight_with) if freight_with is not None else Decimal("0")),
    )
    order.order_amount_without_vat = _q2(
        goods_without + (_d2(freight_wo) if freight_wo is not None else Decimal("0")),
    )


async def _recalc_order_amounts_after_order_detail_save(
    session: AsyncSession, order: DistributionOrder,
) -> None:
    """订单创建阶段：保存订单明细后回填主表汇总金额字段。"""
    from apps.system.distribution_order.constants import CREATE_SOURCE_BATCH_DROPSHIP

    rows = await _load_alive_lines(
        session, int(order._id), DistributionOrderItemDetail,
    )

    # 运费不含税：含税运费 / (1 + VAT税率)。免税时 VAT=0。
    vat_rate = Decimal("0")
    if int(order.is_tax_free or 0) == 0 and order.vat_rate is not None:
        vat_rate = _d2(order.vat_rate)

    if int(getattr(order, "create_source", 0) or 0) == CREATE_SOURCE_BATCH_DROPSHIP:
        # 一件代发批量：行运费权威，主单运费=行汇总
        denom = Decimal("1") + vat_rate
        for row in rows:
            fw = _d2(row.freight_with_vat)
            if denom == 0:
                row.freight_without_vat = Decimal("0")
            else:
                row.freight_without_vat = _q2(fw / denom)
            apply_line_order_amounts(row)
        sync_order_freight_from_lines(order, rows)
    else:
        freight_with = order.freight_with_vat
        if freight_with is not None:
            denom = Decimal("1") + vat_rate
            if denom == 0:
                order.freight_without_vat = Decimal("0")
            else:
                order.freight_without_vat = _q2(_d2(freight_with) / denom)
        allocate_freight_to_order_lines(order, rows)

    recalc_order_goods_amounts_from_lines(order, rows)

    # 预付款金额：含税订单总额 * 预付款比例（无预付则 0；比例为整数%，如 30=30%）
    prepay_ratio = (
        _prepayment_ratio_decimal(order.prepayment_ratio)
        if int(order.is_prepayment or 0) == 1
        else Decimal("0")
    )
    order.prepay_amount = _q2(_d2(order.order_amount_with_vat) * prepay_ratio)

    # 预扣税金额：含税订单总额 * 预扣税比例（未选预扣税则 0）
    ewt_rate = _d2(order.ewt_rate) if int(order.is_ewt or 0) == 1 else Decimal("0")
    order.ewt_amount = _q2(_d2(order.order_amount_with_vat) * ewt_rate)

    # 尾款金额：含税订单总额 - 预付款金额
    order.balance_amount = _q2(_d2(order.order_amount_with_vat) - _d2(order.prepay_amount))

    # 调整后尾款应收：无调整时默认等于尾款金额；有值则不覆盖（避免覆盖手工调整结果）
    if order.adjusted_balance_amount is None:
        order.adjusted_balance_amount = order.balance_amount

    # # 预计回款日期：
    # # - 结算方式=带款提货：出库日期
    # # - 结算方式=账期：出库日期 + 合同约定 settlement_days（PRD 还有 +3/+5 但缺少区分字段，此处按 settlement_days 计算）  若 settlement_method 结算方式 为 1.带货提款 2.
    # ship_date = order.actual_ship_date
    # if ship_date:
    #     if int(order.settlement_method or 0) == 1:
    #         order.expected_payment_date = ship_date
    #     elif int(order.settlement_method or 0) == 2:
    #         snap = (
    #             await session.execute(
    #                 select(DistributionOrderSnapshot).where(
    #                     DistributionOrderSnapshot.order_id == int(order._id),
    #                 )
    #             )
    #         ).scalar_one_or_none()
    #         effective_node = snap.effective_node
    #         days = int(getattr(snap, "settlement_days", 0) or 0) if snap is not None else 0
    #         if effective_node == 0:
    #             days += 3
    #         elif effective_node == 1:
    #             days += 5
    #
    #         if days > 0:
    #             order.expected_payment_date = ship_date + datetime.timedelta(days=days)
    #         else:
    #             order.expected_payment_date = ship_date


async def soft_delete_line_details(
    session: AsyncSession,
    order_id: int,
    kind: str,
    detail_ids: List[int],
    *,
    check_status: bool = True,
) -> None:
    if not detail_ids:
        return
    cfg = line_kind_config(kind)
    if check_status:
        order = await _load_order(session, order_id)
        if order.status not in cfg.editable_statuses:
            raise DistributionOrderError(
                40900, "当前状态不允许删除%s" % cfg.label,
            )
    ids = list(set(detail_ids))
    rows = (
        await session.execute(
            select(cfg.model).where(
                cfg.model.order_id == order_id,
                cfg.model._id.in_(ids),
                cfg.model.is_delete == 0,
            )
        )
    ).scalars().all()
    if len(rows) != len(ids):
        raise DistributionOrderError(
            40001, "%s_id无效或不属于本单" % cfg.label,
        )
    for row in rows:
        row.is_delete = 1


async def soft_delete_all_alive_line_details(
    session: AsyncSession,
    order_id: int,
    kind: str,
    *,
    check_status: bool = True,
) -> int:
    """软删本单全部未删除明细行，返回删除条数。"""
    cfg = line_kind_config(kind)
    if check_status:
        order = await _load_order(session, order_id)
        if order.status not in cfg.editable_statuses:
            raise DistributionOrderError(
                40900, "当前状态不允许删除%s" % cfg.label,
            )
    rows = await _load_alive_lines(session, order_id, cfg.model)
    for row in rows:
        row.is_delete = 1
    return len(rows)


async def save_line_details(
    session: AsyncSession,
    order_id: int,
    kind: str,
    lines: List[Any],
    extra_delete_ids: Optional[List[int]] = None,
    *,
    check_status: bool = True,
    replace_all: bool = True,
    filter_value: Optional[List[Dict[str, Any]]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    """
    批量保存明细。
    replace_all=False：无 _id 新增；有 _id 更新；有 _id 且 is_delete≠0 软删。
    replace_all=True：软删本单全部存活行后按 body 全部新建（忽略行上 _id）。
    """
    cfg = line_kind_config(kind)
    order: Optional[DistributionOrder] = None
    if check_status:
        order = await _load_order(session, order_id)
        if order.status not in cfg.editable_statuses:
            raise DistributionOrderError(
                40000, "当前状态不允许编辑%s" % cfg.label,
            )

    if replace_all:
        await soft_delete_all_alive_line_details(
            session, order_id, kind, check_status=False,
        )
        await session.flush()
        create_lines = [
            line for line in (lines or []) if not _line_mark_delete(line)
        ]
        if kind == "quote":
            _assert_alive_sku_unique(create_lines, {}, label=cfg.label)
        for line in create_lines:
            sku = (getattr(line, "sku", None) or "").strip()
            row = cfg.model(order_id=order_id, sku=sku or "")
            session.add(row)
            await session.flush()
            _apply_writable_fields(row, line, cfg.writable_attrs)
            if order is None:
                order = await _load_order(session, order_id)
            _apply_line_auto_calc_and_validate(
                order=order,
                row=row,
                line=line,
                kind=kind,
                filter_value=filter_value,
                is_trans=is_trans,
                translation_dict=translation_dict,
            )
            if kind == _KIND_ORDER:
                _apply_order_quote_check_passed(row)
        if kind == _KIND_ORDER:
            if order is None:
                order = await _load_order(session, order_id)
            if int(order.status) == STATUS_ORDER_CREATE:
                await _recalc_order_amounts_after_order_detail_save(session, order)
        from apps.system.distribution_order.distribution_order_tags import (
            refresh_order_tags,
        )
        await refresh_order_tags(session, order_id)
        return

    delete_ids: List[int] = list(extra_delete_ids or [])
    delete_id_set = set(delete_ids)
    upsert_lines: List[Any] = []
    for line in lines or []:
        lid = _line_row_id(line)
        if lid and _line_mark_delete(line):
            if lid not in delete_id_set:
                delete_ids.append(lid)
            delete_id_set.add(lid)
            continue
        if not lid and _line_mark_delete(line):
            raise DistributionOrderError(
                40000, "%s软删须传_id" % cfg.label,
            )
        if lid and lid in delete_id_set:
            continue
        upsert_lines.append(line)
    await soft_delete_line_details(
        session, order_id, kind, delete_ids, check_status=False,
    )
    if not upsert_lines:
        return
    existing = {
        r._id: r
        for r in await _load_alive_lines(session, order_id, cfg.model)
    }
    if kind == "quote":
        _assert_alive_sku_unique(upsert_lines, existing, label=cfg.label)
    for line in upsert_lines:
        lid = _line_row_id(line)
        sku = (getattr(line, "sku", None) or "").strip()
        if lid:
            if lid not in existing:
                raise DistributionOrderError(
                    40001, "%s_id无效或已删除：%s" % (cfg.label, lid),
                )
            row = existing[lid]
        else:
            row = cfg.model(order_id=order_id, sku=sku or "")
            session.add(row)
            await session.flush()
            existing[row._id] = row
        _apply_writable_fields(row, line, cfg.writable_attrs)
        if order is None:
            order = await _load_order(session, order_id)
        _apply_line_auto_calc_and_validate(
            order=order,
            row=row,
            line=line,
            kind=kind,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
        if kind == _KIND_ORDER and not _line_mark_delete(line):
            _apply_order_quote_check_passed(row)

    # 订单创建阶段：每次批量保存订单明细后，回填主表汇总金额字段（销售结算区块）
    if kind == _KIND_ORDER:
        if order is None:
            order = await _load_order(session, order_id)
        if int(order.status) == STATUS_ORDER_CREATE:
            await _recalc_order_amounts_after_order_detail_save(session, order)

    from apps.system.distribution_order.distribution_order_tags import (
        refresh_order_tags,
    )
    await refresh_order_tags(session, order_id)


async def copy_line_details_from_order(
    session: AsyncSession,
    *,
    from_order_id: int,
    to_order_id: int,
    kind: str,
) -> int:
    """复制源单明细行到目标单；字段取自 line_kind_config.writable_attrs（与 ORM/schema 一致）。"""
    cfg = line_kind_config(kind)
    rows = await _load_alive_lines(session, from_order_id, cfg.model)
    for src in rows:
        row = cfg.model(order_id=to_order_id)
        for attr in cfg.writable_attrs:
            setattr(row, attr, getattr(src, attr))
        session.add(row)
    return len(rows)


def apply_order_line_amounts(
    order: DistributionOrder,
    row: DistributionOrderItemDetail,
) -> None:
    """按主单税率回填订单明细行不含税单价与行金额（与 order_details/save 一致）。"""
    if row.price_with_vat is None or row.qty is None:
        return
    vat_rate = _vat_rate_for_order(order)
    calc = _calc_order_line_amounts(
        qty=int(row.qty),
        price_with_vat=row.price_with_vat,
        vat_rate=vat_rate,
    )
    row.price_without_vat = calc["price_without_vat"]
    row.amount_with_vat = calc["amount_with_vat"]
    row.amount_without_vat = calc["amount_without_vat"]
    row.vat_amount = calc["vat_amount"]


def build_split_order_item(
    *,
    src: DistributionOrderItemDetail,
    child_order_id: int,
    qty_split: int,
    order: DistributionOrder,
) -> DistributionOrderItemDetail:
    """拆单：从父单订单明细复制一行到子单并依拆出数量重算金额（规则同 §4.3.1）。"""
    cfg = line_kind_config(_KIND_ORDER)
    row = cfg.model(order_id=child_order_id)
    for attr in cfg.writable_attrs:
        if attr in _LINE_AMOUNT_ATTRS_ON_SPLIT:
            continue
        setattr(row, attr, getattr(src, attr))
    row.is_protocol_sample = int(src.is_protocol_sample or 0)
    row.quote_check_passed = int(src.quote_check_passed or 0)
    row.qty = int(qty_split)
    row.dispatched_qty = 0
    row.received_qty = None
    row.receive_diff_remark = None
    row.dispatch_stock_on_hand = None
    apply_order_line_amounts(order, row)
    _apply_order_quote_check_passed(row)
    return row
