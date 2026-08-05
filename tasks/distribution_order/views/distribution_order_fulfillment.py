# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/27
# @Author  : Zhu Yaming
# @File    : distribution_order_fulfillment.py
# @Description : 预付/实收/回款/拆单/下发/手工调整 POST 接口
"""
from typing import Any, Dict

from fastapi import Depends, Request
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_async_session

from apps.system.reports.view.common_func import get_common_shop_dict

from apps.system.distribution_order.auth import oauth2_scheme
from apps.system.distribution_order.distribution_order_service import (
    _load_order,
    build_order_save_data,
    get_distribution_order_detail,
)
from apps.system.distribution_order.distribution_order_fulfillment_service import (
    confirm_payment, confirm_prepay, confirm_receive,
    dispatch_order, list_adjustments, save_adjustments, split_order, dispatch_order_test,
)
from apps.system.distribution_order.distribution_order_line_service import list_line_details
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.models import (
    DistributionOrderBalancePayment, DistributionOrderPrepayment,
)
from apps.system.distribution_order.schemas import (
    AdjustmentBatchSaveIn, AdjustmentIn, AdjustmentLineIn,
    DispatchIn, PaymentConfirmIn, PaymentConfirmOut,
    PrepayConfirmIn, PrepayConfirmOut, ReceiveConfirmIn, SplitIn,
    confirm_body_log_snapshot, receive_confirm_body_log_snapshot,
    serialize_confirm_record_log_snapshot,
)
from apps.system.distribution_order.translate import (
    get_translaiton_dict_from_request, translate_text,
)
from apps.system.distribution_order.operation_log import (
    LOG_SCOPE_ADJUSTMENT,
    LOG_SCOPE_ORDER_DETAIL,
    LOG_SCOPE_PAYMENT_CONFIRM,
    LOG_SCOPE_PREPAY_CONFIRM,
    LOG_SCOPE_RECEIVE_CONFIRM,
    LOG_SCOPE_QUOTE_DETAIL,
    get_operator_display_name,
    log_distribution_order_create,
    log_distribution_order_create_with_modules,
    log_distribution_order_update,
    to_log_dict,
)

def _adjustment_rows_by_ids(
    rows: list, row_ids: list,
) -> list:
    id_set = {int(i) for i in row_ids}
    return [r for r in rows if int(r.get("_id") or 0) in id_set]


async def _log_adjustment_save(
    session: AsyncSession,
    *,
    username: str,
    order_id: int,
    old_rows: list,
    new_rows: list,
    created_ids: list,
    updated_ids: list,
    deleted_ids: list,
) -> None:
    """每次保存只记一条：含更新/删除→整表 diff（更新）；仅新增→新建快照。"""
    if not created_ids and not updated_ids and not deleted_ids:
        return
    if updated_ids or deleted_ids:
        await log_distribution_order_update(
            session, username=username, order_id=order_id,
            old_data={LOG_SCOPE_ADJUSTMENT: old_rows},
            new_data={LOG_SCOPE_ADJUSTMENT: new_rows},
        )
        return
    created_snap = _adjustment_rows_by_ids(new_rows, created_ids)
    if created_snap:
        await log_distribution_order_create(
            session, username=username, order_id=order_id,
            scope=LOG_SCOPE_ADJUSTMENT, snapshot=created_snap,
        )


async def distribution_order_prepay_confirm(
    request: Request,
    body: PrepayConfirmIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    username = get_operator_display_name(request)
    operator_id = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    try:
        data = await confirm_prepay(inter_session, body, operator_id=operator_id)
        row = (
            await inter_session.execute(
                select(DistributionOrderPrepayment).where(
                    DistributionOrderPrepayment.order_id == body.order_id,
                )
            )
        ).scalar_one_or_none()
        snapshot = serialize_confirm_record_log_snapshot(row, PrepayConfirmOut)
        if not snapshot:
            snapshot = confirm_body_log_snapshot(body)
        await log_distribution_order_create(
            inter_session, username=username, order_id=body.order_id,
            scope=LOG_SCOPE_PREPAY_CONFIRM, snapshot=snapshot,
        )
        await inter_session.commit()
        try:
            from apps.system.distribution_order.distribution_order_todo import (
                handle_fulfillment_todos_realtime,
            )
            await handle_fulfillment_todos_realtime(
                request, inter_session, int(body.order_id), event="prepay_done",
            )
        except Exception as todo_exc:
            logger.error(
                f"分销订单待办关闭失败 order_id={body.order_id}: {todo_exc}",
            )
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {"code": 40000, "msg": translate_text(exc.msg, is_trans, translation_dict), "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"确认预付失败：{e}")
        return {"code": 40000, "msg": translate_text("操作失败", is_trans, translation_dict), "data": {}}
    return {"code": 200, "msg": translate_text("操作成功", is_trans, translation_dict), "data": data}


async def distribution_order_receive_confirm(
    request: Request,
    body: ReceiveConfirmIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    username = get_operator_display_name(request)
    operator_id = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    try:
        data = await confirm_receive(inter_session, body, operator_id=operator_id)
        order_lines = await list_line_details(inter_session, body.order_id, "order")
        by_id = {
            int(r["_id"]): r for r in order_lines
            if r.get("_id") is not None
        }
        await log_distribution_order_create(
            inter_session, username=username, order_id=body.order_id,
            scope=LOG_SCOPE_RECEIVE_CONFIRM,
            snapshot=receive_confirm_body_log_snapshot(body, by_id),
        )
        await inter_session.commit()
        try:
            from apps.system.distribution_order.distribution_order_todo import (
                handle_fulfillment_todos_realtime,
            )
            await handle_fulfillment_todos_realtime(
                request, inter_session, int(body.order_id), event="receive_done",
            )
            await inter_session.commit()
        except Exception as todo_exc:
            logger.error(
                f"分销订单待办实时处理失败 order_id={body.order_id}: {todo_exc}",
            )
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {"code": 40000, "msg": translate_text(exc.msg, is_trans, translation_dict), "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"确认实收失败：{e}")
        return {"code": 40000, "msg": translate_text("操作失败", is_trans, translation_dict), "data": {}}
    return {"code": 200, "msg": translate_text("操作成功", is_trans, translation_dict), "data": data}


async def distribution_order_payment_confirm(
    request: Request,
    body: PaymentConfirmIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    username = get_operator_display_name(request)
    operator_id = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    try:
        row = (
            await inter_session.execute(
                select(DistributionOrderBalancePayment).where(
                    DistributionOrderBalancePayment.order_id == body.order_id,
                )
            )
        ).scalar_one_or_none()
        old_data = serialize_confirm_record_log_snapshot(row, PaymentConfirmOut)
        data = await confirm_payment(inter_session, body, operator_id=operator_id)
        new_data = confirm_body_log_snapshot(body)
        if old_data:
            await log_distribution_order_update(
                inter_session, username=username, order_id=body.order_id,
                scope=LOG_SCOPE_PAYMENT_CONFIRM, old_data=old_data, new_data=new_data,
            )
        else:
            await log_distribution_order_create(
                inter_session, username=username, order_id=body.order_id,
                scope=LOG_SCOPE_PAYMENT_CONFIRM, snapshot=new_data,
            )
        await inter_session.commit()
        try:
            from apps.system.distribution_order.distribution_order_todo import (
                handle_fulfillment_todos_realtime,
            )
            await handle_fulfillment_todos_realtime(
                request, inter_session, int(body.order_id), event="payment_done",
            )
        except Exception as todo_exc:
            logger.error(
                f"分销订单待办关闭失败 order_id={body.order_id}: {todo_exc}",
            )
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {"code": 40000, "msg": translate_text(exc.msg, is_trans, translation_dict), "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"确认回款失败：{e}")
        return {"code": 40000, "msg": translate_text("操作失败", is_trans, translation_dict), "data": {}}
    return {"code": 200, "msg": translate_text("操作成功", is_trans, translation_dict), "data": data}


async def distribution_order_dispatch(
    request: Request,
    body: DispatchIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    username = get_operator_display_name(request)
    operator_id = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    try:
        shop_dict = await get_common_shop_dict(request)
        old_main = await _split_main_snapshot(inter_session, body.order_id)
        old_order_lines = await list_line_details(inter_session, body.order_id, "order")
        data = await dispatch_order_test(
            inter_session, body, operator_id=operator_id,operator_name=username ,shop_dict=shop_dict,
        )
        new_main = await _split_main_snapshot(inter_session, body.order_id)
        new_order_lines = await list_line_details(inter_session, body.order_id, "order")
        await log_distribution_order_update(
            inter_session, username=username, order_id=body.order_id,
            old_data={
                **old_main,
                LOG_SCOPE_ORDER_DETAIL: to_log_dict(old_order_lines) or [],
            },
            new_data={
                **new_main,
                LOG_SCOPE_ORDER_DETAIL: to_log_dict(new_order_lines) or [],
            },
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {"code": 40000, "msg": translate_text(exc.msg, is_trans, translation_dict), "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"下发千易失败：{e}")
        return {"code": 40000, "msg": translate_text("操作失败", is_trans, translation_dict), "data": {}}
    return {"code": 200, "msg": translate_text("操作成功", is_trans, translation_dict), "data": data}


_SPLIT_MAIN_EXCLUDE = frozenset({
    "quote_details", "order_details",
    "quote_approval_flow", "order_approval_flow",
})

def _split_line_snapshot(quote_lines, order_lines) -> Dict[str, Any]:
    return {
        LOG_SCOPE_QUOTE_DETAIL: to_log_dict(quote_lines) or [],
        LOG_SCOPE_ORDER_DETAIL: to_log_dict(order_lines) or [],
    }


async def _split_main_snapshot(
    session: AsyncSession, order_id: int,
) -> Dict[str, Any]:
    detail = await get_distribution_order_detail(session, order_id)
    return {
        k: v for k, v in detail.items()
        if k not in _SPLIT_MAIN_EXCLUDE
    }


def _split_parent_update_snapshot(
    main: Dict[str, Any], quote_lines, order_lines,
) -> Dict[str, Any]:
    snap = dict(main)
    snap.update(_split_line_snapshot(quote_lines, order_lines))
    return snap


async def distribution_order_split(
    request: Request,
    body: SplitIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    username = get_operator_display_name(request)
    operator_id = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    try:
        # 拆单会同时影响父单订单明细（扣减 qty）并生成子单订单明细（新行）；
        # split_order 返回值不包含明细，因此这里必须在 view 内补充查询。
        parent_order_lines_old = await list_line_details(inter_session, int(body.order_id), "order")
        parent_quote_lines_old = await list_line_details(inter_session, int(body.order_id), "quote")
        parent_main_old = await _split_main_snapshot(inter_session, int(body.order_id))
        data = await split_order(inter_session, body, operator_id=operator_id)
        child_order_id = int((data or {}).get("child_order_id") or 0)
        parent_order_lines_new = await list_line_details(inter_session, int(body.order_id), "order")
        parent_quote_lines_new = await list_line_details(inter_session, int(body.order_id), "quote")
        parent_main_new = await _split_main_snapshot(inter_session, int(body.order_id))
        child_order_lines = (
            await list_line_details(inter_session, child_order_id, "order")
            if child_order_id > 0 else []
        )
        child_quote_lines = (
            await list_line_details(inter_session, child_order_id, "quote")
            if child_order_id > 0 else []
        )

        # 1) 子单：一条新建日志（主表 + order_detail + quote_detail）
        if child_order_id > 0:
            modules = {}
            if child_order_lines:
                modules[LOG_SCOPE_ORDER_DETAIL] = to_log_dict(child_order_lines)
            if child_quote_lines:
                modules[LOG_SCOPE_QUOTE_DETAIL] = to_log_dict(child_quote_lines)
            await log_distribution_order_create_with_modules(
                inter_session,
                username=username,
                order_id=child_order_id,
                main_snapshot=await _split_main_snapshot(
                    inter_session, child_order_id,
                ),
                modules=modules,
            )

        # 2) 父单：主表 + 定价/订单明细 更新
        old_data = _split_parent_update_snapshot(
            parent_main_old, parent_quote_lines_old, parent_order_lines_old,
        )
        new_data = _split_parent_update_snapshot(
            parent_main_new, parent_quote_lines_new, parent_order_lines_new,
        )

        await log_distribution_order_update(
            inter_session,
            username=username,
            order_id=int(body.order_id),
            old_data=old_data,
            new_data=new_data,
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {"code": 40000, "msg": translate_text(exc.msg, is_trans, translation_dict), "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"拆单失败：{e}")
        return {"code": 40000, "msg": translate_text("操作失败", is_trans, translation_dict), "data": {}}
    return {"code": 200, "msg": translate_text("操作成功", is_trans, translation_dict), "data": data}


async def _adjustment_save(
    request: Request,
    body: AdjustmentBatchSaveIn,
    session: AsyncSession,
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    username = get_operator_display_name(request)
    operator_id = getattr(getattr(request, "user", None), "id", None)
    try:
        old_rows = await list_adjustments(session, body.order_id)
        data = await save_adjustments(session, body, operator_id=operator_id)
        new_rows = await list_adjustments(session, body.order_id)
        await _log_adjustment_save(
            session,
            username=username,
            order_id=body.order_id,
            old_rows=old_rows,
            new_rows=new_rows,
            created_ids=data.get("created_ids") or [],
            updated_ids=data.get("updated_ids") or [],
            deleted_ids=data.get("deleted_ids") or [],
        )
        order = await _load_order(session, body.order_id)
        await session.commit()
    except DistributionOrderError as exc:
        await session.rollback()
        msg = translate_text(exc.msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    except Exception as e:
        await session.rollback()
        logger.error(f"手工调整保存失败：{e}")
        msg = translate_text("保存失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("保存成功", is_trans, translation_dict)
    resp_data = build_order_save_data(int(body.order_id), order.order_sn)
    resp_data.update(data or {})
    return {"code": 200, "msg": msg, "data": resp_data}


async def distribution_order_adjustment_save(
    request: Request,
    body: AdjustmentBatchSaveIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _adjustment_save(request, body, inter_session)


async def distribution_order_adjustment_add(
    request: Request,
    body: AdjustmentIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
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
    result = await _adjustment_save(request, batch, inter_session)
    if result.get("code") != 200:
        return result
    data = result.get("data") or {}
    adj_ids = data.get("adjustment_ids") or []
    return {
        "code": 200,
        "msg": result.get("msg"),
        "data": {
            **build_order_save_data(int(body.order_id), data.get("order_sn")),
            "adjustment_id": int(adj_ids[0]) if adj_ids else None,
            "seq": data.get("last_seq"),
            "adjusted_balance_after": data.get("adjusted_balance_after"),
        },
    }
