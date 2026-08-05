# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/29
# @Author  : Zhu Yaming
# @File    : distribution_order_todo.py
# @Description : 分销订单首页待办（需求文档 §2.2.2 / §2.2.4 / §2.2.5 / §2.2.8）

**TodoQueueSender 用法（主仓）**：
  - 接口内：``TodoQueueSender(request=request)``，复用 ``request.app.state.data_cache``
  - 脚本兜底：``TodoQueueSender()``（request=None），自建 Redis 连接
  - ``produce`` 创建/关闭时：顶层 ``title`` 均为「分销下单」；详情见 ``add_param.note``（``add_param`` 不含 ``title``）
  - 创建：``add_param`` 含 ``todo_step_name`` / ``todo_step`` / ``todo_user_id`` / ``level``（与外层 ``todo_level`` 一致，consumer 写入明细表）
  - 关闭：``update_param`` 含 ``action=COMPLETE_ALL`` + ``todo_step``（``todo_level`` 仍必填）

§2.2.5 确认预付：PRD 笔误写「审核人」，实际推送给持 ``prepay_confirm`` 操作权限的财务用户。

定时兜底脚本（与实时推送分离）：
``scripts/sync_distribution_order_todo.py`` → ``scripts/distribution_order_todo_sync.py``
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from loguru import logger
from sqlalchemy import desc, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.system.distribution_order.distribution_order_workflow_engine import (
    ACTION_ORDER_APPROVE,
    ACTION_ORDER_REJECT,
    ACTION_ORDER_SUBMIT,
    ACTION_ORDER_WITHDRAW,
    ACTION_QUOTE_APPROVE,
    ACTION_QUOTE_REJECT,
    ACTION_QUOTE_SUBMIT,
    ACTION_QUOTE_WITHDRAW,
    APPROVER_TYPE_LINE_MANAGER,
    STATUS_ORDER_REVIEW,
    STATUS_PENDING_PAYMENT,
    STATUS_PREPAY,
    STATUS_QUOTE_REVIEW,
    _find_approval_step_by_no,
    _load_approval_steps,
    _load_order,
    get_customer_country,
    get_role_step_approver_user_ids,
    line_manager_user_id_for_chain,
)
from apps.system.distribution_order.models import (
    DistributionOrder,
    DistributionOrderStatusLog,
)

# todo_keywords / todo_step 与首页待办路由约定；合入主仓后与前端的 todo_step 对齐
TODO_SCENE_QUOTE_APPROVAL = "distribution_order_quote_approval"
TODO_SCENE_ORDER_APPROVAL = "distribution_order_order_approval"
TODO_SCENE_PREPAY_CONFIRM = "distribution_order_prepay_confirm"
TODO_SCENE_PAYMENT_CONFIRM = "distribution_order_payment_confirm"

# 首页待办 menu_id（分销下单菜单）
DISTRIBUTION_ORDER_MENU_ID = 416

# 首页待办 title（模块名，四类统一；对齐种草计划等待办 title 用法）
TODO_TITLE = "分销下单"

# 关闭待办时 todo_level 必填（TodoQueueSender 校验）；消费侧 COMPLETE_ALL 通常忽略该字段
TODO_CLOSE_DEFAULT_LEVEL = "P2"

# yy_permission：tab1 操作权限 code（见 permissions.sql）
PERM_PREPAY_CONFIRM = "prepay_confirm"
PERM_TYPE_TAB1 = "tab1"

# 持 tab1 操作权限的用户（合入主仓后 SQL 以对齐 yy_permission 表结构）
TAB1_PERMISSION_USER_IDS_SQL = """
SELECT DISTINCT ur.user_id AS user_id
FROM internal_app.yy_user_role ur
INNER JOIN internal_app.yy_role_permission rp ON rp.role_id = ur.role_id
INNER JOIN internal_app.yy_permission p ON p._id = rp.permission_id
WHERE p.permission_code = :permission_code
  AND p.permission_type = :permission_type
  AND ur.invalid_ind = 0
  AND rp.invalid_ind = 0
  AND p.invalid_ind = 0
"""


# ── 工具 ─────────────────────────────────────────────────────────────────────


def _coerce_date(value: Any) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text_val = str(value).strip()
    if not text_val:
        return None
    try:
        return datetime.date.fromisoformat(text_val[:10])
    except ValueError:
        return None


def _get_field(item: Union[Mapping[str, Any], Any], key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _unique_user_ids(user_ids: Sequence[Any]) -> List[int]:
    out = []
    seen = set()
    for uid in user_ids:
        if uid is None:
            continue
        try:
            n = int(uid)
        except (TypeError, ValueError):
            continue
        if n <= 0 or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _format_date_bracket(value: Any) -> str:
    """PRD 文案中的【YYYY-MM-DD】；无日期则【-】。"""
    d = _coerce_date(value)
    if d is None:
        return "【-】"
    return "【%s】" % d.isoformat()


def _build_todo_payload(
    *,
    order: Union[Mapping[str, Any], DistributionOrder],
    todo_keywords: str,
    todo_step: str,
    todo_step_name: str,
    note: str,
    todo_level: str,
    user_ids: Sequence[int],
    related_id: str,
    menu_id: Optional[int] = None,
) -> Dict[str, Any]:
    """组装 TodoQueueSender.produce 入参（结构对齐 audit_center / 种草计划等待办）。"""
    order_id = int(_get_field(order, "_id") or _get_field(order, "order_id"))
    order_sn = _get_field(order, "order_sn")

    return {
        "title": TODO_TITLE,
        "todo_keywords": todo_keywords,
        "redirect_params": {"order_id": order_id, "_id": order_id, "order_sn": order_sn},
        "related_id": related_id,
        "menu_id": menu_id if menu_id is not None else get_distribution_order_menu_id(),
        "todo_level": todo_level,
        "add_param": {
            "todo_step_name": todo_step_name,
            "todo_user_id": _unique_user_ids(user_ids),
            "todo_step": todo_step,
            "note": note,
            "level": todo_level,
        },
        "queue_name": "todo_queue",
    }


def get_distribution_order_menu_id() -> int:
    """分销订单首页待办 menu_id。"""
    return DISTRIBUTION_ORDER_MENU_ID


def quote_approval_related_id(order_id: int, step: int) -> str:
    """报价审核待办 related_id（多环节互不覆盖）。"""
    return "%s_quote_%s" % (int(order_id), int(step))


def order_approval_related_id(order_id: int, step: int) -> str:
    """订单审核待办 related_id。"""
    return "%s_order_%s" % (int(order_id), int(step))


async def complete_distribution_order_todo(
    request: Any,
    *,
    todo_keywords: str,
    todo_step: str,
    related_id: str,
    todo_level: str = TODO_CLOSE_DEFAULT_LEVEL,
) -> None:
    """
    关闭待办（``update_param.action=COMPLETE_ALL``）。

    须在 FastAPI 接口内调用并传入 ``request``（复用 Redis 连接池）。
    ``request is None`` 时跳过——关闭动作仅发生在 HTTP 写接口，脚本兜底只补「创建」。
    """
    if request is None:
        return
    try:
        from apps.common.service.todo_queue_sender import TodoQueueSender

        menu_id = get_distribution_order_menu_id()
        sender = TodoQueueSender(request=request)
        try:
            ok, msg = await sender.produce(
                title=TODO_TITLE,
                todo_keywords=todo_keywords,
                related_id=str(related_id),
                menu_id=menu_id,
                todo_level=todo_level,
                update_param={
                    "action": "COMPLETE_ALL",
                    "todo_step": todo_step,
                },
            )
            if not ok:
                logger.warning(
                    "分销订单待办关闭未成功 related_id=%s step=%s: %s"
                    % (related_id, todo_step, msg),
                )
        finally:
            await sender.close()
    except Exception:
        logger.exception(
            "分销订单待办关闭异常 related_id=%s step=%s" % (related_id, todo_step),
        )


async def _sync_todo_notice_main_fields(
    session: AsyncSession,
    *,
    menu_id: int,
    related_id: str,
    todo_keywords: str,
    title: str,
    todo_level: str,
    todo_step: str,
    redirect_params: Any = None,
) -> None:
    """
    推送成功后补写 todo_notice 主表及进行中明细优先级。

    consumer 对唯一键冲突走 INSERT IGNORE，不会更新已有行的 title / redirect_params / todo_level；
    明细优先级写入 add_param.level，未传则 level 为 NULL，列表 coalesce 会回落到主表旧值。
    """
    rp = None
    if redirect_params is not None:
        if isinstance(redirect_params, dict):
            rp = json.dumps(redirect_params, ensure_ascii=False)
        else:
            rp = str(redirect_params)
    params = {
        "title": title,
        "redirect_params": rp,
        "todo_level": todo_level,
        "menu_id": menu_id,
        "related_id": str(related_id),
        "todo_keywords": todo_keywords,
        "todo_step": todo_step,
    }
    await session.execute(
        text("""
            UPDATE internal_app.todo_notice
            SET title = :title,
                redirect_params = COALESCE(:redirect_params, redirect_params),
                todo_level = :todo_level
            WHERE menu_id = :menu_id
              AND related_id = :related_id
              AND todo_keywords = :todo_keywords
        """),
        params,
    )
    await session.execute(
        text("""
            UPDATE internal_app.todo_notice_detail d
            INNER JOIN internal_app.todo_notice n ON d.todo_id = n._id
            SET d.level = :todo_level
            WHERE n.menu_id = :menu_id
              AND n.related_id = :related_id
              AND n.todo_keywords = :todo_keywords
              AND d.todo_step = :todo_step
              AND d.todo_status = 1
        """),
        params,
    )


async def _produce_distribution_order_todo(
    todo_data: Dict[str, Any],
    session: AsyncSession = None,
    *,
    request: Any = None,
    sender: Any = None,
) -> tuple:
    """分销订单专用：推送待办并补写 todo_notice 主表字段及明细优先级（不改 consumer 原函数）。"""
    ret, msg = await _produce_todo(todo_data, request=request, sender=sender)
    if ret and session is not None:
        title = (todo_data.get("title") or TODO_TITLE).strip() or TODO_TITLE
        add_param = todo_data.get("add_param") or {}
        await _sync_todo_notice_main_fields(
            session,
            menu_id=int(todo_data["menu_id"]),
            related_id=str(todo_data["related_id"]),
            todo_keywords=todo_data["todo_keywords"],
            title=title,
            todo_level=str(todo_data["todo_level"]),
            todo_step=str(add_param.get("todo_step") or todo_data["todo_keywords"]),
            redirect_params=todo_data.get("redirect_params"),
        )
    return ret, msg


async def _produce_todo(
    todo_data: Dict[str, Any],
    request: Any = None,
    sender: Any = None,
) -> tuple:
    """
    推送「创建待办」消息（仅 add_param 路径）。

    request 有值 → 接口模式；None → 脚本模式（TodoQueueSender 自建 Redis）。
    """
    add_param = todo_data.get("add_param") or {}
    if not add_param.get("todo_user_id"):
        return False, "待办接收人为空"
    if not todo_data.get("todo_level"):
        return False, "todo_level 不能为空"
    from apps.common.service.todo_queue_sender import TodoQueueSender

    own_sender = sender is None
    if own_sender:
        sender = TodoQueueSender(request=request)
    title = (todo_data.get("title") or TODO_TITLE).strip() or TODO_TITLE
    ret, msg = await sender.produce(
        title=title,
        todo_keywords=todo_data["todo_keywords"],
        redirect_params=todo_data.get("redirect_params"),
        related_id=str(todo_data["related_id"]),
        menu_id=todo_data["menu_id"],
        todo_level=todo_data["todo_level"],
        add_param=add_param,
        queue_name=todo_data.get("queue_name", "todo_queue"),
    )
    if own_sender:
        await sender.close()
    return bool(ret), msg or ""


# ── 优先级（PRD §2.2.2 / §2.2.4 / §2.2.5 / §2.2.8）──────────────────────────


def resolve_todo_level_by_order_create_date(
    create_date: Any,
    *,
    ref_date: Optional[datetime.date] = None,
) -> str:
    """
    报价审核待办优先级（§2.2.2，按「报价单创建日期」距今天数）。

    - 不足 2 自然日：P2
    - 2–4 自然日：P1
    - 4 自然日以上（≥5 天）：P0
    """
    d = _coerce_date(create_date)
    if d is None:
        return "P2"
    today = ref_date or datetime.date.today()
    days = (today - d).days
    if days >= 5:
        return "P0"
    if days >= 2:
        return "P1"
    return "P2"


def resolve_todo_level_by_expected_ship_date(
    expected_ship_date: Any,
    *,
    ref_date: Optional[datetime.date] = None,
) -> str:
    """
    订单审核 / 确认预付待办优先级（§2.2.4、§2.2.5，按期望出库日期距今天数）。

    - 7 自然日以上：P2
    - 2–5 自然日：P1
    - 不足 2 自然日（含已过期、第 6 天）：P0
    """
    ship_date = _coerce_date(expected_ship_date)
    if ship_date is None:
        return "P2"
    today = ref_date or datetime.date.today()
    days = (ship_date - today).days
    if days >= 7:
        return "P2"
    if days >= 2:
        return "P1"
    return "P0"


def resolve_todo_level_by_expected_payment_date(
    expected_payment_date: Any,
    *,
    ref_date: Optional[datetime.date] = None,
) -> str:
    """
    待回款待办优先级（§2.2.8，按预计回款日期）。

    - 预计回款日期未到：P2
    - 已到 0–3 自然日：P1
    - 已到 4 自然日及以上：P0
    """
    pay_date = _coerce_date(expected_payment_date)
    if pay_date is None:
        return "P2"
    today = ref_date or datetime.date.today()
    overdue_days = (today - pay_date).days
    if overdue_days < 0:
        return "P2"
    if overdue_days <= 3:
        return "P1"
    return "P0"


# ── §2.2.2 报价审核 ──────────────────────────────────────────────────────────


def build_quote_approval_todo_note(
    item: Union[Mapping[str, Any], DistributionOrder],
    submit_date: Any,
) -> str:
    """分销订单：你有一条新的报价单待审核-提交审核日期【日期】"""
    return (
        "：你有一条新的报价单待审核-提交审核日期%s"
        % _format_date_bracket(submit_date)
    )


def build_quote_approval_todo_data(
    order: Union[Mapping[str, Any], DistributionOrder],
    user_ids: Sequence[int],
    submit_date: Any,
    *,
    current_step: int,
    menu_id: Optional[int] = None,
) -> Dict[str, Any]:
    order_id = int(_get_field(order, "_id") or _get_field(order, "order_id"))
    return _build_todo_payload(
        order=order,
        todo_keywords=TODO_SCENE_QUOTE_APPROVAL,
        todo_step=TODO_SCENE_QUOTE_APPROVAL,
        todo_step_name="报价审核",
        note=build_quote_approval_todo_note(order, submit_date),
        todo_level=resolve_todo_level_by_order_create_date(
            _get_field(order, "create_time"),
        ),
        user_ids=user_ids,
        # 多环节审批：related_id 含 step，避免下一环节待办被去重
        related_id="%s_quote_%s" % (order_id, int(current_step)),
        menu_id=menu_id,
    )


# ── §2.2.4 订单审核 ──────────────────────────────────────────────────────────


def build_order_approval_todo_note(item: Union[Mapping[str, Any], DistributionOrder]) -> str:
    """分销订单：你有一个新的分销订单待审核-期望最晚出库日期【日期】"""
    return (
        "：你有一个新的分销订单待审核-期望最晚出库日期%s"
        % _format_date_bracket(_get_field(item, "expected_ship_date"))
    )


def build_order_approval_todo_data(
    order: Union[Mapping[str, Any], DistributionOrder],
    user_ids: Sequence[int],
    *,
    current_step: int,
    menu_id: Optional[int] = None,
) -> Dict[str, Any]:
    order_id = int(_get_field(order, "_id") or _get_field(order, "order_id"))
    return _build_todo_payload(
        order=order,
        todo_keywords=TODO_SCENE_ORDER_APPROVAL,
        todo_step=TODO_SCENE_ORDER_APPROVAL,
        todo_step_name="订单审核",
        note=build_order_approval_todo_note(order),
        todo_level=resolve_todo_level_by_expected_ship_date(
            _get_field(order, "expected_ship_date"),
        ),
        user_ids=user_ids,
        related_id="%s_order_%s" % (order_id, int(current_step)),
        menu_id=menu_id,
    )


# ── §2.2.5 确认预付（推送给财务，非审批链审核人）──────────────────────────────


def build_prepay_confirm_todo_note(item: Union[Mapping[str, Any], DistributionOrder]) -> str:
    """分销订单：你有一个新的分销订单预付待确认-期望最晚出库日期【日期】"""
    return (
        "：你有一个新的分销订单预付待确认-期望最晚出库日期%s"
        % _format_date_bracket(_get_field(item, "expected_ship_date"))
    )


def build_prepay_confirm_todo_data(
    item: Union[Mapping[str, Any], DistributionOrder],
    user_ids: Sequence[int],
    *,
    menu_id: Optional[int] = None,
) -> Dict[str, Any]:
    order_id = int(_get_field(item, "_id") or _get_field(item, "order_id"))
    return _build_todo_payload(
        order=item,
        todo_keywords=TODO_SCENE_PREPAY_CONFIRM,
        todo_step=TODO_SCENE_PREPAY_CONFIRM,
        todo_step_name="确认预付",
        note=build_prepay_confirm_todo_note(item),
        todo_level=resolve_todo_level_by_expected_ship_date(
            _get_field(item, "expected_ship_date"),
        ),
        user_ids=user_ids,
        related_id=str(order_id),
        menu_id=menu_id,
    )


# ── §2.2.8 待回款（推送给发起人 create_by）──────────────────────────────────


def build_payment_confirm_todo_note(item: Union[Mapping[str, Any], DistributionOrder]) -> str:
    """分销订单：你有一个新的分销订单回款待确认-预计回款日期【日期】"""
    return (
        "：你有一个新的分销订单回款待确认-预计回款日期%s"
        % _format_date_bracket(_get_field(item, "expected_payment_date"))
    )


def build_payment_confirm_todo_data(
    item: Union[Mapping[str, Any], DistributionOrder],
    user_ids: Sequence[int],
    *,
    menu_id: Optional[int] = None,
) -> Dict[str, Any]:
    order_id = int(_get_field(item, "_id") or _get_field(item, "order_id"))
    return _build_todo_payload(
        order=item,
        todo_keywords=TODO_SCENE_PAYMENT_CONFIRM,
        todo_step=TODO_SCENE_PAYMENT_CONFIRM,
        todo_step_name="确认回款",
        note=build_payment_confirm_todo_note(item),
        todo_level=resolve_todo_level_by_expected_payment_date(
            _get_field(item, "expected_payment_date"),
        ),
        user_ids=user_ids,
        related_id=str(order_id),
        menu_id=menu_id,
    )


# ── 接收人解析 ────────────────────────────────────────────────────────────────


def get_tab1_permission_user_ids(cursor, permission_code: str) -> List[int]:
    """同步游标：持指定 tab1 操作权限的用户 id。"""
    cursor.execute(
        TAB1_PERMISSION_USER_IDS_SQL,
        {"permission_code": permission_code, "permission_type": PERM_TYPE_TAB1},
    )
    rows = cursor.fetchall()
    uids = []
    for row in rows:
        uid = row["user_id"] if isinstance(row, dict) else row[0]
        uids.append(uid)
    return _unique_user_ids(uids)


async def get_tab1_permission_user_ids_async(
    session: AsyncSession, permission_code: str,
) -> List[int]:
    """AsyncSession：持指定 tab1 操作权限的用户 id。"""
    result = await session.execute(
        text(TAB1_PERMISSION_USER_IDS_SQL),
        {"permission_code": permission_code, "permission_type": PERM_TYPE_TAB1},
    )
    return _unique_user_ids([row.user_id for row in result.all()])


async def get_prepay_confirm_user_ids_async(session: AsyncSession) -> List[int]:
    """§2.2.5：持「确认预付」操作权限的用户（财务）。"""
    return await get_tab1_permission_user_ids_async(session, PERM_PREPAY_CONFIRM)


def get_prepay_confirm_user_ids(cursor) -> List[int]:
    return get_tab1_permission_user_ids(cursor, PERM_PREPAY_CONFIRM)


async def get_quote_submit_date(session: AsyncSession, order_id: int) -> Optional[datetime.date]:
    """报价审核待办：取最近一次「提交报价审核」日志日期作为提交审核日期。"""
    row = (
        await session.execute(
            select(DistributionOrderStatusLog.create_time)
            .where(
                DistributionOrderStatusLog.order_id == order_id,
                DistributionOrderStatusLog.action_code == ACTION_QUOTE_SUBMIT,
            )
            .order_by(
                desc(DistributionOrderStatusLog.create_time),
                desc(DistributionOrderStatusLog._id),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if isinstance(row, datetime.datetime):
        return row.date()
    return _coerce_date(row)


async def get_current_step_approver_user_ids(
    session: AsyncSession,
    order: DistributionOrder,
) -> List[int]:
    """
    §2.2.2 / §2.2.4：当前审批环节待办接收人。

    - 环节配置为「直线上级」→ quote_lm_user_id / order_lm_user_id
    - 环节配置为「办事角色」→ 按客户国家 + chain + step 查 user_business_role_permission
    """
    chain_code = order.current_chain_code
    step_no = order.current_step
    if chain_code is None or step_no is None:
        return []

    chain_code = int(chain_code)
    step_no = int(step_no)
    steps_raw = await _load_approval_steps(session, chain_code)
    step_cfg = _find_approval_step_by_no(steps_raw, step_no)
    if step_cfg is None:
        return []

    if int(step_cfg.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
        mgr_id = line_manager_user_id_for_chain(order, chain_code)
        return _unique_user_ids([mgr_id] if mgr_id else [])

    country = (order.customer_country or "").strip()
    if not country:
        country = (
            await get_customer_country(session, order.offline_customer_id) or ""
        ).strip()
    if not country:
        return []

    uids = await get_role_step_approver_user_ids(
        session, order, chain_code, step_no, country=country,
    )
    return _unique_user_ids(uids)


# ── 单条推送 ──────────────────────────────────────────────────────────────────


async def produce_quote_approval_todo(
    session: AsyncSession,
    order: DistributionOrder,
    *,
    request: Any = None,
    sender: Any = None,
) -> tuple:
    user_ids = await get_current_step_approver_user_ids(session, order)
    if not user_ids:
        return False, "当前报价审核环节无待办接收人"
    submit_date = await get_quote_submit_date(session, int(order._id))
    todo_data = build_quote_approval_todo_data(
        order, user_ids, submit_date,
        current_step=int(order.current_step),
    )
    return await _produce_distribution_order_todo(
        todo_data, session, request=request, sender=sender,
    )


async def produce_order_approval_todo(
    session: AsyncSession,
    order: DistributionOrder,
    *,
    request: Any = None,
    sender: Any = None,
) -> tuple:
    user_ids = await get_current_step_approver_user_ids(session, order)
    if not user_ids:
        return False, "当前订单审核环节无待办接收人"
    todo_data = build_order_approval_todo_data(
        order, user_ids, current_step=int(order.current_step),
    )
    return await _produce_distribution_order_todo(
        todo_data, session, request=request, sender=sender,
    )


async def produce_prepay_confirm_todo(
    item: Union[Mapping[str, Any], DistributionOrder],
    user_ids: Sequence[int],
    *,
    request: Any = None,
    sender: Any = None,
) -> tuple:
    if not user_ids:
        return False, "无确认预付权限用户"
    todo_data = build_prepay_confirm_todo_data(item, user_ids)
    return await _produce_todo(todo_data, request=request, sender=sender)


async def produce_payment_confirm_todo(
    order: DistributionOrder,
    *,
    request: Any = None,
    sender: Any = None,
) -> tuple:
    creator_id = order.create_by
    user_ids = _unique_user_ids([creator_id])
    if not user_ids:
        return False, "订单发起人不存在，无法推送回款待办"
    todo_data = build_payment_confirm_todo_data(order, user_ids)
    return await _produce_todo(todo_data, request=request, sender=sender)


async def _mark_quote_todo_synced(
    session: AsyncSession, order_id: int, step: int,
) -> None:
    await session.execute(
        update(DistributionOrder)
        .where(DistributionOrder._id == order_id)
        .values(quote_approval_todo_synced_step=int(step))
    )


async def _mark_order_todo_synced(
    session: AsyncSession, order_id: int, step: int,
) -> None:
    await session.execute(
        update(DistributionOrder)
        .where(DistributionOrder._id == order_id)
        .values(order_approval_todo_synced_step=int(step))
    )


async def _mark_prepay_todo_synced(session: AsyncSession, order_id: int) -> None:
    await session.execute(
        update(DistributionOrder)
        .where(DistributionOrder._id == order_id)
        .values(prepay_todo_synced=1)
    )


async def _mark_payment_todo_synced(session: AsyncSession, order_id: int) -> None:
    await session.execute(
        update(DistributionOrder)
        .where(DistributionOrder._id == order_id)
        .values(payment_todo_synced=1)
    )


async def _realtime_push_quote_approval(
    request: Any, session: AsyncSession, order: DistributionOrder,
) -> None:
    """§2.2.2：推送当前环节报价审核待办。"""
    ret, msg = await produce_quote_approval_todo(
        session, order, request=request,
    )
    if ret and order.current_step is not None:
        await _mark_quote_todo_synced(session, int(order._id), int(order.current_step))
    elif not ret:
        logger.warning(
            "报价审核待办实时推送失败 order_id=%s: %s" % (order._id, msg),
        )


async def _realtime_push_order_approval(
    request: Any, session: AsyncSession, order: DistributionOrder,
) -> None:
    """§2.2.4：推送当前环节订单审核待办。"""
    ret, msg = await produce_order_approval_todo(
        session, order, request=request,
    )
    if ret and order.current_step is not None:
        await _mark_order_todo_synced(session, int(order._id), int(order.current_step))
    elif not ret:
        logger.warning(
            "订单审核待办实时推送失败 order_id=%s: %s" % (order._id, msg),
        )


async def _realtime_push_prepay_confirm(
    request: Any, session: AsyncSession, order: DistributionOrder,
) -> None:
    """§2.2.5：推送确认预付待办给财务。"""
    user_ids = await get_prepay_confirm_user_ids_async(session)
    todo_data = build_prepay_confirm_todo_data(order, user_ids)
    ret, msg = await _produce_distribution_order_todo(
        todo_data, session, request=request,
    )
    if ret:
        await _mark_prepay_todo_synced(session, int(order._id))
    elif not ret:
        logger.warning(
            "确认预付待办实时推送失败 order_id=%s: %s" % (order._id, msg),
        )


async def _realtime_push_payment_confirm(
    request: Any, session: AsyncSession, order: DistributionOrder,
) -> None:
    """§2.2.8：推送待回款待办给发起人。"""
    creator_id = order.create_by
    user_ids = _unique_user_ids([creator_id])
    if not user_ids:
        logger.warning("回款待办实时推送失败 order_id=%s: 订单发起人不存在" % order._id)
        return
    todo_data = build_payment_confirm_todo_data(order, user_ids)
    ret, msg = await _produce_distribution_order_todo(
        todo_data, session, request=request,
    )
    if ret:
        await _mark_payment_todo_synced(session, int(order._id))
    elif not ret:
        logger.warning(
            "回款待办实时推送失败 order_id=%s: %s" % (order._id, msg),
        )


async def handle_approval_todos_realtime(
    request: Any,
    session: AsyncSession,
    order_id: int,
    action: int,
    *,
    from_step: Optional[int],
    from_status: int,
) -> None:
    """
    审批类接口 commit 后调用：关闭上一环节待办 + 按需创建下一环节/阶段待办。

    from_step / from_status 为流转前快照（由 view 在 apply_transition 前读取）。
    """
    if request is None:
        return

    order = await _load_order(session, order_id)
    oid = int(order_id)

    # ── 报价链 ──────────────────────────────────────────────────────────────
    if action in (
        ACTION_QUOTE_APPROVE, ACTION_QUOTE_REJECT, ACTION_QUOTE_WITHDRAW,
    ):
        if from_step is not None and from_status == STATUS_QUOTE_REVIEW:
            await complete_distribution_order_todo(
                request,
                todo_keywords=TODO_SCENE_QUOTE_APPROVAL,
                todo_step=TODO_SCENE_QUOTE_APPROVAL,
                related_id=quote_approval_related_id(oid, int(from_step)),
            )

    if action == ACTION_QUOTE_SUBMIT:
        if int(order.status) == STATUS_QUOTE_REVIEW and order.current_step is not None:
            await _realtime_push_quote_approval(request, session, order)
        return

    if action in (
        ACTION_QUOTE_APPROVE, ACTION_QUOTE_REJECT, ACTION_QUOTE_WITHDRAW,
    ):
        if int(order.status) == STATUS_QUOTE_REVIEW and order.current_step is not None:
            await _realtime_push_quote_approval(request, session, order)
        return

    # ── 订单链 ──────────────────────────────────────────────────────────────
    if action in (
        ACTION_ORDER_APPROVE, ACTION_ORDER_REJECT, ACTION_ORDER_WITHDRAW,
    ):
        if from_step is not None and from_status == STATUS_ORDER_REVIEW:
            await complete_distribution_order_todo(
                request,
                todo_keywords=TODO_SCENE_ORDER_APPROVAL,
                todo_step=TODO_SCENE_ORDER_APPROVAL,
                related_id=order_approval_related_id(oid, int(from_step)),
            )

    if action == ACTION_ORDER_SUBMIT:
        if int(order.status) == STATUS_ORDER_REVIEW and order.current_step is not None:
            await _realtime_push_order_approval(request, session, order)
        return

    if action in (
        ACTION_ORDER_APPROVE, ACTION_ORDER_REJECT, ACTION_ORDER_WITHDRAW,
    ):
        if int(order.status) == STATUS_ORDER_REVIEW and order.current_step is not None:
            await _realtime_push_order_approval(request, session, order)
            return
        if action == ACTION_ORDER_APPROVE and int(order.status) == STATUS_PREPAY:
            await _realtime_push_prepay_confirm(request, session, order)


async def handle_fulfillment_todos_realtime(
    request: Any,
    session: AsyncSession,
    order_id: int,
    *,
    event: str,
) -> None:
    """
    履约/财务接口 commit 后调用。

    event:
      - prepay_done   确认预付完成 → 关闭预付待办
      - receive_done  确认实收进入待回款 → 推送回款待办
      - payment_done  确认回款完成 → 关闭回款待办
    """
    if request is None:
        return

    oid = int(order_id)
    if event == "prepay_done":
        await complete_distribution_order_todo(
            request,
            todo_keywords=TODO_SCENE_PREPAY_CONFIRM,
            todo_step=TODO_SCENE_PREPAY_CONFIRM,
            related_id=str(oid),
        )
        return

    if event == "payment_done":
        await complete_distribution_order_todo(
            request,
            todo_keywords=TODO_SCENE_PAYMENT_CONFIRM,
            todo_step=TODO_SCENE_PAYMENT_CONFIRM,
            related_id=str(oid),
        )
        return

    if event == "receive_done":
        order = await _load_order(session, oid)
        await _realtime_push_payment_confirm(request, session, order)
