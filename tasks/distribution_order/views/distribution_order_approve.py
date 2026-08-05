# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/1
# @Author  : Zhu Yaming
# @File    : distribution_order_approve.py
# @Description : 报价/订单审批流查询与 submit/approve/reject/withdraw
"""
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_async_session

from apps.system.distribution_order.auth import oauth2_scheme
from apps.system.distribution_order.distribution_order_line_service import list_line_details
from apps.system.distribution_order.distribution_order_extent import get_table_config
from apps.system.distribution_order.distribution_order_workflow_engine import (
    ACTION_ORDER_APPROVE,
    ACTION_ORDER_REJECT,
    ACTION_ORDER_SUBMIT,
    ACTION_ORDER_WITHDRAW,
    ACTION_QUOTE_APPROVE,
    ACTION_QUOTE_REJECT,
    ACTION_QUOTE_SUBMIT,
    ACTION_QUOTE_WITHDRAW,
    CHAIN_PRICING,
    OPERATOR_APPROVER,
    OPERATOR_CREATOR,
    STATUS_DRAFT,
    STATUS_ORDER_REVIEW,
    STATUS_QUOTE_REVIEW,
    TRIGGER_MANUAL,
    _load_order,
    apply_transition,
    assert_chain_has_approvers,
    get_customer_country,
    normalize_line_manager_user_id,
    load_combined_workflow_bundle,
    load_order_workflow_bundle,
    load_quote_workflow_bundle,
    user_can_review_order,
)
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.schemas import (
    OrderSubmitIn, TransitionBody, TransitionOut,
)
from apps.system.reports.view.common_func import get_common_exchange_rate_dict
from apps.system.distribution_order.distribution_order_service import (
    get_distribution_order_detail,
    submit_distribution_order,
)
from apps.system.distribution_order.translate import (
    get_translaiton_dict_from_request, translate_all_output, translate_text,
)
from apps.system.distribution_order.operation_log import (
    get_operator_display_name,
    log_distribution_order_update,
)


def _extract_option_pairs(filter_value: Any, *, key: str) -> list:
    """从 filter_value 中抽取 options 的 (value,label)。"""
    pairs = []
    for item in filter_value or []:
        if not isinstance(item, dict):
            continue
        if item.get("key") != key:
            continue
        options = item.get("options") or item.get("search_list") or []
        for opt in options or []:
            if not isinstance(opt, dict):
                continue
            val = opt.get("value")
            label = opt.get("label")
            if isinstance(val, str) and val and isinstance(label, str) and label:
                pairs.append((val, label))
        break
    return pairs


def _assert_required_fields(
    order: Any,
    *,
    required_fields: Optional[list] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    if not required_fields:
        return
    td = translation_dict or {}
    tmpl = translate_text("字段不能为空：{field}", is_trans, td)
    for field_key, field_label in required_fields:
        if isinstance(order, dict):
            if field_key not in order:
                continue
            val = order.get(field_key)
        else:
            if not hasattr(order, field_key):
                continue
            val = getattr(order, field_key, None)
        label = translate_text(field_label, is_trans, td)
        if val is None:
            raise DistributionOrderError(40000, tmpl.format(field=label))
        if isinstance(val, str) and not val.strip():
            raise DistributionOrderError(40000, tmpl.format(field=label))
        if isinstance(val, (list, dict, tuple)) and not val:
            raise DistributionOrderError(40000, tmpl.format(field=label))

def _parse_reject_target(
    reject_to_info: Optional[Dict[str, Any]],
) -> Tuple[Optional[int], Optional[int]]:
    if not reject_to_info:
        return None, None
    to_status = reject_to_info.get("to_status")
    if to_status is not None and int(to_status) == STATUS_DRAFT:
        to_status = None
    to_step = reject_to_info.get("to_step_no")
    if to_step is None:
        to_step = reject_to_info.get("to_step")
    return to_step, to_status


async def _do_transition(
    session: AsyncSession,
    request: Request,
    body: TransitionBody,
    action: int,
    operator_role: int,
) -> Dict[str, Any]:
    order_id = body.order_id
    if not order_id or int(order_id) <= 0:
        raise DistributionOrderError(40000, "order_id 无效")
    user_id = getattr(getattr(request, "user", None), "id", None)
    reject_to_step, reject_to_status = _parse_reject_target(body.reject_to_info)
    try:
        _, meta, _msg = await apply_transition(
            session,
            order_id=int(order_id),
            action=action,
            operator_id=user_id,
            operator_role=operator_role,
            remark=body.remark,
            trigger_type=TRIGGER_MANUAL,
            chain_code=body.chain_code,
            reject_to_step=reject_to_step,
            reject_to_status=reject_to_status,
        )
    except ValueError as e:
        raise DistributionOrderError(40000, str(e))
    except RuntimeError as e:
        raise DistributionOrderError(40000, str(e))
    out = TransitionOut(
        order_id=int(order_id),
        from_status=int(meta["from_status"]),
        to_status=int(meta["to_status"]),
        current_chain_code=meta.get("current_chain_code"),
        current_step=meta.get("current_step"),
        total_steps=meta.get("total_steps"),
        message=meta.get("message") or "",
    )
    return out.dict()


async def _apply_quote_line_manager_from_body(
    session: AsyncSession,
    body: TransitionBody,
    operator_id: Optional[int],
) -> None:
    if "quote_lm_user_id" not in body.__fields_set__:
        return
    order = await _load_order(session, int(body.order_id))
    order.quote_lm_user_id = normalize_line_manager_user_id(
        body.quote_lm_user_id,
    )
    order.update_by = operator_id


async def _ensure_quote_submit_ready(
    session: AsyncSession,
    order_id: int,
    *,
    operator_id: Optional[int] = None,
    required_fields: Optional[list] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    order = await _load_order(session, order_id)
    if int(order.status) != STATUS_DRAFT:
        raise DistributionOrderError(40000, "当前状态不允许提交报价审核")
    lines = await list_line_details(session, order_id, "quote")
    if not lines:
        raise DistributionOrderError(40000, "报价明细不能为空")

    # 定价信息完整性校验：报价阶段仅校验 SKU + 单价，不校验数量及行金额
    td = translation_dict or {}
    tmpl = translate_text("报价明细定价信息未完整：{sku}-{field}", is_trans, td)
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        sku = (ln.get("sku") or "").strip()
        for field_key, field_label in (
            ("sku", "SKU"),
            ("price_with_vat", "含增值税单价"),
            ("price_without_vat", "不含增值税单价"),
        ):
            val = ln.get(field_key)
            if val is None or (isinstance(val, str) and not val.strip()):
                label = translate_text(field_label, is_trans, td)
                raise DistributionOrderError(
                    40000, tmpl.format(sku=sku or "-", field=label),
                )
    country = order.customer_country
    if not country:
        raise DistributionOrderError(40000, "客户国家未配置，无法提交审核")

    # 必填校验：按详情 dict 校验，确保快照字段（联系人/地址等）也能覆盖
    detail = await get_distribution_order_detail(session, order_id)
    _assert_required_fields(
        detail if isinstance(detail, dict) else order,
        required_fields=required_fields,
        is_trans=is_trans,
        translation_dict=translation_dict,
    )
    try:
        await assert_chain_has_approvers(
            session, country, CHAIN_PRICING, order,
        )
    except ValueError as e:
        raise DistributionOrderError(40000, str(e))


async def _ensure_review_permission(
    session: AsyncSession, order_id: int, user_id: int, in_review_status: int,
) -> None:
    order = await _load_order(session, order_id)
    if int(order.status) != in_review_status:
        raise DistributionOrderError(40000, "订单未到该审批流程")
    if not await user_can_review_order(session, order, user_id):
        raise DistributionOrderError(40300, "您暂无审批该订单的权限")


async def _post_transition(
    request: Request,
    body: TransitionBody,
    session: AsyncSession,
    action: int,
    operator_role: int,
    *,
    before=None,
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    order_id = int(body.order_id)
    try:
        order_before = await _load_order(session, order_id)
        prev_step = order_before.current_step
        prev_status = int(order_before.status)
        if before is not None:
            await before(session, body)
        data = await _do_transition(session, request, body, action, operator_role)
        await session.commit()
        try:
            from apps.system.distribution_order.distribution_order_todo import (
                handle_approval_todos_realtime,
            )
            await handle_approval_todos_realtime(
                request, session, order_id, action,
                from_step=prev_step, from_status=prev_status,
            )
            await session.commit()
        except Exception as todo_exc:
            logger.error(f"分销订单待办实时处理失败 order_id={order_id}: {todo_exc}")
    except DistributionOrderError as exc:
        await session.rollback()
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        await session.rollback()
        logger.error(f"审批操作失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    msg = translate_text("操作成功", is_trans, translation_dict)
    return {"code": 200, "msg": msg, "data": data}


@translate_all_output(
    modules=["offline_customer", "common", "msg"],
    translatable_fields=[
        "action_code_str", "from_status_str", "to_status_str",
        "operator_role_str", "role_name", "order_status_str",
        "approval_type_str",
    ],
    skip_fields=[],
)
async def distribution_order_approval_quote_flow(
    request: Request,
    order_id: int,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    if order_id <= 0:
        return {"code": 40000, "msg": "order_id 无效", "data": {}}
    try:
        bundle = await load_quote_workflow_bundle(inter_session, order_id)
    except ValueError as e:
        return {"code": 40000, "msg": str(e), "data": {}}
    except Exception as e:
        logger.error(f"报价审批流查询失败：{e}")
        return {"code": 40000, "msg": "获取审批流失败", "data": {}}
    return {"code": 200, "msg": "获取数据成功", "data": bundle}


@translate_all_output(
    modules=["offline_customer", "common", "msg"],
    translatable_fields=[
        "action_code_str", "from_status_str", "to_status_str",
        "operator_role_str", "role_name", "order_status_str",
        "approval_type_str",
    ],
    skip_fields=[],
)
async def distribution_order_approval_order_flow(
    request: Request,
    order_id: int,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    if order_id <= 0:
        return {"code": 40000, "msg": "order_id 无效", "data": {}}
    try:
        bundle = await load_order_workflow_bundle(inter_session, order_id)
    except ValueError as e:
        return {"code": 40000, "msg": str(e), "data": {}}
    except Exception as e:
        logger.error(f"订单审批流查询失败：{e}")
        return {"code": 40000, "msg": "获取审批流失败", "data": {}}
    return {"code": 200, "msg": "获取数据成功", "data": bundle}


@translate_all_output(
    modules=["offline_customer", "common", "msg"],
    translatable_fields=[
        "action_code_str", "from_status_str", "to_status_str",
        "operator_role_str", "role_name", "order_status_str",
        "approval_type_str",
    ],
    skip_fields=[],
)
async def distribution_order_approval_flow(
    request: Request,
    order_id: int,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    """统一审批流：报价+订单已审历史一并返回，步骤含审核类型。"""
    if order_id <= 0:
        return {"code": 40000, "msg": "order_id 无效", "data": {}}
    try:
        bundle = await load_combined_workflow_bundle(inter_session, order_id)
    except ValueError as e:
        return {"code": 40000, "msg": str(e), "data": {}}
    except Exception as e:
        logger.error(f"审批流查询失败：{e}")
        return {"code": 40000, "msg": "获取审批流失败", "data": {}}
    return {"code": 200, "msg": "获取数据成功", "data": bundle}


async def distribution_order_quote_submit(
    request: Request,
    body: TransitionBody,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    operator_id = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    table_base_data = await get_table_config(inter_session, request)
    filter_value = table_base_data.get("filter_value") or []
    required_fields = _extract_option_pairs(filter_value, key="validation_fields_quote")

    async def _before(session, b):
        await _ensure_quote_submit_ready(
            session,
            int(b.order_id),
            operator_id=operator_id,
            required_fields=required_fields,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
        await _apply_quote_line_manager_from_body(session, b, operator_id)

    return await _post_transition(
        request, body, inter_session, ACTION_QUOTE_SUBMIT, OPERATOR_CREATOR,
        before=_before,
    )


async def _assert_order_submit_required_fields(
    order_dict: Dict[str, Any],
    required_fields: Optional[list],
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    td = translation_dict or {}
    tmpl = translate_text("字段不能为空：{field}", is_trans, td)
    for field_key, field_label in required_fields or []:
        if field_key not in order_dict:
            continue
        val = order_dict.get(field_key)
        label = translate_text(field_label, is_trans, td)
        if val is None:
            raise DistributionOrderError(40000, tmpl.format(field=label))
        if isinstance(val, str) and not val.strip():
            raise DistributionOrderError(40000, tmpl.format(field=label))
        if isinstance(val, (list, dict, tuple)) and not val:
            raise DistributionOrderError(40000, tmpl.format(field=label))


async def distribution_order_order_submit(
    request: Request,
    body: OrderSubmitIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    operator_id = getattr(getattr(request, "user", None), "id", None)
    username = get_operator_display_name(request)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    try:
        table_base_data = await get_table_config(inter_session, request)
        filter_value = table_base_data.get("filter_value") or []
        required_fields = _extract_option_pairs(filter_value, key="validation_fields_order")
        old_data = await get_distribution_order_detail(inter_session, body.order_id)
        order_dict = old_data if isinstance(old_data, dict) else {}
        await _assert_order_submit_required_fields(
            order_dict, required_fields,
            is_trans=is_trans, translation_dict=translation_dict,
        )
        exchange_rate_dict = await get_common_exchange_rate_dict(request)
        data = await submit_distribution_order(
            inter_session, body, operator_id=operator_id,
            exchange_rate_dict=exchange_rate_dict,
        )
        new_data = await get_distribution_order_detail(inter_session, body.order_id)
        await log_distribution_order_update(
            inter_session, username=username, order_id=body.order_id,
            old_data=old_data, new_data=new_data,
        )
        await inter_session.commit()
        try:
            from apps.system.distribution_order.distribution_order_todo import (
                handle_approval_todos_realtime,
            )
            await handle_approval_todos_realtime(
                request, inter_session, int(body.order_id), ACTION_ORDER_SUBMIT,
                from_step=None, from_status=0,
            )
            await inter_session.commit()
        except Exception as todo_exc:
            logger.error(
                f"分销订单待办实时处理失败 order_id={body.order_id}: {todo_exc}",
            )
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"提交订单审核失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    msg = translate_text("操作成功", is_trans, translation_dict)
    return {"code": 200, "msg": msg, "data": data}


async def distribution_order_approval_quote_approve(
    request: Request,
    body: TransitionBody,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    uid = getattr(getattr(request, "user", None), "id", None)

    async def _before(session, b):
        await _ensure_review_permission(
            session, int(b.order_id), uid, STATUS_QUOTE_REVIEW,
        )

    return await _post_transition(
        request, body, inter_session, ACTION_QUOTE_APPROVE, OPERATOR_APPROVER,
        before=_before,
    )


async def distribution_order_approval_quote_reject(
    request: Request,
    body: TransitionBody,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    uid = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    if not (body.remark or "").strip():
        msg = translate_text("驳回时审批意见不能为空", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}

    async def _before(session, b):
        await _ensure_review_permission(
            session, int(b.order_id), uid, STATUS_QUOTE_REVIEW,
        )

    return await _post_transition(
        request, body, inter_session, ACTION_QUOTE_REJECT, OPERATOR_APPROVER,
        before=_before,
    )


async def distribution_order_approval_quote_withdraw(
    request: Request,
    body: TransitionBody,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _post_transition(
        request, body, inter_session, ACTION_QUOTE_WITHDRAW, OPERATOR_CREATOR,
    )


async def distribution_order_approval_order_approve(
    request: Request,
    body: TransitionBody,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    uid = getattr(getattr(request, "user", None), "id", None)

    async def _before(session, b):
        await _ensure_review_permission(
            session, int(b.order_id), uid, STATUS_ORDER_REVIEW,
        )

    return await _post_transition(
        request, body, inter_session, ACTION_ORDER_APPROVE, OPERATOR_APPROVER,
        before=_before,
    )


async def distribution_order_approval_order_reject(
    request: Request,
    body: TransitionBody,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    uid = getattr(getattr(request, "user", None), "id", None)
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    if not (body.remark or "").strip():
        msg = translate_text("驳回时审批意见不能为空", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}

    async def _before(session, b):
        await _ensure_review_permission(
            session, int(b.order_id), uid, STATUS_ORDER_REVIEW,
        )

    return await _post_transition(
        request, body, inter_session, ACTION_ORDER_REJECT, OPERATOR_APPROVER,
        before=_before,
    )


async def distribution_order_approval_order_withdraw(
    request: Request,
    body: TransitionBody,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _post_transition(
        request, body, inter_session, ACTION_ORDER_WITHDRAW, OPERATOR_CREATOR,
    )
