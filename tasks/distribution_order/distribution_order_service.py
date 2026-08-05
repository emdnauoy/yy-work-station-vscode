# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : distribution_order_service.py
# @Description : 分销订单主单 list / detail / draft.save
"""
from __future__ import annotations

import datetime
import math
import secrets
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar

from pydantic import BaseModel

from sqlalchemy import and_, asc, case, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import attributes as orm_attributes
from sqlalchemy.orm.attributes import flag_modified

from apps.system.offline_customer.models import OfflineCustomer
from apps.system.distribution_order.constants import (
    CREATE_SOURCE_BATCH_DROPSHIP,
    CREATE_SOURCE_LABELS,
    COOPERATION_METHOD_LABELS,
    EDITABLE_DRAFT_STATUSES,
    EDITABLE_ORDER_DETAIL_STATUSES,
    LARGE_AMOUNT_USD_THRESHOLD,
    STATUS_BUTTON_LIST,
    STATUS_LABELS,
)
from apps.system.distribution_order.distribution_order_line_service import (
    _load_alive_lines,
    _recalc_order_amounts_after_order_detail_save,
    allocate_freight_to_order_lines,
    list_line_details,
    save_line_details,
)
from apps.system.distribution_order.distribution_order_tags import (
    attach_tags_display,
    order_amount_usd,
    refresh_order_tags,
)
from apps.system.distribution_order.distribution_order_workflow_engine import (
    ACTION_ORDER_SUBMIT,
    CHAIN_ORDER_LARGE,
    CHAIN_ORDER_TH_LARGE,
    CHAIN_ORDER_STANDARD,
    OPERATOR_CREATOR,
    ORDER_CHAIN_CODES,
    STATUS_DRAFT,
    STATUS_ORDER_CREATE,
    STATUS_ORDER_REVIEW,
    STATUS_VOIDED,
    TRIGGER_MANUAL,
    apply_transition,
    assert_chain_has_approvers,
    get_customer_country,
    normalize_line_manager_user_id,
    void_order,
)
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.models import (
    DistributionOrder,
    DistributionOrderItemDetail,
    DistributionOrderSnapshot,
    _ORDER_JSON_KEYS,
    normalize_json_column,
)
from apps.system.distribution_order.schemas import (
    DistributionOrderCreateIn,
    DistributionOrderDraftIn,
    DistributionOrderOut,
    DistributionOrderSnapshotIn,
    DistributionOrderSnapshotOut,
    OrderSubmitIn,
    RemarkSaveIn,
    VoidIn,
)
from apps.system.supplier_admission.service.sequence import SequenceService

_TSchema = TypeVar("_TSchema", bound=BaseModel)


def build_order_save_data(order_id: int, order_sn: Optional[str] = None) -> Dict[str, Any]:
    return {
        "_id": order_id,
        "id": order_id,
        "order_id": order_id,
        "order_sn": order_sn,
    }


_SNAPSHOT_KEYS = tuple(DistributionOrderSnapshotIn.__fields__.keys())

# 拆单复制主表时跳过的列（子单单独赋值或库默认）
_ORDER_SPLIT_SKIP_COLS: Set[str] = {
    "_id", "order_sn", "parent_order_id",
    "create_time", "update_time", "create_by", "update_by", "is_delete",
}
# 拆单复制快照时跳过的列
_SNAPSHOT_SPLIT_SKIP_COLS: Set[str] = {"order_id", "create_time", "update_time"}
# JSON 列：规范化 "null" 字符串并深拷贝
_JSON_COLUMN_NAMES: Set[str] = {
    "customer_po_attachments",
    "ship_guide_attachments",
    "bank_account_confirmation",
}

# DraftIn = 快照 + 主表 + id/明细；主表键与 schemas 同步，避免手写白名单漂移
_DRAFT_NON_MAIN_KEYS = frozenset({
    "id", "quote_details", "deleted_quote_detail_ids",
})
_MAIN_BODY_KEYS = tuple(
    k for k in DistributionOrderDraftIn.__fields__
    if k not in _SNAPSHOT_KEYS and k not in _DRAFT_NON_MAIN_KEYS
)

_ORDER_CREATE_SKIP_KEYS = frozenset({
    "id", "_id", "order_details", "deleted_order_detail_ids",
})


def status_str(status: int) -> str:
    return STATUS_LABELS.get(status, str(status))


def create_source_str(create_source: Any) -> str:
    return CREATE_SOURCE_LABELS.get(int(create_source or 0), str(create_source or ""))


def cooperation_method_str(cooperation_method: Any) -> str:
    if cooperation_method is None:
        return ""
    return COOPERATION_METHOD_LABELS.get(
        int(cooperation_method), str(cooperation_method),
    )


_FILTER_DATETIME_FMTS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
)
_FILTER_DATE_FMTS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d")


def _parse_list_datetime(val: Optional[str]) -> Optional[datetime.datetime]:
    s = (val or "").strip()
    if not s:
        return None
    for fmt in _FILTER_DATETIME_FMTS:
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise DistributionOrderError(40000, "时间格式无效")


def _parse_list_date(val: Optional[str]) -> Optional[datetime.date]:
    s = (val or "").strip()
    if not s:
        return None
    for fmt in _FILTER_DATE_FMTS:
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise DistributionOrderError(40000, "日期格式无效")


def append_list_datetime_range(
    conds: List[Any],
    column: Any,
    start_val: str = "",
    end_val: str = "",
) -> None:
    """列表筛选：DateTime 列闭区间；仅日期时 start 00:00:00、end 23:59:59。"""
    start_dt = _parse_list_datetime(start_val)
    end_dt = _parse_list_datetime(end_val)
    if start_dt is not None:
        if len((start_val or "").strip()) <= 10:
            start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        conds.append(column >= start_dt)
    if end_dt is not None:
        if len((end_val or "").strip()) <= 10:
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        conds.append(column <= end_dt)


def append_list_date_range(
    conds: List[Any],
    column: Any,
    start_val: str = "",
    end_val: str = "",
) -> None:
    """列表筛选：Date 列闭区间。"""
    start_d = _parse_list_date(start_val)
    end_d = _parse_list_date(end_val)
    if start_d is not None:
        conds.append(column >= start_d)
    if end_d is not None:
        conds.append(column <= end_d)


def build_distribution_order_list_order_by(
    date_sort: Dict[str, Any],
    *,
    ref_date: Optional[datetime.date] = None,
) -> List[Any]:
    """
    列表排序。

    expected_ship_date：逾期未出库优先（逾期越久越靠前）→ 临近期望出库 → 未填/已出库沉底。
    其余字段：按 ascend/descend 排序，同序时 _id 降序。
    """
    sort_key = (date_sort.get("key") or "create_time").strip()
    sort_value = (date_sort.get("value") or "descend").strip()
    today = ref_date or datetime.date.today()

    if sort_key == "expected_ship_date":
        not_shipped = DistributionOrder.actual_ship_date.is_(None)
        has_expected = DistributionOrder.expected_ship_date.isnot(None)
        overdue = and_(
            has_expected, not_shipped, DistributionOrder.expected_ship_date < today,
        )
        upcoming = and_(
            has_expected, not_shipped, DistributionOrder.expected_ship_date >= today,
        )
        sort_tier = case((overdue, 0), (upcoming, 1), else_=2)
        sort_date = case(
            (and_(has_expected, not_shipped), DistributionOrder.expected_ship_date),
            else_=None,
        )
        return [asc(sort_tier), asc(sort_date), desc(DistributionOrder._id)]

    simple_sort = {
        "create_time": DistributionOrder.create_time,
        "update_time": DistributionOrder.update_time,
        "expected_payment_date": DistributionOrder.expected_payment_date,
        "actual_ship_date": DistributionOrder.actual_ship_date,
        "actual_payment_date": DistributionOrder.actual_payment_date,
    }
    column = simple_sort.get(sort_key)
    if column is None and hasattr(DistributionOrder, sort_key):
        column = getattr(DistributionOrder, sort_key)
    if column is not None:
        order_expr = desc(column) if sort_value == "descend" else asc(column)
        return [order_expr, desc(DistributionOrder._id)]
    return [desc(DistributionOrder._id)]


async def list_distribution_orders(
    session: AsyncSession,
    *,
    keyword: str = "",
    status_list: Optional[List[int]] = None,
    offline_customer_ids: Optional[List[int]] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    conds = [DistributionOrder.is_delete == 0]
    if status_list:
        conds.append(DistributionOrder.status.in_(status_list))
    if offline_customer_ids:
        conds.append(
            DistributionOrder.offline_customer_id.in_(offline_customer_ids)
        )
    kw = (keyword or "").strip()
    if kw:
        like = "%{}%".format(kw)
        conds.append(
            or_(
                DistributionOrder.order_sn.like(like),
                DistributionOrder.customer_code.like(like),
                DistributionOrder.customer_short_name.like(like),
            )
        )
    total = int(
        await session.scalar(
            select(func.count(DistributionOrder._id)).where(*conds)
        ) or 0
    )
    page = max(page, 1)
    page_size = max(min(page_size, 200), 1)
    offset = (page - 1) * page_size
    rows = (
        await session.execute(
            select(DistributionOrder).where(*conds)
            .order_by(DistributionOrder._id.desc())
            .offset(offset).limit(page_size)
        )
    ).scalars().all()
    t_data = [_serialize_list_row(r) for r in rows]
    page_total = int(math.ceil(total / page_size)) if total else 0
    return {
        "t_data": t_data,
        "total": total,
        "page_total": page_total,
    }


async def get_distribution_order_detail(
    session: AsyncSession, order_id: int,
) -> Dict[str, Any]:
    order = await _load_order(session, order_id)
    snap = await _load_snapshot(session, order_id)
    data = _serialize_detail(order, snap)
    data["quote_details"] = await list_line_details(
        session, order_id, "quote",
    )
    data["order_details"] = await list_line_details(
        session, order_id, "order",
    )

    from apps.system.distribution_order.distribution_order_fulfillment_service import (
        build_fulfillment_detail,
    )
    from apps.system.distribution_order.distribution_order_workflow_engine import (
        load_order_workflow_bundle, load_quote_workflow_bundle,
    )
    data.update(await build_fulfillment_detail(
        session, order_id, order=order, order_lines=data["order_details"],
    ))
    try:
        data["quote_approval_flow"] = await load_quote_workflow_bundle(
            session, order_id,
        )
    except ValueError:
        data["quote_approval_flow"] = None
    try:
        data["order_approval_flow"] = await load_order_workflow_bundle(
            session, order_id,
        )
    except ValueError:
        data["order_approval_flow"] = None
    return data


async def save_distribution_order_draft(
    session: AsyncSession,
    body: DistributionOrderDraftIn,
    *,
    operator_id: Optional[int] = None,
    filter_value: Optional[List[Dict[str, Any]]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
    exchange_rate_dict: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Optional[str]]:
    if body.id:
        order_id, order_sn = await _update_draft(
            session, body, operator_id=operator_id,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
            exchange_rate_dict=exchange_rate_dict,
        )
        return order_id, order_sn
    order_id, order_sn = await _create_draft(
        session, body, operator_id=operator_id,
        filter_value=filter_value,
        is_trans=is_trans,
        translation_dict=translation_dict,
        exchange_rate_dict=exchange_rate_dict,
    )
    return order_id, order_sn


async def save_distribution_order_create(
    session: AsyncSession,
    body: DistributionOrderCreateIn,
    *,
    operator_id: Optional[int] = None,
    filter_value: Optional[List[Dict[str, Any]]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
    exchange_rate_dict: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Optional[str]]:
    """订单创建阶段保存主表字段与订单明细（JSON 附件经 NormalizedJSON 落库）。"""
    order = await _load_order(session, body.id)
    if int(order.status) not in EDITABLE_ORDER_DETAIL_STATUSES:
        raise DistributionOrderError(40000, "当前状态不允许保存订单")

    data = body.dict(exclude_unset=True)
    for key, val in data.items():
        if key in _ORDER_CREATE_SKIP_KEYS:
            continue
        if key == "order_lm_user_id":
            val = normalize_line_manager_user_id(val)
        if hasattr(order, key):
            setattr(order, key, val)
    order.update_by = operator_id

    if "order_details" in body.__fields_set__:
        await save_line_details(
            session,
            int(order._id),
            "order",
            body.order_details,
            check_status=False,
            replace_all=True,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
        await _recalc_order_amounts_after_order_detail_save(session, order)
    await refresh_order_tags(
        session, int(order._id), order=order,
        exchange_rate_dict=exchange_rate_dict,
    )
    await session.flush()
    return int(order._id), order.order_sn


async def void_distribution_order(
    session: AsyncSession,
    body: VoidIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    """草稿/订单创建 → 已作废。"""
    try:
        _, meta, message = await void_order(
            session,
            order_id=int(body.order_id),
            operator_id=operator_id,
            operator_role=OPERATOR_CREATOR,
            remark=(body.remark or "").strip() or None,
            trigger_type=TRIGGER_MANUAL,
        )
    except ValueError as e:
        raise DistributionOrderError(40000, str(e))
    return {
        "order_id": int(body.order_id),
        "from_status": int(meta["from_status"]),
        "to_status": int(meta["to_status"]),
        "void_from_status": int(meta["from_status"]),
        "message": message,
    }


async def save_distribution_order_remark(
    session: AsyncSession,
    body: RemarkSaveIn,
    *,
    operator_id: Optional[int] = None,
) -> int:
    """单独修改订单备注，不限主状态（已作废不可改）。"""
    order = await _load_order(session, body.order_id)
    # if int(order.status) == STATUS_VOIDED:
    #     raise DistributionOrderError(40000, "已作废订单不可修改备注")
    order.remark = body.remark
    order.update_by = operator_id
    await session.flush()
    return int(order._id)


def resolve_order_approval_chain_code(
    order: DistributionOrder,
    chain_code: Optional[int] = None,
    *,
    exchange_rate_dict: Optional[Dict[str, Any]] = None,
) -> int:
    """订单提交审核：chain 2 标准 / 3 大额（按含税订单总额 USD）。"""
    if chain_code is not None:
        code = int(chain_code)
        if code not in ORDER_CHAIN_CODES:
            raise DistributionOrderError(40001, "chain_code 须为 2 或 3")
        return code
    customer_country = order.customer_country
    amount_usd = order_amount_usd(order, exchange_rate_dict)
    if amount_usd is None:
        raise DistributionOrderError(40000, "订单金额未计算，请先保存订单明细")
    if amount_usd >= LARGE_AMOUNT_USD_THRESHOLD and customer_country == "TH":
        return CHAIN_ORDER_TH_LARGE
    elif amount_usd >= LARGE_AMOUNT_USD_THRESHOLD:
        return CHAIN_ORDER_LARGE
    return CHAIN_ORDER_STANDARD


async def submit_distribution_order(
    session: AsyncSession,
    body: OrderSubmitIn,
    *,
    operator_id: Optional[int] = None,
    exchange_rate_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """订单创建(30) → 提交订单审核(40)。"""
    order = await _load_order(session, body.order_id)
    if int(order.status) != STATUS_ORDER_CREATE:
        raise DistributionOrderError(40000, "当前状态不允许提交订单审核")

    item_rows = await _load_alive_lines(
        session, int(order._id), DistributionOrderItemDetail,
    )
    if not item_rows:
        raise DistributionOrderError(40000, "订单明细不能为空")
    if int(getattr(order, "create_source", 0) or 0) == CREATE_SOURCE_BATCH_DROPSHIP:
        await _recalc_order_amounts_after_order_detail_save(session, order)
    else:
        allocate_freight_to_order_lines(order, item_rows)

    chain_code = resolve_order_approval_chain_code(
        order, body.chain_code, exchange_rate_dict=exchange_rate_dict,
    )
    country = order.customer_country
    if not country:
        raise DistributionOrderError(40000, "客户国家未配置，无法提交审核")
    try:
        await assert_chain_has_approvers(
            session, country, chain_code, order,
        )
    except ValueError as exc:
        raise DistributionOrderError(40000, str(exc)) from exc

    if getattr(body, "__fields_set__", None) and "order_lm_user_id" in body.__fields_set__:
        order.order_lm_user_id = normalize_line_manager_user_id(body.order_lm_user_id)
    order.update_by = operator_id

    from_status = int(order.status)
    try:
        _, meta, _msg = await apply_transition(
            session,
            order_id=int(body.order_id),
            action=ACTION_ORDER_SUBMIT,
            operator_id=operator_id,
            operator_role=OPERATOR_CREATOR,
            trigger_type=TRIGGER_MANUAL,
            chain_code=chain_code,
        )
    except ValueError as exc:
        raise DistributionOrderError(40000, str(exc)) from exc
    except RuntimeError as exc:
        raise DistributionOrderError(40000, str(exc)) from exc

    await refresh_order_tags(
        session, int(order._id), order=order,
        exchange_rate_dict=exchange_rate_dict,
    )
    return {
        "order_id": int(body.order_id),
        "from_status": from_status,
        "to_status": int(meta["to_status"]),
        "current_chain_code": meta.get("current_chain_code"),
        "current_step": meta.get("current_step"),
        "chain_code": chain_code,
        "total_steps": meta.get("total_steps"),
        "message": meta.get("message") or "已提交，待审批",
    }


# ── 内部：查询 ───────────────────────────────────────────────────────────────


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


async def _load_snapshot(
    session: AsyncSession, order_id: int,
) -> Optional[DistributionOrderSnapshot]:
    return (
        await session.execute(
            select(DistributionOrderSnapshot).where(
                DistributionOrderSnapshot.order_id == order_id,
            )
        )
    ).scalar_one_or_none()


def _copy_orm_columns(
    dest: Any,
    src: Any,
    *,
    skip: Set[str],
) -> None:
    """按 ORM 列复制；JSON 列走 normalize_json_column。"""
    mapper = inspect(src.__class__)
    for attr in mapper.mapper.column_attrs:
        key = attr.key
        if key in skip:
            continue
        val = getattr(src, key)
        if key in _JSON_COLUMN_NAMES:
            val = normalize_json_column(val)
        setattr(dest, key, val)


def _copy_order_json_fields_from_parent(
    child: DistributionOrder,
    parent: DistributionOrder,
) -> None:
    """拆单复制附件 JSON：有值才 setattr；无值则不写入列（避免 JSON 列落成字符串/null）。"""
    for key in _ORDER_JSON_KEYS:
        val = normalize_json_column(getattr(parent, key, None))
        if val is not None:
            setattr(child, key, val)
        elif key in child.__dict__:
            del child.__dict__[key]


def clone_order_for_split(
    parent: DistributionOrder,
    *,
    order_sn: str,
    parent_order_id: int,
    operator_id: Optional[int],
) -> DistributionOrder:
    """拆单子单：复制父单主表全部业务列，仅覆盖单号/父单/审计字段。"""
    skip = set(_ORDER_SPLIT_SKIP_COLS) | set(_ORDER_JSON_KEYS)
    child = DistributionOrder()
    _copy_orm_columns(child, parent, skip=skip)
    _copy_order_json_fields_from_parent(child, parent)
    child.order_sn = order_sn
    child.parent_order_id = parent_order_id
    child.create_by = operator_id
    child.update_by = operator_id
    return child


def clone_snapshot_for_split(
    parent_snap: DistributionOrderSnapshot,
    child_order_id: int,
) -> DistributionOrderSnapshot:
    """拆单子单：复制父单 1:1 扩展快照。"""
    child_snap = DistributionOrderSnapshot(order_id=child_order_id)
    _copy_orm_columns(child_snap, parent_snap, skip=_SNAPSHOT_SPLIT_SKIP_COLS)
    return child_snap


def _order_json_clear_flags(parent: DistributionOrder) -> tuple:
    """返回 (是否清空采购单附件, 是否清空发货指导附件)。"""
    clear_po = (
        normalize_json_column(getattr(parent, "customer_po_attachments", None)) is None
    )
    clear_ship = (
        normalize_json_column(getattr(parent, "ship_guide_attachments", None)) is None
    )
    return clear_po, clear_ship


async def ensure_sql_null_order_json_attachments(
    session: AsyncSession,
    order_id: int,
    *,
    clear_po: bool,
    clear_ship: bool,
) -> None:
    """MySQL JSON 列：ORM 的 None 常落成 JSON null(IS NULL=0)；强制 SQL NULL。"""
    sets = []
    if clear_po:
        sets.append("customer_po_attachments = NULL")
    if clear_ship:
        sets.append("ship_guide_attachments = NULL")
    if not sets:
        return
    await session.execute(
        text(
            "UPDATE internal_app.data_distribution_order SET "
            + ", ".join(sets)
            + " WHERE _id = :oid"
        ),
        {"oid": int(order_id)},
    )


def _align_order_json_in_memory(
    order: DistributionOrder,
    *,
    clear_po: bool,
    clear_ship: bool,
) -> None:
    """SQL NULL 已落库后同步 ORM 状态，避免 expire 触发异步懒加载。"""
    if clear_po:
        orm_attributes.set_committed_value(
            order, "customer_po_attachments", None,
        )
    if clear_ship:
        orm_attributes.set_committed_value(
            order, "ship_guide_attachments", None,
        )


async def ensure_sql_null_order_json_from_parent(
    session: AsyncSession,
    order_id: int,
    parent: DistributionOrder,
    *,
    order: Optional[DistributionOrder] = None,
) -> None:
    clear_po, clear_ship = _order_json_clear_flags(parent)
    await ensure_sql_null_order_json_attachments(
        session, order_id, clear_po=clear_po, clear_ship=clear_ship,
    )
    if order is not None:
        _align_order_json_in_memory(
            order, clear_po=clear_po, clear_ship=clear_ship,
        )


async def sanitize_order_json_columns(
    session: AsyncSession,
    order: DistributionOrder,
) -> None:
    """修正主表 JSON 附件：有值规范化；无值强制 SQL NULL（非 JSON null）。"""
    clear_po, clear_ship = _order_json_clear_flags(order)
    if clear_po or clear_ship:
        await ensure_sql_null_order_json_attachments(
            session,
            int(order._id),
            clear_po=clear_po,
            clear_ship=clear_ship,
        )
        _align_order_json_in_memory(
            order, clear_po=clear_po, clear_ship=clear_ship,
        )
        return
    for key in _ORDER_JSON_KEYS:
        normalized = normalize_json_column(getattr(order, key, None))
        if getattr(order, key, None) != normalized:
            setattr(order, key, normalized)
            flag_modified(order, key)


# ── 内部：草稿保存 ───────────────────────────────────────────────────────────


async def _create_draft(
    session: AsyncSession,
    body: DistributionOrderDraftIn,
    *,
    operator_id: Optional[int],
    filter_value: Optional[List[Dict[str, Any]]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
    exchange_rate_dict: Optional[Dict[str, Any]] = None,
) -> int:
    if not body.offline_customer_id:
        raise DistributionOrderError(40001, "请选择线下客户")
    country = (body.customer_country or "").strip()
    if not country:
        cust = await _load_customer(session, body.offline_customer_id)
        country = (cust.customer_country or "").strip()
    if not country:
        raise DistributionOrderError(40001, "客户国家为空，无法生成单号")
    order_sn = await _allocate_order_sn(session, country)
    order = DistributionOrder(
        order_sn=order_sn,
        status=STATUS_DRAFT,
        offline_customer_id=body.offline_customer_id,
        create_by=operator_id,
        update_by=operator_id,
    )
    session.add(order)
    await session.flush()
    _apply_main_fields(order, body)
    snap = DistributionOrderSnapshot(order_id=order._id)
    session.add(snap)
    _apply_snapshot_fields(snap, body)
    if "quote_details" in body.__fields_set__:
        await save_line_details(
            session, order._id, "quote", body.quote_details,
            check_status=False,
            replace_all=True,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
    await refresh_order_tags(
        session, int(order._id), order=order,
        exchange_rate_dict=exchange_rate_dict,
    )
    await session.flush()
    return int(order._id), order.order_sn


async def _update_draft(
    session: AsyncSession,
    body: DistributionOrderDraftIn,
    *,
    operator_id: Optional[int],
    filter_value: Optional[List[Dict[str, Any]]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
    exchange_rate_dict: Optional[Dict[str, Any]] = None,
) -> int:
    order = await _load_order(session, body.id)
    if order.status not in EDITABLE_DRAFT_STATUSES:
        raise DistributionOrderError(
            40000, "当前状态不允许保存草稿",
        )
    _apply_main_fields(order, body)
    order.update_by = operator_id
    snap = await _load_snapshot(session, order._id)
    if snap is None:
        snap = DistributionOrderSnapshot(order_id=order._id)
        session.add(snap)
    _apply_snapshot_fields(snap, body)
    if "quote_details" in body.__fields_set__:
        await save_line_details(
            session, order._id, "quote", body.quote_details,
            check_status=False,
            replace_all=True,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
    await refresh_order_tags(
        session, int(order._id), order=order,
        exchange_rate_dict=exchange_rate_dict,
    )
    await session.flush()
    return int(order._id), order.order_sn


async def _load_customer(
    session: AsyncSession, customer_id: int,
) -> OfflineCustomer:
    row = (
        await session.execute(
            select(OfflineCustomer).where(OfflineCustomer._id == customer_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise DistributionOrderError(40400, "线下客户不存在")
    return row


async def _allocate_order_sn(
    session: AsyncSession, customer_country: str,
) -> str:
    """暂用随机后缀；日序列表方案后续由业务方接入。"""
    prefix = "B2B{}{}".format(
        customer_country, datetime.date.today().strftime("%Y%m%d"),
    )
    sequence = await SequenceService.next(session, type="B2B", sub_type=f"{prefix}_{customer_country}")
    if sequence:
        sn = prefix + str(sequence)
        return sn
    raise DistributionOrderError(40000, "生成单号失败，请重试")


async def _allocate_batch_id(session: AsyncSession) -> str:
    """Batch ID：Bat + B2B + 日期 + 四位自增序号。"""
    day = datetime.date.today().strftime("%Y%m%d")
    prefix = "BatB2B{}".format(day)
    sequence = await SequenceService.next(
        session, type="B2BBATCH", sub_type=prefix,
    )
    if sequence:
        return prefix + str(int(sequence)).zfill(4)
    raise DistributionOrderError(40000, "生成 Batch ID 失败，请重试")


def _apply_main_fields(
    order: DistributionOrder, body: DistributionOrderDraftIn,
) -> None:
    data = body.dict(exclude_unset=True)
    for key in _MAIN_BODY_KEYS:
        if key not in data:
            continue
        val = data[key]
        if key in ("is_prepayment", "is_tax_free", "is_ewt") and val is not None:
            val = int(val)
        setattr(order, key, val)


def _apply_snapshot_fields(
    snap: DistributionOrderSnapshot, body: DistributionOrderDraftIn,
) -> None:
    data = body.dict(exclude_unset=True)
    for key in _SNAPSHOT_KEYS:
        if key in data:
            setattr(snap, key, data[key])


# ── 内部：序列化（复用 schemas 读出模型，避免与 ORM 双份字段列表）──────────


def _orm_out_dict(model_cls: Type[_TSchema], row: Any) -> Dict[str, Any]:
    return model_cls.from_orm(row).dict(by_alias=True)


def _serialize_list_row(order: DistributionOrder) -> Dict[str, Any]:
    data = _orm_out_dict(DistributionOrderOut, order)
    st = int(order.status)
    data["status_str"] = status_str(st)
    void_from = order.void_from_status
    data["void_from_status"] = void_from
    data["void_from_status_str"] = (
        status_str(int(void_from)) if void_from is not None else ""
    )
    data["button_list"] = list(STATUS_BUTTON_LIST.get(st, []))
    data["tags_bitmask"] = order.tags_bitmask
    data["create_source_str"] = create_source_str(order.create_source)
    data["cooperation_method_str"] = cooperation_method_str(order.cooperation_method)
    attach_tags_display(data)
    return data


def _serialize_detail(
    order: DistributionOrder,
    snap: Optional[DistributionOrderSnapshot],
) -> Dict[str, Any]:
    data = _serialize_list_row(order)
    if snap is not None:
        data.update(_orm_out_dict(DistributionOrderSnapshotOut, snap))
    else:
        for key in _SNAPSHOT_KEYS:
            data[key] = None
    return data
