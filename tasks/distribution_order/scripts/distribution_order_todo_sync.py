# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/29
# @Author  : Zhu Yaming
# @File    : distribution_order_todo_sync.py
# @Description : 分销订单首页待办兜底扫描（定时脚本专用，与 view 内实时推送分离）

主路径为接口 commit 后 ``handle_*_realtime`` 实时推送；本模块仅补推未同步记录。

合入主仓路径：
``apps/system/distribution_order/scripts/distribution_order_todo_sync.py``
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.system.distribution_order.distribution_order_todo import (
    _produce_distribution_order_todo,
    build_payment_confirm_todo_data,
    build_prepay_confirm_todo_data,
    get_prepay_confirm_user_ids_async,
    produce_order_approval_todo,
    produce_quote_approval_todo,
)
from apps.system.distribution_order.distribution_order_workflow_engine import (
    STATUS_ORDER_REVIEW,
    STATUS_PENDING_PAYMENT,
    STATUS_PREPAY,
    STATUS_QUOTE_REVIEW,
)
from apps.system.distribution_order.models import DistributionOrder

SCENE_ALL = "all"
SCENE_QUOTE_APPROVAL = "quote_approval"
SCENE_ORDER_APPROVAL = "order_approval"
SCENE_PREPAY_CONFIRM = "prepay_confirm"
SCENE_PAYMENT_CONFIRM = "payment_confirm"

SCENES = (
    SCENE_ALL,
    SCENE_QUOTE_APPROVAL,
    SCENE_ORDER_APPROVAL,
    SCENE_PREPAY_CONFIRM,
    SCENE_PAYMENT_CONFIRM,
)


def _needs_approval_todo_sync(order: DistributionOrder, synced_step_attr: str) -> bool:
    """审批类：当前环节与已同步环节不一致时需推送（含首次进入审核）。"""
    if order.current_step is None:
        return False
    synced = getattr(order, synced_step_attr, None)
    if synced is None:
        return True
    try:
        return int(synced) != int(order.current_step)
    except (TypeError, ValueError):
        return True


async def _scan_with_sender(
    session: AsyncSession,
    handler: Callable[[AsyncSession, object], int],
) -> int:
    """脚本兜底扫描：TodoQueueSender() 无 request，走自建 Redis 连接。"""
    from apps.common.service.todo_queue_sender import TodoQueueSender

    sender = TodoQueueSender()
    synced = 0
    try:
        synced = await handler(session, sender)
    finally:
        await sender.close()
    return synced


async def _run_with_session(
    session: Optional[AsyncSession],
    runner: Callable[[AsyncSession], int],
) -> int:
    if session is not None:
        return await runner(session)
    from core.db.session import get_async_session

    total = 0
    async for db_session in get_async_session():
        total = await runner(db_session)
        await db_session.commit()
        break
    return total


async def async_quote_approval_todo(session: Optional[AsyncSession] = None) -> int:
    """§2.2.2 兜底：扫描未同步的报价审核待办。"""

    async def _run(db: AsyncSession, sender) -> int:
        rows = (
            await db.execute(
                select(DistributionOrder).where(
                    DistributionOrder.status == STATUS_QUOTE_REVIEW,
                    DistributionOrder.is_delete == 0,
                    DistributionOrder.current_step.isnot(None),
                )
            )
        ).scalars().all()
        count = 0
        for order in rows:
            if not _needs_approval_todo_sync(order, "quote_approval_todo_synced_step"):
                continue
            try:
                ret, msg = await produce_quote_approval_todo(
                    db, order, sender=sender,
                )
                if ret:
                    await db.execute(
                        update(DistributionOrder)
                        .where(DistributionOrder._id == order._id)
                        .values(quote_approval_todo_synced_step=int(order.current_step))
                    )
                    count += 1
                else:
                    logger.error(
                        "报价审核待办推送失败: order_id=%s, %s" % (order._id, msg),
                    )
            except Exception as e:
                logger.error("报价审核待办异常: order_id=%s, %s" % (order._id, e))
        return count

    async def _runner(db: AsyncSession) -> int:
        return await _scan_with_sender(db, _run)

    return await _run_with_session(session, _runner)


async def async_order_approval_todo(session: Optional[AsyncSession] = None) -> int:
    """§2.2.4 兜底：扫描未同步的订单审核待办。"""

    async def _run(db: AsyncSession, sender) -> int:
        rows = (
            await db.execute(
                select(DistributionOrder).where(
                    DistributionOrder.status == STATUS_ORDER_REVIEW,
                    DistributionOrder.is_delete == 0,
                    DistributionOrder.current_step.isnot(None),
                )
            )
        ).scalars().all()
        count = 0
        for order in rows:
            if not _needs_approval_todo_sync(order, "order_approval_todo_synced_step"):
                continue
            try:
                ret, msg = await produce_order_approval_todo(
                    db, order, sender=sender,
                )
                if ret:
                    await db.execute(
                        update(DistributionOrder)
                        .where(DistributionOrder._id == order._id)
                        .values(order_approval_todo_synced_step=int(order.current_step))
                    )
                    count += 1
                else:
                    logger.error(
                        "订单审核待办推送失败: order_id=%s, %s" % (order._id, msg),
                    )
            except Exception as e:
                logger.error("订单审核待办异常: order_id=%s, %s" % (order._id, e))
        return count

    async def _runner(db: AsyncSession) -> int:
        return await _scan_with_sender(db, _run)

    return await _run_with_session(session, _runner)


async def async_prepay_confirm_todo(session: Optional[AsyncSession] = None) -> int:
    """§2.2.5 兜底：扫描未同步的确认预付待办。"""

    async def _run(db: AsyncSession, sender) -> int:
        user_ids = await get_prepay_confirm_user_ids_async(db)
        if not user_ids:
            logger.warning("确认预付待办：未解析到权限用户，跳过")
            return 0
        rows = (
            await db.execute(
                select(DistributionOrder).where(
                    DistributionOrder.status == STATUS_PREPAY,
                    DistributionOrder.prepay_todo_synced == 0,
                    DistributionOrder.is_delete == 0,
                )
            )
        ).scalars().all()
        count = 0
        for order in rows:
            try:
                todo_data = build_prepay_confirm_todo_data(order, user_ids)
                ret, msg = await _produce_distribution_order_todo(
                    todo_data, db, sender=sender,
                )
                if ret:
                    await db.execute(
                        update(DistributionOrder)
                        .where(DistributionOrder._id == order._id)
                        .values(prepay_todo_synced=1)
                    )
                    count += 1
                else:
                    logger.error(
                        "确认预付待办推送失败: order_id=%s, %s" % (order._id, msg),
                    )
            except Exception as e:
                logger.error("确认预付待办异常: order_id=%s, %s" % (order._id, e))
        return count

    async def _runner(db: AsyncSession) -> int:
        return await _scan_with_sender(db, _run)

    return await _run_with_session(session, _runner)


async def async_payment_confirm_todo(session: Optional[AsyncSession] = None) -> int:
    """§2.2.8 兜底：扫描未同步的待回款待办。"""

    async def _run(db: AsyncSession, sender) -> int:
        rows = (
            await db.execute(
                select(DistributionOrder).where(
                    DistributionOrder.status == STATUS_PENDING_PAYMENT,
                    DistributionOrder.payment_todo_synced == 0,
                    DistributionOrder.is_delete == 0,
                )
            )
        ).scalars().all()
        count = 0
        for order in rows:
            try:
                creator_id = order.create_by
                if not creator_id:
                    logger.error("回款待办推送失败: order_id=%s, 订单发起人不存在" % order._id)
                    continue
                todo_data = build_payment_confirm_todo_data(order, [int(creator_id)])
                ret, msg = await _produce_distribution_order_todo(
                    todo_data, db, sender=sender,
                )
                if ret:
                    await db.execute(
                        update(DistributionOrder)
                        .where(DistributionOrder._id == order._id)
                        .values(payment_todo_synced=1)
                    )
                    count += 1
                else:
                    logger.error(
                        "回款待办推送失败: order_id=%s, %s" % (order._id, msg),
                    )
            except Exception as e:
                logger.error("回款待办异常: order_id=%s, %s" % (order._id, e))
        return count

    async def _runner(db: AsyncSession) -> int:
        return await _scan_with_sender(db, _run)

    return await _run_with_session(session, _runner)


_SCENE_RUNNERS = {
    SCENE_QUOTE_APPROVAL: async_quote_approval_todo,
    SCENE_ORDER_APPROVAL: async_order_approval_todo,
    SCENE_PREPAY_CONFIRM: async_prepay_confirm_todo,
    SCENE_PAYMENT_CONFIRM: async_payment_confirm_todo,
}


async def async_distribution_order_todo(
    session: Optional[AsyncSession] = None,
    scenes: Optional[List[str]] = None,
) -> Dict[str, int]:
    """
    待办兜底扫描统一入口。

    :param scenes: 指定场景列表，默认四类全扫；``all`` 或 None 表示全扫。
    """
    if scenes and SCENE_ALL not in scenes:
        active = [s for s in scenes if s in _SCENE_RUNNERS]
    else:
        active = list(_SCENE_RUNNERS.keys())

    if session is not None:
        result = {}
        for name in active:
            result[name] = await _SCENE_RUNNERS[name](session)
        return result

    from core.db.session import get_async_session

    result = {name: 0 for name in active}
    async for db_session in get_async_session():
        for name in active:
            result[name] = await _SCENE_RUNNERS[name](db_session)
        await db_session.commit()
        break
    return result
