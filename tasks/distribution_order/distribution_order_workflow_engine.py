# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/25
# @Author  : Zhu Yaming
# @File    : distribution_order_workflow_engine.py
# @Description : 分销订单审批流引擎，报价链与订单链独立
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, asc, exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.system.distribution_order.models import (
    DistributionOrder,
    DistributionOrderApprovalConfig,
    DistributionOrderStatusLog,
)

logger = logging.getLogger(__name__)

# ── 主状态 ───────────────────────────────────────────────────────────────────
STATUS_DRAFT = 10
STATUS_QUOTE_REVIEW = 20
STATUS_ORDER_CREATE = 30
STATUS_ORDER_REVIEW = 40
STATUS_PREPAY = 50
STATUS_PENDING_DISPATCH = 60
STATUS_FULFILLING = 70
STATUS_PENDING_PAYMENT = 80
STATUS_COMPLETED = 90
STATUS_VOIDED = 99

# ── 审批链 ───────────────────────────────────────────────────────────────────
CHAIN_PRICING = 1  # 定价审批
CHAIN_ORDER_STANDARD = 2  # 订单审批-标准
CHAIN_ORDER_TH_LARGE = 3
CHAIN_ORDER_LARGE = 4  # 订单审批-大额
ORDER_CHAIN_CODES = (CHAIN_ORDER_STANDARD, CHAIN_ORDER_TH_LARGE, CHAIN_ORDER_LARGE)

# ── 动作码（design 附录 A.1，审批相关）────────────────────────────────────────
ACTION_QUOTE_SUBMIT = 10
ACTION_QUOTE_APPROVE = 11
ACTION_QUOTE_REJECT = 12
ACTION_QUOTE_WITHDRAW = 13
ACTION_QUOTE_AUTO_PASS = 14
ACTION_ORDER_SUBMIT = 20
ACTION_ORDER_APPROVE = 21
ACTION_ORDER_REJECT = 22
ACTION_ORDER_WITHDRAW = 23
ACTION_ORDER_AUTO_PASS = 24
ACTION_PREPAY_CONFIRM = 30
ACTION_DISPATCH = 40
ACTION_RECEIVE_CONFIRM = 50
ACTION_PAYMENT_CONFIRM = 60
ACTION_VOID = 90

QUOTE_ACTIONS = (
    ACTION_QUOTE_SUBMIT,
    ACTION_QUOTE_APPROVE,
    ACTION_QUOTE_REJECT,
    ACTION_QUOTE_WITHDRAW,
)
ORDER_ACTIONS = (
    ACTION_ORDER_SUBMIT,
    ACTION_ORDER_APPROVE,
    ACTION_ORDER_REJECT,
    ACTION_ORDER_WITHDRAW,
)
FULFILLMENT_ACTIONS = (
    ACTION_PREPAY_CONFIRM,
    ACTION_DISPATCH,
    ACTION_RECEIVE_CONFIRM,
    ACTION_PAYMENT_CONFIRM,
)

PHASE_QUOTE = "quote"
PHASE_ORDER = "order"
PHASE_FULFILLMENT = "fulfillment"

# 审批流展示：审核类型（报价单审核 / 订单审核）
APPROVAL_TYPE_STR = {
    PHASE_QUOTE: "报价单审核",
    PHASE_ORDER: "订单审核",
}

# ── trigger_type / operator_role（附录 A.2/A.3）──────────────────────────────
TRIGGER_MANUAL = 1
TRIGGER_APPROVAL = 3

OPERATOR_CREATOR = 1
OPERATOR_APPROVER = 2
OPERATOR_ADMIN = 3
OPERATOR_SYSTEM = 4

APPROVER_TYPE_LINE_MANAGER = 1
APPROVER_TYPE_ROLE = 2

STATUS_STR = {
    10: "草稿",
    20: "报价审核",
    30: "订单创建",
    40: "订单审核",
    50: "确认预付",
    60: "待下发",
    70: "履约中",
    80: "待回款",
    90: "已完成",
    99: "已作废",
}
ACTION_STR = {
    10: "提交报价审核",
    11: "报价审核通过",
    12: "报价审核驳回",
    13: "撤回报价审核",
    14: "自动通过",
    20: "提交订单审核",
    21: "订单审核通过",
    22: "订单审核驳回",
    23: "撤回订单审核",
    24: "自动通过",
    30: "确认预付",
    40: "下发千易",
    50: "确认实收",
    60: "确认回款",
    90: "作废",
}
OPERATOR_ROLE_STR = {
    1: "发起人",
    2: "审核人",
    3: "管理员",
    4: "系统",
}


def phase_for_action(action: int) -> str:
    if action in QUOTE_ACTIONS:
        return PHASE_QUOTE
    if action in ORDER_ACTIONS:
        return PHASE_ORDER
    if action in FULFILLMENT_ACTIONS:
        return PHASE_FULFILLMENT
    raise ValueError("非审批动作码: %s" % action)


def _assert_transition(from_status: int, action: int) -> None:
    phase = phase_for_action(action)
    if phase == PHASE_QUOTE:
        allowed = {
            STATUS_DRAFT: {ACTION_QUOTE_SUBMIT},
            STATUS_QUOTE_REVIEW: {
                ACTION_QUOTE_APPROVE,
                ACTION_QUOTE_REJECT,
                ACTION_QUOTE_WITHDRAW,
            },
        }
    elif phase == PHASE_ORDER:
        allowed = {
            STATUS_ORDER_CREATE: {ACTION_ORDER_SUBMIT},
            STATUS_ORDER_REVIEW: {
                ACTION_ORDER_APPROVE,
                ACTION_ORDER_REJECT,
                ACTION_ORDER_WITHDRAW,
            },
        }
    else:
        allowed = {
            STATUS_PREPAY: {ACTION_PREPAY_CONFIRM},
            STATUS_PENDING_DISPATCH: {ACTION_DISPATCH},
            STATUS_FULFILLING: {ACTION_RECEIVE_CONFIRM},
            STATUS_PENDING_PAYMENT: {ACTION_PAYMENT_CONFIRM},
        }
    if action not in allowed.get(from_status, set()):
        raise ValueError(
            "当前状态「%s」不允许执行「%s」"
            % (STATUS_STR.get(from_status, from_status), ACTION_STR.get(action, action))
        )


async def _load_order(session: AsyncSession, order_id: int) -> DistributionOrder:
    order = (
        await session.execute(
            select(DistributionOrder).where(
                DistributionOrder._id == order_id,
                DistributionOrder.is_delete == 0,
            )
        )
    ).scalar_one_or_none()
    if not order:
        raise ValueError("订单 %s 不存在" % order_id)
    return order


async def _load_approval_steps(
    session: AsyncSession, chain_code: Optional[int],
) -> List[DistributionOrderApprovalConfig]:
    if chain_code is None:
        raise ValueError("审批链 chain_code 不能为空")
    rows = (
        await session.execute(
            select(DistributionOrderApprovalConfig)
            .where(
                DistributionOrderApprovalConfig.chain_code == chain_code,
                DistributionOrderApprovalConfig.is_active == 1,
            )
            .order_by(asc(DistributionOrderApprovalConfig.step_no))
        )
    ).scalars().all()
    if not rows:
        raise RuntimeError("未配置审批链 chain_code=%s" % chain_code)
    return rows


async def get_customer_country(session: AsyncSession, offline_customer_id: int) -> Optional[str]:
    """客户国家（办事角色权限过滤用）。"""
    try:
        from apps.system.offline_customer.models import OfflineCustomer
    except ImportError:
        logger.warning("OfflineCustomer 模型不可用，无法解析国家")
        return None
    return (
        await session.execute(
            select(OfflineCustomer.customer_country).where(
                OfflineCustomer._id == offline_customer_id
            )
        )
    ).scalar_one_or_none()


async def _get_country_chain_role_steps(
    session: AsyncSession, country: str, chain_code: int,
) -> List[Tuple[int, int]]:
    """该国该审批链是否已配置办事角色（提交前校验）。"""
    sql = text(
        """
        SELECT bs.role_id AS role_id, dac.step_no AS step_no
        FROM internal_app.user_business_role_permission yrp
        INNER JOIN internal_app.business_role_config bsc ON bsc.id = yrp.role_config_id
        INNER JOIN internal_app.business_role bs ON bsc.role_id = bs.role_id
        INNER JOIN internal_app.data_distribution_order_approval_config dac
            ON dac.role_id = bs.role_id
        WHERE bsc.config_key = 'customer_nation'
          AND yrp.value = :country
          AND dac.chain_code = :chain_code
          AND dac.is_active = 1
          AND bsc.invalid_ind = 0
          AND bs.invalid_ind = 0
          AND yrp.invalid_ind = 0
        """
    )
    result = await session.execute(
        sql, {"country": country, "chain_code": chain_code},
    )
    return [(row.role_id, row.step_no) for row in result]


async def _get_user_valid_role_step(
    session: AsyncSession,
    user_id: int,
    country: str,
    chain_code: int,
    current_step: int,
) -> List[Tuple[int, int]]:
    """当前用户在该国、该链、该环节是否具备审批办事角色。"""
    sql = text(
        """
        SELECT bs.role_id AS role_id, dac.step_no AS step_no
        FROM internal_app.user_business_role_permission yrp
        INNER JOIN internal_app.business_role_config bsc ON bsc.id = yrp.role_config_id
        INNER JOIN internal_app.business_role bs ON bsc.role_id = bs.role_id
        INNER JOIN internal_app.data_distribution_order_approval_config dac
            ON dac.role_id = bs.role_id
        WHERE yrp.user_id = :user_id
          AND bsc.config_key = 'customer_nation'
          AND yrp.value = :country
          AND dac.chain_code = :chain_code
          AND dac.step_no = :current_step
          AND dac.is_active = 1
          AND bsc.invalid_ind = 0
          AND bs.invalid_ind = 0
          AND yrp.invalid_ind = 0
        """
    )
    result = await session.execute(
        sql,
        {
            "user_id": user_id,
            "country": country,
            "chain_code": chain_code,
            "current_step": current_step,
        },
    )
    return [(row.role_id, row.step_no) for row in result]


def normalize_line_manager_user_id(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        uid = int(val)
    except (TypeError, ValueError):
        return None
    return uid if uid > 0 else None


def line_manager_user_id_for_chain(
    order: DistributionOrder, chain_code: int,
) -> Optional[int]:
    """定价链用 quote_lm_user_id；订单链用 order_lm_user_id。"""
    if int(chain_code) == CHAIN_PRICING:
        return normalize_line_manager_user_id(
            order.quote_lm_user_id,
        )
    return normalize_line_manager_user_id(
        order.order_lm_user_id,
    )


def submitter_user_id(order: DistributionOrder) -> Optional[int]:
    """当前轮次提交审核发起人（submit 时写入 submit_by）。"""
    return normalize_line_manager_user_id(getattr(order, "submit_by", None))


def initiator_acted_user_ids(order: DistributionOrder) -> Set[int]:
    """create_by，仅用于提交前 next_steps 预览。"""
    uid = normalize_line_manager_user_id(order.create_by)
    return {int(uid)} if uid else set()


def chain_skip_acted_base_user_ids(order: DistributionOrder) -> Set[int]:
    """本轮已执行 submit 的用户（同人跳过：提交算一次操作）。"""
    submitter = submitter_user_id(order)
    return {int(submitter)} if submitter else set()


def _add_operated_user_id(acted: Set[int], user_id: Optional[int]) -> None:
    uid = normalize_line_manager_user_id(user_id)
    if uid is not None:
        acted.add(int(uid))


def _pick_skip_operator_id(
    overlap: Set[int], trigger_operator_id: Optional[int] = None,
) -> int:
    """同人跳过：优先取本次操作人，否则取交集中最小 user_id。"""
    if trigger_operator_id is not None:
        tid = normalize_line_manager_user_id(trigger_operator_id)
        if tid is not None and tid in overlap:
            return int(tid)
    return int(min(overlap))


def _try_apply_step_skip(
    acted: Set[int],
    approver_ids: Set[int],
    *,
    trigger_operator_id: Optional[int] = None,
) -> Optional[int]:
    """
    已操作人 ∩ 环节审批人 → 自动跳过，仅触发人计入 acted。
    返回触发跳过的 user_id；无需跳过时返回 None。
    """
    if not approver_ids:
        return None
    overlap = acted & approver_ids
    if not overlap:
        return None
    skip_uid = _pick_skip_operator_id(overlap, trigger_operator_id)
    acted.add(skip_uid)
    return skip_uid


ROLE_STEP_APPROVER_USER_IDS_SQL = text(
    """
    SELECT DISTINCT yrp.user_id AS user_id
    FROM internal_app.user_business_role_permission yrp
    INNER JOIN internal_app.business_role_config bsc ON bsc.id = yrp.role_config_id
    INNER JOIN internal_app.business_role bs ON bsc.role_id = bs.role_id
    INNER JOIN internal_app.data_distribution_order_approval_config dac
        ON dac.role_id = bs.role_id
    WHERE bsc.config_key = 'customer_nation'
      AND yrp.value = :country
      AND dac.chain_code = :chain_code
      AND dac.step_no = :step_no
      AND dac.is_active = 1
      AND bsc.invalid_ind = 0
      AND bs.invalid_ind = 0
      AND yrp.invalid_ind = 0
    """
)


async def get_step_approver_user_ids(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    step: DistributionOrderApprovalConfig,
    *,
    country: Optional[str] = None,
) -> Set[int]:
    """解析单环节全部可审批人 user_id（直线上级 or 办事角色）。"""
    if int(step.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
        mgr_id = line_manager_user_id_for_chain(order, chain_code)
        return {int(mgr_id)} if mgr_id else set()
    step_no = int(step.step_no or 0)
    ids = await get_role_step_approver_user_ids(
        session, order, chain_code, step_no, country=country,
    )
    return set(ids)


async def resolve_current_executor_user_ids(
    session: AsyncSession,
    order: DistributionOrder,
) -> List[int]:
    """
    当前执行人 user_id 列表（与列表展示 / 筛选口径一致）。
    - 草稿/订单创建：create_by
    - 报价/订单审核：当前环节审批人（引擎 get_step_approver_user_ids）
    - 其余状态：空
    """
    status = int(order.status or 0)
    if status in (STATUS_DRAFT, STATUS_ORDER_CREATE):
        uid = normalize_line_manager_user_id(getattr(order, "create_by", None))
        return [uid] if uid else []
    if status not in (STATUS_QUOTE_REVIEW, STATUS_ORDER_REVIEW):
        return []
    chain_code = int(order.current_chain_code or 0)
    step_no = int(order.current_step or 0)
    if chain_code <= 0 or step_no <= 0:
        return []
    steps = await _load_approval_steps(session, chain_code)
    step = _find_approval_step_by_no(steps, step_no)
    if step is None:
        return []
    if not should_include_approval_step(order, step, chain_code):
        return []
    ids = await get_step_approver_user_ids(
        session, order, chain_code, step,
        country=(order.customer_country or "").strip() or None,
    )
    return sorted(int(x) for x in ids if int(x) > 0)


def _clean_executor_display_name(name: Optional[str]) -> Optional[str]:
    """过滤空串及历史占位 Unknow/Unknown。"""
    if name is None:
        return None
    text = str(name).strip()
    if not text:
        return None
    if text.lower() in ("unknow", "unknown", "none", "null"):
        return None
    return text


async def resolve_current_executor_display_name(
    session: AsyncSession,
    order: DistributionOrder,
    *,
    user_dict: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    当前执行人展示名（与 resolve_current_executor_user_ids 口径一致）。
    审核中优先走引擎环节展示名（直线上级 / 角色 GROUP_CONCAT），避免 user_dict 缺人出 Unknow。
    """
    status = int(order.status or 0)
    if status in (STATUS_DRAFT, STATUS_ORDER_CREATE):
        uid = normalize_line_manager_user_id(getattr(order, "create_by", None))
        if not uid:
            return None
        name = None
        if user_dict:
            name = user_dict.get(str(uid)) or user_dict.get(uid)
        name = _clean_executor_display_name(name)
        if not name:
            name = _clean_executor_display_name(
                await _resolve_operator_name(session, uid)
            )
        return name
    if status not in (STATUS_QUOTE_REVIEW, STATUS_ORDER_REVIEW):
        return None
    chain_code = int(order.current_chain_code or 0)
    step_no = int(order.current_step or 0)
    if chain_code <= 0 or step_no <= 0:
        return None
    steps = await _load_approval_steps(session, chain_code)
    step = _find_approval_step_by_no(steps, step_no)
    if step is None or not should_include_approval_step(order, step, chain_code):
        return None
    country = (order.customer_country or "").strip()
    if not country:
        country = (await get_customer_country(session, order.offline_customer_id) or "").strip()
    if not country and int(step.approver_type or 0) != APPROVER_TYPE_LINE_MANAGER:
        return None
    name = await _resolve_step_operator_display_name(
        session, order, chain_code, step, country,
    )
    return _clean_executor_display_name(name)


def build_execute_user_list_filter(user_ids: List[int]):
    """
    列表「当前执行人」筛选条件（与 resolve_current_executor_user_ids 对齐）。
    未选人返回 None。
    """
    uids = sorted({
        int(x) for x in (user_ids or [])
        if x is not None and str(x).strip() != "" and int(x) > 0
    })
    if not uids:
        return None

    cfg = DistributionOrderApprovalConfig
    draft_or_create = and_(
        DistributionOrder.status.in_([STATUS_DRAFT, STATUS_ORDER_CREATE]),
        DistributionOrder.create_by.in_(uids),
    )
    lm_quote = and_(
        DistributionOrder.status == STATUS_QUOTE_REVIEW,
        DistributionOrder.quote_lm_user_id.in_(uids),
        DistributionOrder.current_step > 0,
        exists(
            select(cfg._id).where(
                cfg.chain_code == DistributionOrder.current_chain_code,
                cfg.step_no == DistributionOrder.current_step,
                cfg.is_active == 1,
                cfg.approver_type == APPROVER_TYPE_LINE_MANAGER,
            )
        ),
    )
    lm_order = and_(
        DistributionOrder.status == STATUS_ORDER_REVIEW,
        DistributionOrder.order_lm_user_id.in_(uids),
        DistributionOrder.current_step > 0,
        exists(
            select(cfg._id).where(
                cfg.chain_code == DistributionOrder.current_chain_code,
                cfg.step_no == DistributionOrder.current_step,
                cfg.is_active == 1,
                cfg.approver_type == APPROVER_TYPE_LINE_MANAGER,
            )
        ),
    )
    # 角色审批：与 ROLE_STEP_APPROVER_USER_IDS_SQL 同口径，关联主表当前链/步/国家
    uid_csv = ",".join(str(i) for i in uids)
    role_exists = text(
        """
        EXISTS (
          SELECT 1
          FROM internal_app.user_business_role_permission yrp
          INNER JOIN internal_app.business_role_config bsc
              ON bsc.id = yrp.role_config_id
          INNER JOIN internal_app.business_role bs ON bsc.role_id = bs.role_id
          INNER JOIN internal_app.data_distribution_order_approval_config dac
              ON dac.role_id = bs.role_id
          WHERE bsc.config_key = 'customer_nation'
            AND yrp.value = internal_app.data_distribution_order.customer_country
            AND dac.chain_code = internal_app.data_distribution_order.current_chain_code
            AND dac.step_no = internal_app.data_distribution_order.current_step
            AND dac.is_active = 1
            AND dac.approver_type = 2
            AND bsc.invalid_ind = 0
            AND bs.invalid_ind = 0
            AND yrp.invalid_ind = 0
            AND yrp.user_id IN (%s)
            AND internal_app.data_distribution_order.status IN (20, 40)
            AND internal_app.data_distribution_order.current_step > 0
        )
        """ % uid_csv
    )
    return or_(draft_or_create, lm_quote, lm_order, role_exists)


async def collect_related_execute_user_ids(session: AsyncSession) -> List[int]:
    """
    收集在途单（status<=40）上与「当前执行人」相关的全部 user_id，
    口径对齐 build_execute_user_list_filter / resolve_current_executor_user_ids。
    """
    cfg = DistributionOrderApprovalConfig
    uids: Set[int] = set()

    create_rows = (
        await session.execute(
            select(DistributionOrder.create_by).where(
                DistributionOrder.is_delete == 0,
                DistributionOrder.status.in_([STATUS_DRAFT, STATUS_ORDER_CREATE]),
                DistributionOrder.create_by.isnot(None),
                DistributionOrder.create_by > 0,
            ).distinct()
        )
    ).all()
    for (uid,) in create_rows:
        try:
            n = int(uid)
        except (TypeError, ValueError):
            continue
        if n > 0:
            uids.add(n)

    lm_quote_rows = (
        await session.execute(
            select(DistributionOrder.quote_lm_user_id).where(
                DistributionOrder.is_delete == 0,
                DistributionOrder.status == STATUS_QUOTE_REVIEW,
                DistributionOrder.current_step > 0,
                DistributionOrder.quote_lm_user_id.isnot(None),
                DistributionOrder.quote_lm_user_id > 0,
                exists(
                    select(cfg._id).where(
                        cfg.chain_code == DistributionOrder.current_chain_code,
                        cfg.step_no == DistributionOrder.current_step,
                        cfg.is_active == 1,
                        cfg.approver_type == APPROVER_TYPE_LINE_MANAGER,
                    )
                ),
            ).distinct()
        )
    ).all()
    for (uid,) in lm_quote_rows:
        try:
            n = int(uid)
        except (TypeError, ValueError):
            continue
        if n > 0:
            uids.add(n)

    lm_order_rows = (
        await session.execute(
            select(DistributionOrder.order_lm_user_id).where(
                DistributionOrder.is_delete == 0,
                DistributionOrder.status == STATUS_ORDER_REVIEW,
                DistributionOrder.current_step > 0,
                DistributionOrder.order_lm_user_id.isnot(None),
                DistributionOrder.order_lm_user_id > 0,
                exists(
                    select(cfg._id).where(
                        cfg.chain_code == DistributionOrder.current_chain_code,
                        cfg.step_no == DistributionOrder.current_step,
                        cfg.is_active == 1,
                        cfg.approver_type == APPROVER_TYPE_LINE_MANAGER,
                    )
                ),
            ).distinct()
        )
    ).all()
    for (uid,) in lm_order_rows:
        try:
            n = int(uid)
        except (TypeError, ValueError):
            continue
        if n > 0:
            uids.add(n)

    role_sql = text(
        """
        SELECT DISTINCT yrp.user_id AS user_id
        FROM internal_app.data_distribution_order o
        INNER JOIN internal_app.data_distribution_order_approval_config dac
            ON dac.chain_code = o.current_chain_code
           AND dac.step_no = o.current_step
           AND dac.is_active = 1
           AND dac.approver_type = 2
        INNER JOIN internal_app.business_role bs
            ON bs.role_id = dac.role_id AND bs.invalid_ind = 0
        INNER JOIN internal_app.business_role_config bsc
            ON bsc.role_id = bs.role_id
           AND bsc.invalid_ind = 0
           AND bsc.config_key = 'customer_nation'
        INNER JOIN internal_app.user_business_role_permission yrp
            ON yrp.role_config_id = bsc.id
           AND yrp.invalid_ind = 0
           AND yrp.value = o.customer_country
        WHERE o.is_delete = 0
          AND o.status IN (20, 40)
          AND o.current_step > 0
          AND yrp.user_id > 0
        """
    )
    role_rows = (await session.execute(role_sql)).all()
    for row in role_rows:
        try:
            n = int(row.user_id)
        except (TypeError, ValueError):
            continue
        if n > 0:
            uids.add(n)

    return sorted(uids)


async def list_execute_user_filter_options(
    session: AsyncSession,
    *,
    user_dict: Optional[Dict[str, Any]] = None,
    keyword: str = "",
) -> List[Dict[str, Any]]:
    """执行人筛选项：[{label, value}, ...]，可按姓名模糊。"""
    uids = await collect_related_execute_user_ids(session)
    kw = (keyword or "").strip().lower()
    options: List[Dict[str, Any]] = []
    td = user_dict or {}
    for uid in uids:
        name = None
        if td:
            name = td.get(str(uid)) or td.get(uid)
        name = _clean_executor_display_name(name)
        if not name:
            name = _clean_executor_display_name(
                await _resolve_operator_name(session, uid)
            )
        if not name:
            continue
        if kw and kw not in name.lower() and kw not in str(uid):
            continue
        options.append({"label": name, "value": int(uid)})
    options.sort(key=lambda item: (item["label"], item["value"]))
    return options


async def get_role_step_approver_user_ids(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    step_no: int,
    *,
    country: Optional[str] = None,
) -> List[int]:
    resolved_country = (country or order.customer_country or "").strip()
    if not resolved_country:
        resolved_country = (
            await get_customer_country(session, order.offline_customer_id) or ""
        ).strip()
    if not resolved_country:
        return []
    result = await session.execute(
        ROLE_STEP_APPROVER_USER_IDS_SQL,
        {
            "country": resolved_country,
            "chain_code": int(chain_code),
            "step_no": int(step_no),
        },
    )
    uids = []
    for row in result.all():
        try:
            n = int(row.user_id)
        except (TypeError, ValueError):
            continue
        if n > 0:
            uids.append(n)
    return uids


async def list_resolvable_step_nos(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    steps_raw: List[DistributionOrderApprovalConfig],
) -> List[int]:
    """需人工审批的有效环节（已配置审批人 / 直线上级已填）。"""
    country = await get_customer_country(session, order.offline_customer_id)
    nos: List[int] = []
    for step in sorted(steps_raw, key=lambda s: int(s.step_no or 0)):
        step_no = int(step.step_no or 0)
        if step_no <= 0:
            continue
        if not should_include_approval_step(order, step, chain_code):
            continue
        if int(step.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
            nos.append(step_no)
            continue
        if not country:
            continue
        approval_map = await get_approval_users(
            session, country, chain_code, int(step.role_id),
        )
        if not approval_map.get((step_no, country)):
            continue
        nos.append(step_no)
    return nos


def should_include_approval_step(
    order: DistributionOrder,
    step: DistributionOrderApprovalConfig,
    chain_code: int,
) -> bool:
    """办事角色=直线上级：仅当对应链已填直线上级 user_id 时保留该环节。"""
    if int(step.approver_type or 0) != APPROVER_TYPE_LINE_MANAGER:
        return True
    return line_manager_user_id_for_chain(order, chain_code) is not None


def effective_approval_steps(
    order: DistributionOrder,
    steps_raw: List[DistributionOrderApprovalConfig],
    chain_code: int,
) -> List[DistributionOrderApprovalConfig]:
    return [
        s for s in sorted(steps_raw, key=lambda x: int(x.step_no or 0))
        if int(s.step_no or 0) > 0
        and should_include_approval_step(order, s, chain_code)
    ]


def _find_approval_step_by_no(
    steps_raw: List[DistributionOrderApprovalConfig],
    step_no: int,
) -> Optional[DistributionOrderApprovalConfig]:
    for step in steps_raw:
        if int(step.step_no or 0) == int(step_no):
            return step
    return None


async def user_can_review_at_step(
    session: AsyncSession,
    order: DistributionOrder,
    user_id: int,
    *,
    country: Optional[str] = None,
    chain_code: Optional[int] = None,
    current_step: Optional[int] = None,
) -> bool:
    """
    当前环节是否可审批：直线上级=对应 lm_user_id；办事角色=该国+该 step 办事角色权限。
    """
    step_no = current_step if current_step is not None else order.current_step
    chain = chain_code if chain_code is not None else order.current_chain_code
    if step_no is None or chain is None:
        return False
    step_no = int(step_no)
    chain = int(chain)
    steps_raw = await _load_approval_steps(session, chain)
    cur_cfg = _find_approval_step_by_no(steps_raw, step_no)
    if cur_cfg is None:
        return False
    if not should_include_approval_step(order, cur_cfg, chain):
        return False
    if int(cur_cfg.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
        mgr_id = line_manager_user_id_for_chain(order, chain)
        if mgr_id is None:
            return False
        return int(user_id) == int(mgr_id)
    resolved_country = (country or order.customer_country or "").strip()
    if not resolved_country:
        resolved_country = (
            await get_customer_country(session, order.offline_customer_id) or ""
        ).strip()
    if not resolved_country:
        return False
    roles = await _get_user_valid_role_step(
        session, user_id, resolved_country, chain, step_no,
    )
    return bool(roles)


async def user_can_review_order(
    session: AsyncSession, order: DistributionOrder, user_id: int,
) -> bool:
    """是否可审批/驳回当前环节（读主表 current_step / current_chain_code）。"""
    if order.current_step is None or order.current_chain_code is None:
        return False
    country = order.customer_country
    if not country:
        country = await get_customer_country(session, order.offline_customer_id)
    return await user_can_review_at_step(
        session,
        order,
        user_id,
        country=country,
        chain_code=int(order.current_chain_code),
        current_step=int(order.current_step),
    )


async def assert_chain_has_approvers(
    session: AsyncSession,
    country: str,
    chain_code: int,
    order,
) -> None:
    """
    提交前校验：有效环节含办事角色时须已配置审批人；直线上级环节须已填对应 lm_user_id。
    """
    steps_raw = await _load_approval_steps(session, chain_code)
    resolvable = await list_resolvable_step_nos(
        session, order, chain_code, steps_raw,
    )
    if not resolvable:
        return
    need_role_approver = False
    for step in effective_approval_steps(order, steps_raw, chain_code):
        step_no = int(step.step_no or 0)
        if step_no not in resolvable:
            continue
        if int(step.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
            continue
        need_role_approver = True
        break
    if not need_role_approver:
        return
    roles = await _get_country_chain_role_steps(session, country, chain_code)
    if not roles:
        raise ValueError("请联系管理员配置订单对应审批人")


async def _list_active_steps_after(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    steps_raw: List[DistributionOrderApprovalConfig],
    after_step_no: int,
) -> List[Tuple[int, DistributionOrderApprovalConfig]]:
    """after_step_no 之后、可解析审批人的有效环节。"""
    country = await get_customer_country(session, order.offline_customer_id)
    result: List[Tuple[int, DistributionOrderApprovalConfig]] = []
    for step in sorted(steps_raw, key=lambda s: int(s.step_no or 0)):
        step_no = int(step.step_no or 0)
        if step_no <= int(after_step_no):
            continue
        if not should_include_approval_step(order, step, chain_code):
            continue
        if int(step.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
            result.append((step_no, step))
            continue
        if not country:
            continue
        approval_map = await get_approval_users(
            session, country, chain_code, int(step.role_id),
        )
        if not approval_map.get((step_no, country)):
            continue
        result.append((step_no, step))
    return result


async def collect_chain_acted_user_ids(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    phase: str,
) -> Set[int]:
    """
    本轮已操作用户（提交或通过），用于同人跳过。
    含提交人、各人工通过操作人、自动通过日志中的触发人。
    """
    submit_action = (
        ACTION_QUOTE_SUBMIT if phase == PHASE_QUOTE else ACTION_ORDER_SUBMIT
    )
    approve_actions = (
        ACTION_QUOTE_APPROVE, ACTION_ORDER_APPROVE,
    )
    auto_pass_actions = (
        ACTION_QUOTE_AUTO_PASS, ACTION_ORDER_AUTO_PASS,
    )
    if phase == PHASE_QUOTE:
        action_codes = QUOTE_ACTIONS + auto_pass_actions
    else:
        action_codes = ORDER_ACTIONS + auto_pass_actions

    logs = await _fetch_chain_logs(
        session, int(order._id), int(chain_code), action_codes,
    )
    round_start = -1
    for idx, log in enumerate(logs):
        if int(log.action_code or 0) == submit_action:
            round_start = idx
    if round_start < 0:
        return chain_skip_acted_base_user_ids(order)

    acted = chain_skip_acted_base_user_ids(order)
    _add_operated_user_id(acted, logs[round_start].operator_id)
    for log in logs[round_start + 1:]:
        action = int(log.action_code or 0)
        if action in approve_actions:
            _add_operated_user_id(acted, log.operator_id)
        elif action in auto_pass_actions and log.from_step is not None:
            _add_operated_user_id(acted, log.operator_id)
    return acted


async def _simulate_forward_step_states(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    steps_raw: List[DistributionOrderApprovalConfig],
    after_step_no: int,
    acted_user_ids: Set[int],
    *,
    trigger_operator_id: Optional[int] = None,
) -> Tuple[List[Tuple[int, int]], Optional[int]]:
    """
    从 after_step_no 向后模拟同人跳过。
    返回 (自动通过 [(step_no, skip_uid), ...], 下一待人工环节 step_no)。
    """
    acted = set(acted_user_ids)
    auto_pass_steps: List[Tuple[int, int]] = []
    steps_after = await _list_active_steps_after(
        session, order, chain_code, steps_raw, after_step_no,
    )
    for step_no, step in steps_after:
        approver_ids = await get_step_approver_user_ids(
            session, order, chain_code, step,
        )
        if not approver_ids:
            continue
        skip_uid = _try_apply_step_skip(
            acted, approver_ids, trigger_operator_id=trigger_operator_id,
        )
        if skip_uid is not None:
            auto_pass_steps.append((step_no, skip_uid))
            continue
        return auto_pass_steps, step_no
    return auto_pass_steps, None


async def resolve_forward_with_skip(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    steps_raw: List[DistributionOrderApprovalConfig],
    after_step_no: int,
    acted_user_ids: Set[int],
    *,
    trigger_operator_id: Optional[int] = None,
) -> Tuple[Optional[int], List[Tuple[int, int]]]:
    """
    从 after_step_no 向后模拟：已提交/已通过的用户出现在后续环节审批人中则自动跳过。
    仅将触发跳过的实际操作人计入 acted，不把整步审批人全部并入。
    返回 (下一待人工环节, [(被跳过 step_no, 触发跳过的 user_id), ...])。
    """
    auto_pass_steps, next_step = await _simulate_forward_step_states(
        session,
        order,
        chain_code,
        steps_raw,
        after_step_no,
        acted_user_ids,
        trigger_operator_id=trigger_operator_id,
    )
    return next_step, auto_pass_steps


def _finish_review_approval(
    order: DistributionOrder, phase: str,
) -> Tuple[int, str]:
    """审批链终审通过。"""
    order.current_chain_code = None
    order.current_step = None
    if phase == PHASE_QUOTE:
        order.status = STATUS_ORDER_CREATE
        return STATUS_ORDER_CREATE, "报价审核通过，进入订单创建"
    # 结算方式为带款提货时，无论是否有预付，订单审核通过后都推到确认预付状态，跳过确认回款状态
    if order.settlement_method == 1:
        order.status = STATUS_PREPAY
        order.prepay_todo_synced = 0
        return STATUS_PREPAY, "订单审核通过，进入确认预付"

    if int(order.is_prepayment or 0) == 1:
        order.status = STATUS_PREPAY
        order.prepay_todo_synced = 0
        return STATUS_PREPAY, "订单审核通过，进入确认预付"
    order.status = STATUS_PENDING_DISPATCH
    return STATUS_PENDING_DISPATCH, "订单审核通过，进入待下发"


async def _active_step_progress(
    session: AsyncSession,
    order: DistributionOrder,
    steps_raw: List[DistributionOrderApprovalConfig],
    chain_code: int,
    current_step: int,
) -> Tuple[int, int]:
    """当前环节在审批链中的序号与总数。"""
    all_steps = effective_approval_steps(order, steps_raw, chain_code)
    nos = [int(s.step_no) for s in all_steps]
    if not nos:
        return 1, 1
    try:
        idx = nos.index(int(current_step))
    except ValueError:
        idx = 0
    return idx + 1, len(nos)


async def get_approval_users(
    session: AsyncSession, country: str, chain_code: int, role_id: int
) -> Dict[Tuple[int, str], str]:
    """{(step_no, country): 逗号分隔用户名}，对齐合同 get_approval_users。"""
    sql = text(
        """
        SELECT dac.step_no AS step_no,
               yrp.value AS country,
               GROUP_CONCAT(DISTINCT yu.name) AS user_names
        FROM internal_app.user_business_role_permission yrp
        INNER JOIN internal_app.business_role_config bsc ON bsc.id = yrp.role_config_id
        INNER JOIN internal_app.business_role bs ON bsc.role_id = bs.role_id
        INNER JOIN internal_app.data_distribution_order_approval_config dac
            ON dac.role_id = bs.role_id
        INNER JOIN internal_app.yy_user yu ON yu._id = yrp.user_id
        WHERE yrp.value = :country
          AND bsc.role_id = :role_id
          AND dac.chain_code = :chain_code
          AND dac.is_active = 1
          AND bsc.invalid_ind = 0
          AND bs.invalid_ind = 0
          AND yrp.invalid_ind = 0
        GROUP BY dac.step_no, yrp.value
        """
    )
    result = await session.execute(
        sql, {"country": country, "role_id": role_id, "chain_code": chain_code}
    )
    approval_map = {}
    for row in result.all():
        approval_map[(row.step_no, row.country)] = row.user_names
    return approval_map


async def get_current_step_approval_users(
    session: AsyncSession, country: str, chain_code: int, step_no: int
) -> Dict[Tuple[int, str], str]:
    """{(step_no, country): 逗号分隔用户名}，对齐合同 get_approval_users。"""
    sql = text(
        """
        SELECT dac.step_no AS step_no,
               yrp.value AS country,
               GROUP_CONCAT(DISTINCT yu.name) AS user_names
        FROM internal_app.user_business_role_permission yrp
        INNER JOIN internal_app.business_role_config bsc ON bsc.id = yrp.role_config_id
        INNER JOIN internal_app.business_role bs ON bsc.role_id = bs.role_id
        INNER JOIN internal_app.data_distribution_order_approval_config dac
            ON dac.role_id = bs.role_id
        INNER JOIN internal_app.yy_user yu ON yu._id = yrp.user_id
        WHERE yrp.value = :country
          AND dac.chain_code = :chain_code
          AND dac.step_no = :step_no
          AND dac.is_active = 1
          AND bsc.invalid_ind = 0
          AND bs.invalid_ind = 0
          AND yrp.invalid_ind = 0
        GROUP BY dac.step_no, yrp.value
        """
    )
    result = await session.execute(
        sql, {"country": country,  "chain_code": chain_code, "step_no": step_no}
    )
    user_names = ""
    for row in result.all():
        user_names = row.user_names

    return user_names


async def _resolve_operator_name(session: AsyncSession, operator_id: Optional[int]) -> Optional[str]:
    if not operator_id:
        return None
    if operator_id == 0:
        return "System"
    try:
        from apps.common.service.user import UserService
    except ImportError:
        return None
    name = await UserService.get_user_name_by_userid(session, operator_id)
    return name


async def _resolve_step_operator_display_name(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    step: DistributionOrderApprovalConfig,
    country: str,
) -> str:
    """环节默认展示名：直线上级姓名或办事角色多人名。"""
    if int(step.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
        mgr_id = line_manager_user_id_for_chain(order, chain_code)
        return await _resolve_operator_name(session, mgr_id) or ""
    step_no = int(step.step_no or 0)
    approval_map = await get_approval_users(
        session, country, chain_code, int(step.role_id),
    )
    return (approval_map.get((step_no, country)) or "").strip()


def _step_role_name_snapshot(
    steps: List[DistributionOrderApprovalConfig], step_no: Optional[int]
) -> Optional[str]:
    if step_no is None:
        return None
    for step in steps:
        if step.step_no == step_no:
            name = (step.role_name or "").strip()
            return name or None
    return None


def _resolve_log_role_name(
    steps: List[DistributionOrderApprovalConfig],
    action: int,
    from_step: Optional[int],
    to_step: Optional[int],
) -> Optional[str]:
    if action in (ACTION_QUOTE_SUBMIT, ACTION_ORDER_SUBMIT):
        return _step_role_name_snapshot(steps, to_step)
    if action in (
        ACTION_QUOTE_APPROVE,
        ACTION_ORDER_APPROVE,
        ACTION_QUOTE_REJECT,
        ACTION_ORDER_REJECT,
        ACTION_QUOTE_WITHDRAW,
        ACTION_ORDER_WITHDRAW,
        ACTION_QUOTE_AUTO_PASS,
        ACTION_ORDER_AUTO_PASS,
    ):
        return _step_role_name_snapshot(steps, from_step)
    return None


def _write_auto_pass_logs(
    session: AsyncSession,
    *,
    order_id: int,
    chain_code: int,
    phase: str,
    in_review_status: int,
    steps_raw: List[DistributionOrderApprovalConfig],
    auto_pass_steps: List[Tuple[int, int]],
    next_step: Optional[int],
) -> None:
    """同人重复审批：记录被跳过环节的角色、操作人，action 打自动通过标签。"""
    if not auto_pass_steps:
        return
    auto_action = (
        ACTION_QUOTE_AUTO_PASS if phase == PHASE_QUOTE else ACTION_ORDER_AUTO_PASS
    )
    for idx, (skipped, skip_operator_id) in enumerate(auto_pass_steps):
        if idx + 1 < len(auto_pass_steps):
            to_step = auto_pass_steps[idx + 1][0]
        else:
            to_step = next_step
        _write_status_log(
            session,
            order_id=order_id,
            from_status=in_review_status,
            to_status=in_review_status,
            from_chain_code=chain_code,
            to_chain_code=chain_code,
            from_step=skipped,
            to_step=to_step,
            role_name=_step_role_name_snapshot(steps_raw, skipped),
            action_code=auto_action,
            operator_id=skip_operator_id,
            operator_role=OPERATOR_APPROVER,
            trigger_type=TRIGGER_APPROVAL,
            remark=None,
        )


def _write_status_log(
    session: AsyncSession,
    *,
    order_id: int,
    from_status: Optional[int],
    to_status: int,
    from_chain_code: Optional[int],
    to_chain_code: Optional[int],
    from_step: Optional[int],
    to_step: Optional[int],
    role_name: Optional[str] = None,
    action_code: Optional[int],
    operator_id: Optional[int],
    operator_role: Optional[int] = None,
    trigger_type: int = TRIGGER_APPROVAL,
    remark: Optional[str] = None,
) -> None:
    session.add(
        DistributionOrderStatusLog(
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            from_chain_code=from_chain_code,
            to_chain_code=to_chain_code,
            from_step=from_step,
            to_step=to_step,
            role_name=role_name,
            action_code=action_code,
            operator_id=operator_id,
            operator_role=operator_role,
            trigger_type=trigger_type,
            remark=remark,
        )
    )


async def _resolve_order_chain_code(
    session: AsyncSession, order: DistributionOrder
) -> Optional[int]:
    if order.current_chain_code in ORDER_CHAIN_CODES:
        return order.current_chain_code
    row = (
        await session.execute(
            select(DistributionOrderStatusLog.to_chain_code)
            .where(
                DistributionOrderStatusLog.order_id == order._id,
                DistributionOrderStatusLog.action_code == ACTION_ORDER_SUBMIT,
                DistributionOrderStatusLog.to_chain_code.isnot(None),
            )
            .order_by(
                DistributionOrderStatusLog.create_time.desc(),
                DistributionOrderStatusLog._id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def _apply_fulfillment_transition(
    session: AsyncSession,
    order: DistributionOrder,
    *,
    action: int,
    operator_id: Optional[int] = None,
    operator_role: Optional[int] = None,
    remark: Optional[str] = None,
    trigger_type: int = TRIGGER_MANUAL,
) -> Tuple[DistributionOrder, Dict[str, Any], str]:
    """预付/实收/回款：不加载审批链配置，仅改主状态并写日志。"""
    from_status = order.status
    from_chain = order.current_chain_code
    from_step = order.current_step

    if action == ACTION_PREPAY_CONFIRM:
        order.status = STATUS_PENDING_DISPATCH
        message = "已确认预付，进入待下发"
    elif action == ACTION_DISPATCH:
        order.status = STATUS_FULFILLING
        message = "下发千易成功，进入履约中"
    elif action == ACTION_RECEIVE_CONFIRM:
        order.status = STATUS_PENDING_PAYMENT
        order.payment_todo_synced = 0  # §2.2.8：进入待回款，待推发起人回款待办
        message = "已确认实收，进入待回款"
    elif action == ACTION_PAYMENT_CONFIRM:
        order.status = STATUS_COMPLETED
        message = "已确认回款，订单完成"
    else:
        raise ValueError("非履约动作码: %s" % action)

    order.update_by = operator_id
    order.update_time = datetime.datetime.now()

    _write_status_log(
        session,
        order_id=order._id,
        from_status=from_status,
        to_status=order.status,
        from_chain_code=from_chain,
        to_chain_code=from_chain,
        from_step=from_step,
        to_step=from_step,
        role_name=None,
        action_code=action,
        operator_id=operator_id,
        operator_role=operator_role,
        trigger_type=trigger_type,
        remark=remark,
    )
    from apps.system.distribution_order.distribution_order_tags import (
        refresh_order_tags,
    )
    await session.flush()
    await refresh_order_tags(session, int(order._id), order=order)
    meta = {
        "action": action,
        "phase": PHASE_FULFILLMENT,
        "from_status": from_status,
        "to_status": order.status,
        "current_chain_code": order.current_chain_code,
        "current_step": order.current_step,
        "total_steps": None,
        "message": message,
    }
    return order, meta, message


async def void_order(
    session: AsyncSession,
    *,
    order_id: int,
    operator_id: Optional[int] = None,
    operator_role: Optional[int] = None,
    remark: Optional[str] = None,
    trigger_type: int = TRIGGER_MANUAL,
) -> Tuple[DistributionOrder, Dict[str, Any], str]:
    """草稿/订单创建 → 已作废（不 commit）。"""
    order = await _load_order(session, order_id)
    from_status = order.status
    if from_status == STATUS_VOIDED:
        raise ValueError("订单已作废")
    if from_status not in (STATUS_DRAFT,STATUS_QUOTE_REVIEW ,STATUS_ORDER_CREATE, STATUS_ORDER_REVIEW, STATUS_PREPAY, STATUS_PENDING_DISPATCH):
        raise ValueError(
            "当前状态「%s」不允许作废"
            % STATUS_STR.get(from_status, from_status)
        )

    from_chain = order.current_chain_code
    from_step = order.current_step
    order_remark = order.remark
    if order_remark is None:
        order_remark = "【作废原因】:" + remark
    else:
        order_remark = order_remark + "; " + "【作废原因】:" + remark
    order.remark = order_remark
    order.void_from_status = from_status
    order.status = STATUS_VOIDED
    order.current_chain_code = None
    order.current_step = None
    order.update_by = operator_id
    order.update_time = datetime.datetime.now()

    _write_status_log(
        session,
        order_id=order_id,
        from_status=from_status,
        to_status=STATUS_VOIDED,
        from_chain_code=from_chain,
        to_chain_code=None,
        from_step=from_step,
        to_step=None,
        role_name=None,
        action_code=ACTION_VOID,
        operator_id=operator_id,
        operator_role=operator_role,
        trigger_type=trigger_type,
        remark=remark,
    )

    from apps.system.distribution_order.distribution_order_tags import (
        refresh_order_tags,
    )
    await refresh_order_tags(session, order_id, order=order)

    message = "订单已作废"
    meta = {
        "action": ACTION_VOID,
        "phase": "void",
        "from_status": from_status,
        "to_status": STATUS_VOIDED,
        "current_chain_code": None,
        "current_step": None,
        "total_steps": None,
        "message": message,
    }
    return order, meta, message


async def apply_transition(
    session: AsyncSession,
    *,
    order_id: int,
    action: int,
    operator_id: Optional[int] = None,
    operator_role: Optional[int] = None,
    remark: Optional[str] = None,
    trigger_type: int = TRIGGER_MANUAL,
    chain_code: Optional[int] = None,
    reject_to_step: Optional[int] = None,
    reject_to_status: Optional[int] = None,
) -> Tuple[DistributionOrder, Dict[str, Any], str]:
    """
    执行一次审批相关状态流转（不 commit）。

    chain_code：提交订单审核(ACTION_ORDER_SUBMIT)时必填，取 2 或 3。
    reject_to_step / reject_to_status：驳回时回退目标（Q2 不清业务数据）。
    """
    order = await _load_order(session, order_id)
    from_status = order.status
    from_chain = order.current_chain_code
    from_step = order.current_step

    _assert_transition(from_status, action)
    if action in FULFILLMENT_ACTIONS:
        return await _apply_fulfillment_transition(
            session,
            order,
            action=action,
            operator_id=operator_id,
            operator_role=operator_role,
            remark=remark,
            trigger_type=trigger_type,
        )

    phase = phase_for_action(action)

    is_workflow_action = action in (
        ACTION_QUOTE_SUBMIT, ACTION_ORDER_SUBMIT,
        ACTION_QUOTE_APPROVE, ACTION_ORDER_APPROVE,
        ACTION_QUOTE_REJECT, ACTION_ORDER_REJECT,
        ACTION_QUOTE_WITHDRAW, ACTION_ORDER_WITHDRAW,
    )
    steps_raw: List[DistributionOrderApprovalConfig] = []
    total_steps = 0
    message = ""

    if is_workflow_action:
        if phase == PHASE_QUOTE:
            active_chain = CHAIN_PRICING
        else:
            active_chain = chain_code or order.current_chain_code
            if action == ACTION_ORDER_SUBMIT and active_chain not in ORDER_CHAIN_CODES:
                raise ValueError("审核错误")

        steps_raw = await _load_approval_steps(session, active_chain)
        total_steps = len(
            effective_approval_steps(order, steps_raw, active_chain),
        )
    else:
        active_chain = order.current_chain_code

    to_status = from_status
    to_chain = from_chain
    to_step = from_step
    pending_auto_pass = None

    if action in (ACTION_QUOTE_SUBMIT, ACTION_ORDER_SUBMIT):
        to_status = STATUS_QUOTE_REVIEW if phase == PHASE_QUOTE else STATUS_ORDER_REVIEW
        order.status = to_status
        order.current_chain_code = active_chain
        if operator_id is not None:
            order.submit_by = int(operator_id)
        if phase == PHASE_QUOTE:
            # §2.2.2：进入报价审核，待定时任务推待办给当前环节审核人
            order.quote_approval_todo_synced_step = None
        else:
            # §2.2.4：进入订单审核
            order.order_approval_todo_synced_step = None
        acted = chain_skip_acted_base_user_ids(order)
        _add_operated_user_id(acted, operator_id)
        next_step, auto_pass_steps = await resolve_forward_with_skip(
            session, order, active_chain, steps_raw, 0, acted,
            trigger_operator_id=operator_id,
        )
        in_review_status = (
            STATUS_QUOTE_REVIEW if phase == PHASE_QUOTE else STATUS_ORDER_REVIEW
        )
        if next_step is None:
            to_status, message = _finish_review_approval(order, phase)
            to_chain = None
            to_step = None
        else:
            order.current_step = next_step
            to_chain = active_chain
            to_step = order.current_step
            message = "已提交，待审批"
        if auto_pass_steps:
            pending_auto_pass = {
                "chain_code": active_chain,
                "phase": phase,
                "in_review_status": in_review_status,
                "auto_pass_steps": auto_pass_steps,
                "next_step": next_step,
            }

    elif action in (ACTION_QUOTE_APPROVE, ACTION_ORDER_APPROVE):
        if order.current_step is None:
            raise ValueError("当前无待审环节")
        acted = await collect_chain_acted_user_ids(
            session, order, active_chain, phase,
        )
        _add_operated_user_id(acted, operator_id)
        next_step, auto_pass_steps = await resolve_forward_with_skip(
            session,
            order,
            active_chain,
            steps_raw,
            int(order.current_step),
            acted,
            trigger_operator_id=operator_id,
        )
        in_review_status = (
            STATUS_QUOTE_REVIEW if phase == PHASE_QUOTE else STATUS_ORDER_REVIEW
        )
        if next_step is None:
            to_status, message = _finish_review_approval(order, phase)
            to_chain = None
            to_step = None
        else:
            order.current_step = next_step
            to_status = order.status
            to_chain = active_chain
            to_step = order.current_step
            cur_idx, total = await _active_step_progress(
                session, order, steps_raw, active_chain, order.current_step,
            )
            message = "审批通过，当前环节 %s/%s" % (cur_idx, total)
        if auto_pass_steps:
            pending_auto_pass = {
                "chain_code": active_chain,
                "phase": phase,
                "in_review_status": in_review_status,
                "auto_pass_steps": auto_pass_steps,
                "next_step": next_step,
            }

    elif action in (ACTION_QUOTE_REJECT, ACTION_ORDER_REJECT):
        if reject_to_step is not None or reject_to_status is not None:
            to_status = reject_to_status
            if to_status is None:
                to_status = (
                    STATUS_DRAFT if phase == PHASE_QUOTE else STATUS_ORDER_CREATE
                )
            order.status = to_status
            order.current_step = reject_to_step
            if to_status not in (STATUS_QUOTE_REVIEW, STATUS_ORDER_REVIEW):
                order.current_chain_code = None
                to_chain = None
            else:
                to_chain = active_chain
            to_step = reject_to_step
            message = "已驳回"
        else:
            to_status = STATUS_DRAFT if phase == PHASE_QUOTE else STATUS_ORDER_CREATE
            order.status = to_status
            order.current_chain_code = None
            order.current_step = None
            to_chain = None
            to_step = None
            message = "已驳回"

    elif action in (ACTION_QUOTE_WITHDRAW, ACTION_ORDER_WITHDRAW):
        to_status = STATUS_DRAFT if phase == PHASE_QUOTE else STATUS_ORDER_CREATE
        order.status = to_status
        order.current_chain_code = None
        order.current_step = None
        to_chain = None
        to_step = None
        message = "已撤回"

    order.update_by = operator_id
    order.update_time = datetime.datetime.now()

    log_role_name = _resolve_log_role_name(steps_raw, action, from_step, to_step)
    _write_status_log(
        session,
        order_id=order_id,
        from_status=from_status,
        to_status=order.status,
        from_chain_code=from_chain,
        to_chain_code=to_chain,
        from_step=from_step,
        to_step=to_step,
        role_name=log_role_name,
        action_code=action,
        operator_id=operator_id,
        operator_role=operator_role,
        trigger_type=trigger_type,
        remark=remark,
    )
    if pending_auto_pass:
        _write_auto_pass_logs(
            session,
            order_id=order_id,
            steps_raw=steps_raw,
            **pending_auto_pass,
        )
    from apps.system.distribution_order.distribution_order_tags import (
        refresh_order_tags,
    )
    await refresh_order_tags(session, order_id, order=order)

    meta = {
        "action": action,
        "phase": phase,
        "from_status": from_status,
        "to_status": order.status,
        "current_chain_code": order.current_chain_code,
        "current_step": order.current_step,
        "total_steps": total_steps or None,
        "message": message,
    }
    return order, meta, message


async def _fetch_chain_logs(
    session: AsyncSession,
    order_id: int,
    chain_code: int,
    action_codes: Tuple[int, ...],
) -> List[DistributionOrderStatusLog]:
    rows = (
        await session.execute(
            select(DistributionOrderStatusLog)
            .where(
                DistributionOrderStatusLog.order_id == order_id,
                DistributionOrderStatusLog.action_code.in_(action_codes),
            )
            .order_by(
                DistributionOrderStatusLog.create_time,
                DistributionOrderStatusLog._id,
            )
        )
    ).scalars().all()
    filtered = []
    for log in rows:
        chain = log.to_chain_code or log.from_chain_code
        if chain == chain_code:
            filtered.append(log)
    return filtered


async def _build_initiator_submit_item(
    session: AsyncSession,
    order: DistributionOrder,
    *,
    from_status: int,
    to_status: int,
) -> Dict[str, Any]:
    """预提交阶段：下一步首位为发起人办理（提交审核）。"""
    operator_name = await _resolve_operator_name(session, order.create_by) or ""
    return {
        "from_status": from_status,
        "from_status_str": STATUS_STR.get(from_status, from_status),
        "to_status": to_status,
        "to_status_str": STATUS_STR.get(to_status, to_status),
        "step_no": None,
        "role_name": "发起人",
        "action_code_str": "办理中",
        "operator_name": operator_name,
    }


async def _build_pre_review_next_steps(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    steps_raw: List[DistributionOrderApprovalConfig],
    *,
    from_status: int,
    in_review_status: int,
) -> List[Dict[str, Any]]:
    """审核前：发起人提交(办理中) + 审批链全部环节(待办理)。"""
    initiator = await _build_initiator_submit_item(
        session, order, from_status=from_status, to_status=in_review_status,
    )
    approver_steps = await _build_next_step_items(
        session, order, chain_code, steps_raw, None, in_review_status, False,
        acted_user_ids=initiator_acted_user_ids(order),
    )
    return [initiator] + approver_steps


async def _build_next_step_items(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    steps_raw: List[DistributionOrderApprovalConfig],
    from_step_no: Optional[int],
    in_review_status: int,
    is_first_pending: bool,
    *,
    phase: Optional[str] = None,
    acted_user_ids: Optional[Set[int]] = None,
) -> List[Dict[str, Any]]:
    """
    组装 next_steps 预览：与 resolve_forward_with_skip 共用环节列表与同人跳过规则。
    仅将触发跳过的实际操作人计入 acted；自动通过展示该人姓名。
    """
    country = await get_customer_country(session, order.offline_customer_id)
    if not country:
        return []
    if acted_user_ids is None:
        if phase is None:
            phase = (
                PHASE_QUOTE if in_review_status == STATUS_QUOTE_REVIEW else PHASE_ORDER
            )
        acted = await collect_chain_acted_user_ids(
            session, order, chain_code, phase,
        )
    else:
        acted = set(acted_user_ids)
    after_step_no = int(from_step_no) - 1 if from_step_no is not None else 0
    steps_after = await _list_active_steps_after(
        session, order, chain_code, steps_raw, after_step_no,
    )
    items = []
    first_pending_marked = not is_first_pending
    for step_no, step in steps_after:
        approver_ids = await get_step_approver_user_ids(
            session, order, chain_code, step, country=country,
        )
        if not approver_ids:
            continue
        operator_name = await _resolve_step_operator_display_name(
            session, order, chain_code, step, country,
        )
        if not operator_name:
            continue
        is_current_step = (
            is_first_pending
            and not first_pending_marked
            and from_step_no is not None
            and int(step_no) == int(from_step_no)
        )
        skip_uid = None
        if not is_current_step:
            skip_uid = _try_apply_step_skip(acted, approver_ids)
        if skip_uid is not None:
            skip_name = await _resolve_operator_name(session, skip_uid) or ""
            if skip_name:
                operator_name = skip_name
            action_code_str = "自动通过"
            operator_id = skip_uid
        else:
            action_code_str = (
                "办理中" if is_first_pending and not first_pending_marked else "待办理"
            )
            first_pending_marked = True
            operator_id = None
        items.append(
            {
                "from_status": in_review_status,
                "from_status_str": STATUS_STR.get(in_review_status, ""),
                "to_status": in_review_status,
                "to_status_str": STATUS_STR.get(in_review_status, ""),
                "step_no": step_no,
                "role_name": step.role_name,
                "action_code_str": action_code_str,
                "operator_id": operator_id,
                "operator_name": operator_name,
                "operator_role_str": step.role_name,
            }
        )
    return items


def _is_review_phase_completed(
    order: DistributionOrder,
    history_steps: List[Dict[str, Any]],
    in_review_status: int,
) -> bool:
    """主状态已离开 in_review_status，则该阶段审批不再有 next_steps。"""
    if int(order.status) == int(in_review_status):
        return False
    if int(order.status) > int(in_review_status):
        return True
    return False


async def _resolve_preview_from_step_no(
    session: AsyncSession,
    order: DistributionOrder,
    chain_code: int,
    steps_raw: List[DistributionOrderApprovalConfig],
    merged_logs: List[DistributionOrderStatusLog],
    in_review_status: int,
) -> Optional[int]:
    """推断 next_steps 起始环节：优先主表 current_step，否则看末条日志。"""
    if (
        int(order.status) == int(in_review_status)
        and order.current_chain_code == chain_code
        and order.current_step is not None
        and int(order.current_step) > 0
    ):
        return int(order.current_step)
    if not merged_logs:
        return None
    last_log = merged_logs[-1]
    last_action = int(last_log.action_code or 0)
    if last_log.to_step is not None and int(last_log.to_step) > 0:
        return int(last_log.to_step)
    if last_action in (ACTION_QUOTE_AUTO_PASS, ACTION_ORDER_AUTO_PASS):
        after_step = int(last_log.from_step or 0)
        steps_after = await _list_active_steps_after(
            session, order, chain_code, steps_raw, after_step,
        )
        if steps_after:
            return int(steps_after[0][0])
        return None
    if last_log.from_step is not None and int(last_log.from_step) > 0:
        return int(last_log.from_step)
    return None


async def _build_history_step_item(
    session: AsyncSession,
    log: DistributionOrderStatusLog,
    step_role_name: Dict[int, str],
) -> Dict[str, Any]:
    operator_name = await _resolve_operator_name(session, log.operator_id)
    role_str = OPERATOR_ROLE_STR.get(log.operator_role, log.operator_role)
    step_no = log.to_step
    if log.action_code in (ACTION_QUOTE_AUTO_PASS, ACTION_ORDER_AUTO_PASS):
        step_no = log.from_step
        if log.role_name:
            role_str = log.role_name
    elif log.operator_role == OPERATOR_APPROVER and log.from_step:
        role_str = step_role_name.get(log.from_step, role_str)
    operated_at = None
    if log.create_time:
        operated_at = log.create_time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "from_status": log.from_status,
        "from_status_str": STATUS_STR.get(log.from_status, log.from_status),
        "to_status": log.to_status,
        "to_status_str": STATUS_STR.get(log.to_status, log.to_status),
        "action_code": log.action_code,
        "action_code_str": ACTION_STR.get(log.action_code, log.action_code),
        "step_no": step_no,
        "operator_id": log.operator_id,
        "operator_name": operator_name,
        "operator_role": log.operator_role,
        "operator_role_str": role_str,
        "role_name": log.role_name,
        "operated_at": operated_at,
        "remark": log.remark,
    }


def _tag_steps_approval_type(
    steps: List[Dict[str, Any]], phase: str,
) -> List[Dict[str, Any]]:
    """给 history/next 步骤打上审核类型。"""
    label = APPROVAL_TYPE_STR.get(phase, phase)
    out: List[Dict[str, Any]] = []
    for step in steps or []:
        item = dict(step)
        item["approval_type"] = phase
        item["approval_type_str"] = label
        out.append(item)
    return out


async def _load_workflow_bundle(
    session: AsyncSession,
    order_id: int,
    chain_code: int,
    phase: str,
) -> Dict[str, Any]:
    order = await _load_order(session, order_id)
    in_review_status = (
        STATUS_QUOTE_REVIEW if phase == PHASE_QUOTE else STATUS_ORDER_REVIEW
    )
    action_codes = QUOTE_ACTIONS if phase == PHASE_QUOTE else ORDER_ACTIONS
    auto_pass_action = (
        ACTION_QUOTE_AUTO_PASS if phase == PHASE_QUOTE else ACTION_ORDER_AUTO_PASS
    )

    steps_raw = await _load_approval_steps(session, chain_code)
    step_role_name = {s.step_no: s.role_name for s in steps_raw}
    workflow_logs = await _fetch_chain_logs(session, order_id, chain_code, action_codes)
    auto_pass_logs = await _fetch_chain_logs(
        session, order_id, chain_code, (auto_pass_action,),
    )

    merged_logs = sorted(
        workflow_logs + auto_pass_logs,
        key=lambda item: (item.create_time or datetime.datetime.min, item._id or 0),
    )
    history_for_next = []
    for log in merged_logs:
        history_for_next.append(
            await _build_history_step_item(session, log, step_role_name)
        )
    history_steps = []
    for log in merged_logs:
        history_steps.append(
            await _build_history_step_item(session, log, step_role_name)
        )

    next_steps = []
    review_done = _is_review_phase_completed(
        order, history_for_next, in_review_status,
    )
    if not review_done:
        if phase == PHASE_QUOTE and order.status == STATUS_DRAFT:
            next_steps = await _build_pre_review_next_steps(
                session, order, chain_code, steps_raw,
                from_status=STATUS_DRAFT, in_review_status=STATUS_QUOTE_REVIEW,
            )
        elif phase == PHASE_ORDER and order.status < STATUS_ORDER_REVIEW:
            next_steps = await _build_pre_review_next_steps(
                session, order, chain_code, steps_raw,
                from_status=order.status, in_review_status=STATUS_ORDER_REVIEW,
            )
        else:
            preview_from_step = await _resolve_preview_from_step_no(
                session, order, chain_code, steps_raw, merged_logs, in_review_status,
            )
            if preview_from_step is not None:
                next_steps = await _build_next_step_items(
                    session,
                    order,
                    chain_code,
                    steps_raw,
                    preview_from_step,
                    in_review_status,
                    True,
                    phase=phase,
                )

    return {
        "order_sn": order.order_sn,
        "order_status": order.status,
        "order_status_str": STATUS_STR.get(order.status, order.status),
        "current_chain_code": chain_code,
        "current_step": order.current_step if order.current_chain_code == chain_code else None,
        "phase": phase,
        "approval_type": phase,
        "approval_type_str": APPROVAL_TYPE_STR.get(phase, phase),
        "history_steps": _tag_steps_approval_type(history_steps, phase),
        "next_steps": _tag_steps_approval_type(next_steps, phase),
    }


async def load_quote_workflow_bundle(session: AsyncSession, order_id: int) -> Dict[str, Any]:
    return await _load_workflow_bundle(session, order_id, CHAIN_PRICING, PHASE_QUOTE)


async def load_order_workflow_bundle(session: AsyncSession, order_id: int) -> Dict[str, Any]:
    order = await _load_order(session, order_id)
    chain_code = await _resolve_order_chain_code(session, order)
    if chain_code is None:
        if order.status < STATUS_ORDER_REVIEW:
            chain_code = CHAIN_ORDER_STANDARD
        else:
            return {
                "order_sn": order.order_sn,
                "order_status": order.status,
                "order_status_str": STATUS_STR.get(order.status, order.status),
                "current_chain_code": None,
                "current_step": None,
                "phase": PHASE_ORDER,
                "approval_type": PHASE_ORDER,
                "approval_type_str": APPROVAL_TYPE_STR[PHASE_ORDER],
                "history_steps": [],
                "next_steps": [],
            }
    return await _load_workflow_bundle(session, order_id, chain_code, PHASE_ORDER)


async def load_combined_workflow_bundle(
    session: AsyncSession, order_id: int,
) -> Dict[str, Any]:
    """
    统一审批流：报价+订单已审历史都展示，步骤带审核类型；
    next_steps 仅取当前所处阶段。
    """
    order = await _load_order(session, order_id)
    quote_bundle = await load_quote_workflow_bundle(session, order_id)
    order_bundle = await load_order_workflow_bundle(session, order_id)

    history_steps = list(quote_bundle.get("history_steps") or [])
    history_steps.extend(order_bundle.get("history_steps") or [])

    def _history_sort_key(item: Dict[str, Any]) -> Tuple[str, int]:
        return (str(item.get("operated_at") or ""), int(item.get("action_code") or 0))

    history_steps.sort(key=_history_sort_key)

    status = int(order.status or 0)
    if status <= STATUS_QUOTE_REVIEW:
        active = quote_bundle
        phase = PHASE_QUOTE
    else:
        active = order_bundle
        phase = PHASE_ORDER

    return {
        "order_sn": order.order_sn,
        "order_status": order.status,
        "order_status_str": STATUS_STR.get(order.status, order.status),
        "current_chain_code": active.get("current_chain_code"),
        "current_step": active.get("current_step"),
        "phase": phase,
        "approval_type": phase,
        "approval_type_str": APPROVAL_TYPE_STR.get(phase, phase),
        "history_steps": history_steps,
        "next_steps": list(active.get("next_steps") or []),
    }
