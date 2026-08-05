# -* coding: utf-8 -*-
"""
# @Time    : 2026/4/28
# @Author  : Zhu Yaming
# @File    : sys_offline_contract_approve.py
# @Description : 合同状态流转
"""

from __future__ import annotations

from typing import Optional, Tuple, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from sqlalchemy.testing.plugin.plugin_base import options

from apps.system.reports.view.common_func import get_translaiton_dict_from_request, translate_all_output
from apps.system.reports.view.common_func import get_translaiton_dict_from_request
from apps.common.service.table_title_desc_mapping import async_get_one_title_mapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from core.response import ResultResponse


from apps.system.offline_customer.contract_workflow_engine import (
    ACTION_APPROVE,
    ACTION_REJECT,
    ACTION_RESUBMIT,
    ACTION_SUBMIT,
    ACTION_TERMINATE,
    ACTION_WITHDRAW,
    TRIGGER_MANUAL,
    apply_transition,
    load_workflow_bundle,
)
from apps.system.offline_customer.contract_workflow_engine import CREATOR, APPROVER, ADMIN, SYSTEM
from conf.settings import settings
from core.db.session import get_async_session
from apps.system.offline_customer.models import OfflineCustomer, OfflineContract, ContractApprovalConfig
from apps.system.offline_customer.view.sys_offline_contract_view import msg_translator_return

auth_url_part = settings.AuthUrlPart
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=auth_url_part + "/login/")
router = APIRouter(prefix="/contracts", tags=["合同审批"])


# ────────────────────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────────────────────

class TransitionBody(BaseModel):
    """所有流转接口共用的请求体，comment 可选"""
    contract_id: Optional[int] = None
    remark: Optional[str] = Field(None, description="审批意见 / 备注")
    reject_to_info: Optional[Any] = None


class TransitionResponse(BaseModel):
    """统一响应结构"""
    contract_id: int
    from_status: int
    to_status: int
    current_step: Optional[int]
    total_steps: Optional[int]
    message: str


# 内部公共函数：调用引擎 + 统一异常映射
async def _do_transition(
        request: Request,
        contract_id: int,
        action: int,
        session: AsyncSession,
        user_id: int,
        operator_role: Optional[int] = None,
        comment: Optional[str] = None,
        reject_to_info = None,
) -> TransitionResponse:
    try:
        _, meta, message = await apply_transition(
            request,
            session,
            contract_id=contract_id,
            action=action,
            operator_id=user_id,
            operator_role=operator_role,
            comment=comment,
            trigger_type=TRIGGER_MANUAL,
            reject_to_info=reject_to_info,
        )
    except ValueError as e:
        raise HTTPException(status_code=40000, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=40000, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=40000, detail=str(e))

    return TransitionResponse(
        contract_id=contract_id,
        from_status=meta["from_status"],
        to_status=meta["to_status"],
        current_step=meta["current_step"],
        total_steps=meta["total_steps"],
        message=meta["message"],
    )



async def _get_user_roles(db, user_id: int):
    """获取用户角色"""

    sql = text(f"""
        SELECT
          bs.`name` AS business_role,
          bs.`role_id` AS role_id,
          yrp.`value` AS country
        FROM
          `user_business_role_permission` yrp
          INNER JOIN business_role_config bsc ON bsc.id = yrp.role_config_id
          INNER JOIN business_role bs ON bsc.role_id = bs.role_id
        WHERE
          yrp.user_id = :user_id AND bsc.config_key = 'customer_nation' AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
    """)
    roles = await db.execute(sql, {"user_id": user_id})
    role_ids = [row.role_id for row in roles]
    role_country = [row.country for row in roles]
    return role_ids, role_country


async def _get_user_valid_role_step(db, user_id: int, country: str, current_step: int):
    """获取用户角色"""

    sql = text(f"""
        SELECT
          bs.`name` AS business_role,
          bs.`role_id` AS role_id,
          yrp.`value` AS country,
          dac.`step_no` AS step_no
        FROM
          `user_business_role_permission` yrp
          INNER JOIN business_role_config bsc ON bsc.id = yrp.role_config_id
          INNER JOIN business_role bs ON bsc.role_id = bs.role_id
          INNER JOIN data_sys_offline_contract_approval_config dac ON dac.role_id = bs.role_id
        WHERE
          yrp.user_id = :user_id AND bsc.config_key = 'customer_nation' and yrp.value = :country
          AND dac.step_no = :current_step AND dac.is_active = 1 AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
    """)
    roles = await db.execute(sql, {"user_id": user_id, "country": country, "current_step": current_step})

    return [(row.role_id, row.step_no) for row in roles]


async def _get_contract_valid_role_step(db, country: str):
    """获取用户角色"""

    sql = text(f"""
        SELECT
          bs.`name` AS business_role,
          bs.`role_id` AS role_id,
          yrp.`value` AS country,
          dac.`step_no` AS step_no
        FROM
          `user_business_role_permission` yrp
          INNER JOIN business_role_config bsc ON bsc.id = yrp.role_config_id
          INNER JOIN business_role bs ON bsc.role_id = bs.role_id
          INNER JOIN data_sys_offline_contract_approval_config dac ON dac.role_id = bs.role_id
        WHERE
           yrp.value = :country AND dac.is_active = 1 AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
    """)
    roles = await db.execute(sql, {"country": country})

    return [(row.role_id, row.step_no) for row in roles]


async def get_country_by_customer_id(session, customer_id: int):
    country = (
        await session.execute(select(OfflineCustomer.customer_country).where(OfflineCustomer._id == customer_id))
    ).scalar_one_or_none()

    return country or ""


async def _get_user_next_step(session, contract, action, current_step, user_id) -> Optional[int]:
    """
    判断下一步
    提交和重新提交：判断这个人的办事角色step_no最小的哪一个
    """
    if action in (ACTION_APPROVE, ACTION_REJECT):
        # 获取当前人的办事角色
        country = await get_country_by_customer_id(session, contract.customer_id)
        roles = await _get_user_valid_role_step(session, user_id, country, current_step)
        if not roles:
            return None

        next_step = min([role[1] for role in roles])
        return next_step

    return None


async def _judge_role_match(inter_session, user_id: int, contract):
    """是否用户是否有合同审批权限"""
    next_step = await _get_user_next_step(inter_session, contract, ACTION_APPROVE, contract.current_step, user_id)

    return next_step

def _validate_contract_fields(contract,table_base_data):
    """
    校验合同必填字段是否填写
    """
    filter_value = table_base_data.get("filter_value", [])

    valid_files_dict = {}

    for item in filter_value:
        key = item["key"]
        if key == "validation_fields":
            opts = item["options"]
            for option in opts:
                label = option["label"]
                value = option["value"]
                valid_files_dict[value] = label

    null_cols = []
    contract_dict = contract.__dict__
    for k, v in valid_files_dict.items():
        kv = contract_dict.get(k, None)
        if kv is None:
            null_cols.append(v)

    return null_cols

# 接口
async def submit_contract(
        request: Request,
        body: TransitionBody = TransitionBody(),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    user_id = request.user.id
    contract_id = body.contract_id
    contract = (
        await inter_session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    if not contract:
        return ResultResponse(code=40000, msg="合同不存在", data=None)

    # 必填校验
    table_base_data = await async_get_one_title_mapping(inter_session, 315)

    null_cols = _validate_contract_fields(contract, table_base_data)
    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common', 'common_filters', 'msg'])
    msg = "存在未必填字段："
    if is_trans:
        null_cols = [translation_dict.get(v) for v in null_cols]
        msg = translation_dict.get(msg, msg)

    if null_cols:
        return ResultResponse(code=40000, msg=f"{msg}{null_cols}", data=None)

    # created_by = contract.create_by
    # if created_by != user_id:
    #     return ResultResponse(code=40000, msg="您不是合同创建人，无权提交", data=None)
    country = await get_country_by_customer_id(inter_session, contract.customer_id)
    roles = await _get_contract_valid_role_step(inter_session, country)

    if not roles:
        msg = "请联系管理员配置合同对应审批人"
        msg = translation_dict.get(msg, msg)
        return ResultResponse(code=40000, msg=msg, data=None)

    try:
        result = await _do_transition(request, contract_id, ACTION_SUBMIT, inter_session, user_id, CREATOR, body.remark)
    except HTTPException as e:
        return ResultResponse(code=e.status_code, msg=e.detail, data=None)

    msg = "操作成功"
    if is_trans: msg = translation_dict.get(msg, msg)
    return ResultResponse(msg=msg, data=result)


async def approve_contract(
        request: Request,
        body: TransitionBody = TransitionBody(),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    user_id = request.user.id
    contract_id = body.contract_id
    contract = (
        await inter_session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    next_step = await _judge_role_match(inter_session, user_id, contract)

    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common', 'common_filters', 'msg'])
    contract_status = contract.status
    if contract_status == 10:
        msg = "合同未到审批流程"
        if is_trans:  msg = translation_dict.get(msg, msg)
        return ResultResponse(status_code=40000, msg=msg, data=None)

    if not next_step:
        msg = "您暂无审批该合同的权限"
        if is_trans:  msg = translation_dict.get(msg, msg)
        return ResultResponse(status_code=40000, msg=msg, data=None)

    try:
        result = await _do_transition(request, contract_id, ACTION_APPROVE, inter_session, user_id, APPROVER, body.remark)
    except HTTPException as e:
        return ResultResponse(code=e.status_code, msg=e.detail, data=None)

    msg = "操作成功"
    if is_trans: msg = translation_dict.get(msg, msg)
    return ResultResponse(msg=msg, data=result)


async def reject_contract(
        request: Request,
        body: TransitionBody = TransitionBody(),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    user_id = request.user.id
    contract_id = body.contract_id
    reject_to_info = body.reject_to_info
    contract = (
        await inter_session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()

    contract_status = contract.status
    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common', 'common_filters', 'msg'])

    if contract_status == 10:
        msg = "合同未到审批流程"
        if is_trans:  msg = translation_dict.get(msg, msg)
        return ResultResponse(status_code=40000, msg=msg, data=None)

    next_step = await _judge_role_match(inter_session, user_id, contract)

    to_status = reject_to_info.get("to_status", 10)
    if to_status == 10: reject_to_info = None

    if not next_step:
        msg = "您暂无审批该合同的权限"
        if is_trans:  msg = translation_dict.get(msg, msg)
        return ResultResponse(status_code=40000, msg=msg, data=None)

    if not body.remark:
        msg = "驳回时（驳回原因）不能为空"
        if is_trans:  msg = translation_dict.get(msg, msg)
        return ResultResponse(status_code=40000, msg=msg, data=None)

    try:
        result = await _do_transition(request, contract_id, ACTION_REJECT, inter_session, user_id, APPROVER, body.remark, reject_to_info)
    except HTTPException as e:
        return ResultResponse(code=e.status_code, msg=e.detail, data=None)

    msg = "操作成功"
    if is_trans: msg = translation_dict.get(msg, msg)
    return ResultResponse(msg=msg, data=result)


async def withdraw_contract(
        request: Request,
        body: TransitionBody = TransitionBody(),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    contract_id = body.contract_id
    contract = (
        await inter_session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    if not contract:
        return ResultResponse(status_code=40000, detail="合同不存在")

    stmt = select(OfflineContract).where(
        OfflineContract.customer_id == contract.customer_id,
        OfflineContract.status == 10
    )

    pending_contracts = (await inter_session.execute(stmt)).scalars().all()
    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common', 'common_filters', 'msg'])

    if pending_contracts:
        msg = "已存在待提交合同"
        if is_trans:
            msg = translation_dict.get(msg, msg)
        return ResultResponse(code=40000, msg=msg, data={})

    try:
        result = await _do_transition(request, contract_id, ACTION_WITHDRAW, inter_session, request.user.id, body.remark)
    except HTTPException as e:
        msg = e.detail
        if is_trans:
            msg = translation_dict.get(msg, msg)
        return ResultResponse(code=e.status_code, msg=msg, data=None)

    msg = "操作成功"
    if is_trans: msg = translation_dict.get(msg, msg)
    return ResultResponse(msg=msg, data=result)


async def terminate_contract(
        request: Request,
        body: TransitionBody = TransitionBody(),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    user_id = request.user.id
    contract_id = body.contract_id

    try:
        result = await _do_transition(request, contract_id, ACTION_TERMINATE, inter_session, user_id, APPROVER, body.remark)
    except HTTPException as e:
        return ResultResponse(code=e.status_code, msg=e.detail, data=None)
    msg = "操作成功"
    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common', 'common_filters', 'msg'])
    if is_trans: msg = translation_dict.get(msg, msg)
    return ResultResponse(msg=msg, data=result)


async def resubmit_contract(
        request: Request,
        body: TransitionBody = TransitionBody(),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    contract_id = body.contract_id
    contract = (
        await inter_session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    if not contract:
        return ResultResponse(status_code=40000, msg="合同不存在", data=None)

    # if contract.create_by != request.user.id:
    #     return ResultResponse(status_code=40000, msg="仅合同创建人可重新发起", data=None)

    try:
        result = await _do_transition(request, contract_id, ACTION_RESUBMIT, inter_session, request.user.id, body.remark)
    except HTTPException as e:
        return ResultResponse(code=e.status_code, msg=e.detail, data=None)

    msg = "操作成功"
    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common', 'common_filters', 'msg'])
    if is_trans: msg = translation_dict.get(msg, msg)
    return ResultResponse(msg=msg, data=result)


@translate_all_output(
    modules= ['common', 'message', 'common_filters', 'offline_customer'],
    translatable_fields=['action_code_str', 'from_status_str', 'operator_role_str', 'role_name', 'to_status_str'],
    skip_fields=[]
)
async def get_workflow(
        request: Request,
        contract_id: int,
        inter_session = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    try:
        bundle = await load_workflow_bundle(inter_session, contract_id)
    except ValueError as e:
        return ResultResponse(code=40000, msg=str(e), data=None)
    return ResultResponse(code=200, msg="获取数据成功", data=bundle)