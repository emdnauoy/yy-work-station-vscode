# -*- coding: utf-8 -*-
"""
# @File    : contract_workflow_engine.py
# @Description : 合同审批流引擎（配置驱动多步审批）
#
# 状态码（status）
#   10  DRAFT        草稿
#   20  IN_REVIEW    审核中
#   30  PENDING      待生效（全部审批通过，等待生效日）
#   40  ACTIVE       已生效
#   50  EXPIRED      已失效
#
# 动作码（action_code / ACTION_*）
#   1   SUBMIT       提交审核
#   2   APPROVE      通过
#   3   REJECT       驳回（回草稿）
#   4   WITHDRAW     撤回（回草稿）
#   5   TERMINATE    终止（→ 已失效）
#   6   ACTIVATE     生效（系统触发或人工）
#   7   RESUBMIT     重新发起（驳回后再提交，等价 SUBMIT，语义更清晰）
#
# trigger_type（OfflineContractStatusLog.trigger_type）
#   1   人工操作
#   2   系统自动（定时任务触发生效/失效）
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger

from sqlalchemy import select, func, and_, text, asc
from sqlalchemy.ext.asyncio import AsyncSession
from apps.system.reports.view.common_func import get_translaiton_dict_from_request
from apps.system.offline_customer.common_func import get_user_name_dict
from apps.common.service.user import UserService

# ── 状态常量 ────────────────────────────────────────────────────────────────
STATUS_DRAFT     = 10  # 草稿
STATUS_IN_REVIEW = 20  # 审核中
STATUS_PENDING   = 30  # 待生效
STATUS_ACTIVE    = 40  # 已生效
STATUS_EXPIRED   = 50  # 已失效

# ── 动作常量 ────────────────────────────────────────────────────────────────
ACTION_SUBMIT    = 1   # 提交审核
ACTION_APPROVE   = 2   # 审核通过
ACTION_REJECT    = 3   # 审核驳回
ACTION_WITHDRAW  = 4   # 撤回审核
ACTION_TERMINATE = 5   # 终止合同
ACTION_ACTIVATE  = 6   # 生效激活
ACTION_RESUBMIT  = 7   # 重新发起
ACtion_SYSTEM = 8 # 系统更新

# ── 客户状态常量 ────────────────────────────────────────────────────────────
CUSTOMER_STATUS_PENDING   = 10  # 建联中
CUSTOMER_STATUS_ACTIVE    = 20  # 生效中
CUSTOMER_STATUS_EXPIRED   = 30  # 已过期

# ── trigger_type ────────────────────────────────────────────────────────────
TRIGGER_MANUAL = 1
TRIGGER_SYSTEM = 2

# ── 合同操作人
CREATOR = 1
APPROVER = 2
ADMIN = 3
SYSTEM = 4

STATUS_BUTTON_LIST = {
    STATUS_DRAFT : ["select", "edit", "submit", "log"],
    STATUS_IN_REVIEW : ["select", "review", "withdraw", "log"],
    STATUS_PENDING : ["select", "terminate", "log"],
    STATUS_ACTIVE : ["select", "terminate", "resubmit", "log"],
    STATUS_EXPIRED : ["select", "resubmit", "log"],
}


# ── 合法状态流转表（from_status → {action → to_status}）None 表示"任意状态"均可触发（如 TERMINATE 可在多个状态下使用时放开）
_TRANSITIONS: Dict[int, Dict[int, int]] = {
    STATUS_DRAFT: {
        ACTION_SUBMIT:    STATUS_IN_REVIEW,
        ACTION_RESUBMIT:  STATUS_IN_REVIEW,   # 驳回后重新发起
        ACTION_TERMINATE: STATUS_EXPIRED,
    },
    STATUS_IN_REVIEW: {
        ACTION_APPROVE:   None,               # 动态：未到末尾 → 20，末尾 → 30
        ACTION_REJECT:    STATUS_DRAFT,
        ACTION_WITHDRAW:  STATUS_DRAFT,
        ACTION_TERMINATE: STATUS_EXPIRED,
    },
    STATUS_PENDING: {
        ACTION_ACTIVATE:  STATUS_ACTIVE,
        ACTION_TERMINATE: STATUS_EXPIRED,
    },
    STATUS_ACTIVE: {
        ACTION_TERMINATE: STATUS_EXPIRED,
    },
    STATUS_EXPIRED: {
        ACTION_SUBMIT:    STATUS_IN_REVIEW,
        ACTION_RESUBMIT:  STATUS_IN_REVIEW,
    },
}

# ── 哪些动作需要写操作人（为 None 表示系统自动触发可不填） ──────────────────
_REQUIRE_OPERATOR = {ACTION_SUBMIT, ACTION_APPROVE, ACTION_REJECT, ACTION_WITHDRAW, ACTION_TERMINATE, ACTION_RESUBMIT}

STATUS_STR                 = {10: "待提交", 20: "审核中", 30: "待生效", 40: "生效中", 50: "已失效"}                 # 合同状态
ACTION_STR                 = {1: "提交审核", 2: "通过", 3: "驳回", 4: "撤回", 5: "终止", 6: "生效", 7: "重新发起", 8:"系统更新"}     # 合同动作
OPERATOR_ROLE_STR          = {1: "发起人", 2: "审批人", 3: "管理员", 4: "系统"}                                 # 操作人角色

# 参考 接口走配置
TERMINATE_TYPE_STR         = {1: "自然到期", 2: "人工终止", 3: "被新合同顶替"}                                    # 合同终止类型
CONTRACT_METHOD_STR        = {1: "寄售", 2: "非寄售"}                                                            # 合同方式
IS_PREPAYMENT_STR          = {0: "否", 1: "是"}                                                               # 是否预付款
MS_HAS_DELIVERY_TARGET_STR = {0: "不设送货率目标", 1: "有送货率目标"}                                            # 是否有送货率目标
MT_HAS_PENALTY_STR         = {0: "不约定未达标违约金", 1: "有约定违约金"}                                         # 是否有违约金条款
MT_DELIVERY_MODE_STR       = {1: "一次性送齐", 2: "允许多批"}                                                   # 交货模式
CUSTOMER_STATUS_STR        = {10: "建联中", 20: "生效中", 30: "已过期"}                                          # 客户状态
PAYMENT_METHOD_STR         = {1: "银行转账", 2: "支票", 3: "现金", 4: "无需支付"}                                 # 付款方式
SETTLEMENT_NODE_STR        = {1: "带款提货", 2: "账期"}                                                         # 结算方式
DELIVERY_METHOD_STR        = {1: "在指定地点交付", 2: "在配送中心交付", 3: "客户自提"}                             # 配送方式
RETURN_POLICY_STR          = {1: "可退", 0: "不可退"}                                                           # 退货政策
REWARD_POLICY_STR          = {1: "季度采购激励", 2: "年度采购激励", 3: "其他"}                                   # 奖励政策
AD_CHANNELS_STR            = {1: "线上", 2: "线下"}                                                            # 授权渠道
AD_CHANNELS_NEXT_STR       = {1: "地区", 2: "渠道"}                                                           # 授权渠道下一级
SAMPLE_POLICY_STR          = {1: "免费供样", 2: "off折扣供样"}                                                  # 样品政策

# ────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ────────────────────────────────────────────────────────────────────────────
def _assert_transition(from_status: int, action: int) -> None:
    allowed = _TRANSITIONS.get(from_status, {})
    if action not in allowed:
        status_label = STATUS_STR.get(from_status, str(from_status))
        action_label = ACTION_STR.get(action, str(action))
        raise ValueError(f"当前状态「{status_label}」不允许执行「{action_label}」")


async def _load_approval_steps(db: AsyncSession):
    """
    加载启用中的审批链配置，按 step_no 升序。
    返回 ORM 对象列表，每条含 step_no / approver_id / role_code 等字段。
    """
    from apps.system.offline_customer.models import ContractApprovalConfig

    rows = (
        await db.execute(
            select(ContractApprovalConfig)
            .where(ContractApprovalConfig.is_active == True)
            .order_by(asc(ContractApprovalConfig.step_no))
        )
    ).scalars().all()
    if not rows:
        raise RuntimeError("未配置审批链，请先在「合同审批配置」")
    return rows


async def _write_status_log(
    db: AsyncSession,
    *,
    contract_id: int,
    from_status: Optional[int],
    to_status: int,
    from_step: Optional[int],
    to_step: Optional[int],
    action_code: Optional[int],
    operator_id: Optional[int],
    operator_role: Optional[int] = None,
    trigger_type: int = TRIGGER_MANUAL,
    remark: Optional[str] = None,
) -> None:
    from apps.system.offline_customer.models import OfflineContractStatusLog  # 延迟导入

    db.add(
        OfflineContractStatusLog(
            contract_id=contract_id,
            from_status=from_status,
            to_status=to_status,
            from_step=from_step,
            to_step=to_step,
            action_code=action_code,
            operator_id=operator_id,
            operator_role=operator_role,
            trigger_type=trigger_type,
            remark=remark,
        )
    )
    await db.commit()

async def _update_customer_status(session,  operator_id: int, operator_role: Optional[int],customer_id: int, status: int, contract) -> None:
    from apps.system.offline_customer.models import OfflineCustomer
    customer = (
        await session.execute(select(OfflineCustomer).where(OfflineCustomer._id == customer_id))
    ).scalar_one_or_none()
    if customer:
        # 当激活合同时，更新客户状态为生效中，并将 had_ever_effect 设置为 1, 并替换当前生效合同
        if status == STATUS_ACTIVE:
            pre_contract_id = customer.current_contract_id
            customer.current_contract_id = contract._id
            customer.status = CUSTOMER_STATUS_ACTIVE
            # 如果合同状态为已生效，将 had_ever_effect 设置为 1
            customer.had_ever_effect = 1
            customer.updated_by = operator_id
            customer.update_time = datetime.datetime.now()

            # 将上一份合同的状态修改为已失效
            if pre_contract_id is None or(pre_contract_id and pre_contract_id != contract._id):
                from apps.system.offline_customer.models import OfflineContract
                previous_contract = (
                    await session.execute(select(OfflineContract).where(OfflineContract._id == pre_contract_id))
                ).scalar_one_or_none()
                if previous_contract:
                    from_status = previous_contract.status
                    previous_contract.status = STATUS_EXPIRED
                    from_step = previous_contract.current_step
                    previous_contract.current_step = None
                    previous_contract.updated_by = operator_id
                    previous_contract.update_time = datetime.datetime.now()
                    if from_status != previous_contract.status:
                        await session.commit()
                        await session.refresh(previous_contract)

                        await _write_status_log(
                            session,
                            contract_id=pre_contract_id,
                            from_status=from_status,
                            to_status= previous_contract.status,
                            from_step=from_step,
                            to_step=previous_contract.current_step,
                            action_code=ACTION_TERMINATE,
                            operator_id=operator_id,
                            operator_role=operator_role,
                            trigger_type=TRIGGER_SYSTEM,
                            remark="系统自动失效，将上一份合同失效"
                        )

                    contract.previous_contract_id = pre_contract_id
            logger.info(f"Contract ID: {contract._id}, 合同顶替成功：{pre_contract_id} → {contract._id}")
            customer.customer_status = CUSTOMER_STATUS_ACTIVE
            customer.current_contract_id = contract._id

        elif status == STATUS_EXPIRED:
            # 当合同y要到失效时，若客户当前的合同为当前合同，更新客户状态为已过期，并将当前生效合同置空
            current_contract_id = customer.current_contract_id
            if current_contract_id == contract._id:
                customer.current_contract_id = None
                customer.customer_status = CUSTOMER_STATUS_EXPIRED
                customer.updated_by = operator_id
                customer.update_time = datetime.datetime.now()

        await session.commit()
        await session.refresh(customer)

        return contract
    else:
        return contract

def get_trans_value(value, is_trans=False, trans_dict={}):
    if not is_trans:
        return value
    else:
        value = trans_dict.get(value, value)
        return value

async def _customer_status_transition(session, operator_id: int, operator_role: Optional[int], contract_status: int, contract, pre_msg: str = "", is_trans= False, trans_dict={}):
    """
    根据合同状态，更新客户状态
        # 当前合同审核通过后， 判断是否到达生效日期， 若未到则 为待生效， 否则为已生效
    """
    customer_id = contract.customer_id
    effective_start = contract.effective_start
    effective_end = contract.effective_end
    today = datetime.datetime.now().date()

    if not isinstance(effective_start, datetime.date):
        effective_start = datetime.datetime.fromtimestamp(effective_start).date()
    if contract_status == STATUS_ACTIVE:
        # 当合同激活时，若客户当前的合同为当前合同，更新客户状态为生效中，并将 had_ever_effect 设置为 1
        contract = await _update_customer_status(session, operator_id, operator_role, customer_id, contract_status, contract)

        return contract, pre_msg + get_trans_value("合同已生效", is_trans=is_trans, trans_dict=trans_dict)

    elif contract_status == STATUS_PENDING:
        if effective_start and effective_start > today:
            to_status = STATUS_PENDING
            message = pre_msg + get_trans_value("合同通过审核，但未到生效日期，合同进入「待生效」状态", is_trans=is_trans, trans_dict=trans_dict)

        # 2. 其次判断是否已过期（有结束日期且在过去）
        elif effective_end and effective_end < today:
            to_status = STATUS_EXPIRED
            message = pre_msg + get_trans_value("合同通过审核，但已过生效日期，合同进入「已失效」状态", is_trans=is_trans, trans_dict=trans_dict)

        # 3. 剩下的情况默认为已生效
        else:
            # 涵盖：正常生效区间内、无时间限制、仅有开始日期且已到达、仅有结束日期且未过期等情况
            to_status = STATUS_ACTIVE
            if effective_start and effective_end:
                message = pre_msg + get_trans_value("合同通过审核，在生效区间内，合同进入「已生效」状态", is_trans=is_trans, trans_dict=trans_dict)
            elif not effective_start and not effective_end:
                message = pre_msg + get_trans_value("合同通过审核，未设置具体生效区间，默认进入「已生效」状态", is_trans=is_trans, trans_dict=trans_dict)
            else:
                # 处理只有开始日期或只有结束日期的边缘情况
                message = pre_msg + get_trans_value("合同通过审核，满足生效条件，合同进入「已生效」状态", is_trans=is_trans, trans_dict=trans_dict)

        # 状态为已激活时， 更新相关客户的状态
        if to_status in (STATUS_ACTIVE, STATUS_EXPIRED):
            contract = await _update_customer_status(session, operator_id, operator_role, customer_id, to_status, contract)
        contract.status = to_status

        return contract, message

    elif contract_status == STATUS_EXPIRED:
        contract = await _update_customer_status(session, operator_id, operator_role, customer_id, contract_status, contract)

        return contract, pre_msg + get_trans_value("合同已失效", is_trans=is_trans, trans_dict=trans_dict)

    else:
        logger.warning(f"未知状态: {contract_status}")
        return contract, pre_msg + get_trans_value("未知状态", is_trans=is_trans, trans_dict=trans_dict)


async def _get_valid_role_step(db, country: str, current_step: int):
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
          bsc.config_key = 'customer_nation' and yrp.value = :country
          AND dac.step_no >= :current_step AND dac.is_active = 1 AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
    """)
    roles = await db.execute(sql, {"country": country, "current_step": current_step})

    return [(row.role_id, row.step_no) for row in roles]


async def _get_next_step(session, contract, action, current_step) -> Optional[int]:
    """
    判断下一步
    提交和重新提交：判断这个人的办事角色step_no最小的哪一个
    """
    from apps.system.offline_customer.models import OfflineCustomer
    if action in (ACTION_SUBMIT, ACTION_RESUBMIT, ACTION_APPROVE):
        # 获取当前人的办事角色
        country = (
            await session.execute(select(OfflineCustomer.customer_country).where(OfflineCustomer._id == contract.customer_id))
        ).scalar_one_or_none()
        roles = await _get_valid_role_step(session, country, current_step)
        if not roles:
            return None

        next_step = min([role[1] for role in roles])
        return next_step

    return None



# Focus: 合同状态流转
async def apply_transition(
    request,
    session,
    *,
    contract_id: int,
    action: int,
    operator_id: Optional[int] = None,
    operator_role: Optional[int] = None,
    comment: Optional[str] = None,
    trigger_type: int = TRIGGER_MANUAL,
    # is_admin: bool = False,
    reject_to_info = None,
) -> Tuple[Any, Dict[str, Any], str]:
    """
    对合同执行一次状态流转。

    Parameters
    ----------
    session            : 异步 SQLAlchemy session（调用方负责 commit 或本函数内 commit）
    contract_id   : 合同 ID
    action        : ACTION_* 常量
    operator_id   : 操作人 ID（系统触发时可为 None）
    operator_role : 操作人角色编码（写入日志，可选）
    comment       : 审批意见
    trigger_type  : TRIGGER_MANUAL=1 / TRIGGER_SYSTEM=2
    reject_to_info: 驳回时的下一步审批信息（可选）
    request       :  Request

    Returns
    -------
    (contract_orm, meta_dict)
    meta_dict 包含：
        action / from_status / to_status / current_step / total_steps / message
    """
    from apps.system.offline_customer.models import OfflineContract  # 延迟导入

    # ── 1. 加载合同 ──────────────────────────────────────────────────────────
    contract: Optional[OfflineContract] = (
        await session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    if not contract:
        raise ValueError(f"合同 {contract_id} 不存在")

    from_status  = contract.status
    from_step    = contract.current_step
    if reject_to_info is None: reject_to_info = []

    # ── 2. 校验状态机合法性 ───────────────────────────────────────────────────
    _assert_transition(from_status, action)

    # ── 3. 加载审批链（仅流转涉及审批时需要） ──────────────────────────────────
    total_steps = 0
    if action in (ACTION_SUBMIT, ACTION_RESUBMIT, ACTION_APPROVE, ACTION_REJECT, ACTION_WITHDRAW):
        steps_raw       = await _load_approval_steps(session)
        steps = [r.step_no for r in steps_raw if r.step_no > 0]
        total_steps = len(steps)

    # ── 4. 执行流转逻辑 ───────────────────────────────────────────────────────
    to_status: int
    message: str
    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer'])

    if action in (ACTION_SUBMIT, ACTION_RESUBMIT):
        # 提交 / 重新发起：进入第 1 步
        to_status             = STATUS_IN_REVIEW
        contract.status       = to_status
        contract.current_step = 1
        # 需要判断是否有下一步的审核人， 若没有，需要跳过， 根据合同国家 和 角色判断
        next_step = await _get_next_step(session, contract, action, contract.current_step)
        if next_step is None:
            # 没有下一步，直接跳过审批，进入待生效状态
            to_status             = STATUS_PENDING
            contract.status       = to_status
            contract.current_step = None
            pre_msg = "合同提交后，未找到下一步审批人，直接跳过审批，进入「待生效」状态;"
            logger.info(f"Contract ID: {contract._id} {pre_msg}")
            contract, message = await _customer_status_transition(session, operator_id, operator_role, to_status, contract, pre_msg, is_trans=is_trans, trans_dict=translation_dict)
        else:
            # 有下一步，正常审批
            contract.current_step = next_step
            message = f"已提交,待审批"

    elif action == ACTION_APPROVE:
        # 通过：校验操作人 → 判断是否最后一步

        if contract.current_step >= total_steps:
            # 最后一步通过 → 待生效
            to_status             = STATUS_PENDING
            contract.status       = to_status
            contract.current_step = None
            contract, message = await _customer_status_transition(session, operator_id, operator_role, to_status, contract, is_trans=is_trans, trans_dict=translation_dict)
        else:
            # 中间步通过 → 步数 +1，状态保持 IN_REVIEW
            contract.current_step += 1
            to_status              = STATUS_IN_REVIEW

            next_step = await _get_next_step(session, contract, action, contract.current_step)
            if next_step is None:
                # 没有下一步，直接跳过审批，进入待生效状态
                to_status             = STATUS_PENDING
                contract.status       = to_status
                contract.current_step = None
                pre_msg = "合同审批通过后，未找到下一步审批人,直接跳过审批，进入「待生效」状态;"
                contract, message = await _customer_status_transition(session, operator_id, operator_role, to_status, contract, pre_msg, is_trans=is_trans, trans_dict=translation_dict)
            else:
                # 有下一步，正常审批
                contract.current_step = next_step
                p1_msg = "审批通过,当前待下一轮审批, 当前"
                if is_trans: p1_msg = translation_dict.get(p1_msg, p1_msg)
                message = f"{p1_msg}：{from_step}/{total_steps}"

    elif action == ACTION_REJECT:
        # 驳回：退回草稿，清除步数
        if reject_to_info:
            operator_role = reject_to_info.get("operator_role")
            to_status = reject_to_info.get("to_status", STATUS_DRAFT)
            contract.status = to_status
            contract.current_step = reject_to_info.get("to_step_no", None)
            p1_msg = "驳回成功, 当前"
            if is_trans: p1_msg = translation_dict.get(p1_msg, p1_msg)
            message = f"{p1_msg}：{from_step}/{total_steps}"
        else:
            to_status             = STATUS_DRAFT
            contract.status       = to_status
            contract.current_step = None
            p1_msg = "驳回，合同退回至待提交, 当前"
            if is_trans: p1_msg = translation_dict.get(p1_msg, p1_msg)
            message = f"{p1_msg}：{from_step}/{total_steps}"

    elif action == ACTION_WITHDRAW:
        # 撤回：只允许提交人撤回（此处由调用层控制，引擎不重复校验）
        to_status             = STATUS_DRAFT
        contract.status       = to_status
        contract.current_step = None
        message = "已撤回，合同退回至待提交"

    elif action == ACTION_TERMINATE:
        to_status             = STATUS_EXPIRED
        contract.status       = to_status
        contract.current_step = None
        message = "合同已终止"
        contract, _ = await _customer_status_transition(session, operator_id, operator_role, to_status, contract, is_trans=is_trans, trans_dict=translation_dict)

    elif action == ACTION_ACTIVATE:
        to_status             = STATUS_ACTIVE
        contract.status       = to_status
        contract.current_step = None
        message = "合同已生效"
        contract, _ = await _customer_status_transition(session, operator_id, operator_role, to_status, contract, is_trans=is_trans, trans_dict=translation_dict)

    else:
        p1_msg = "未知动作码"
        if is_trans: p1_msg = translation_dict.get(p1_msg, p1_msg)
        raise ValueError(f"{p1_msg}: {action}")

    # ── 5. 持久化 ─────────────────────────────────────────────────────────────
    contract.updated_by  = operator_id
    contract.update_time = datetime.datetime.now()
    to_status = contract.status
    await session.commit()
    await session.refresh(contract)

    # ── 6. 写状态日志 ─────────────────────────────────────────────────────────
    await _write_status_log(
        session,
        contract_id=contract_id,
        from_status=from_status,
        to_status=to_status,
        from_step=from_step,
        to_step=contract.current_step,
        action_code=action,
        operator_id=operator_id,
        operator_role=operator_role,
        trigger_type=trigger_type,
        remark=comment,
    )

    # ── 7. 返回 ───────────────────────────────────────────────────────────────
    meta: Dict[str, Any] = {
        "action":       action,
        "from_status":  from_status,
        "to_status":    to_status,
        "current_step": contract.current_step,
        "total_steps":  total_steps or None,
        "message":      message,
    }

    if is_trans: message = translation_dict.get(message, message)
    return contract, meta, message



# 查询：审批进度 bundle（供 get_offline_contract 调用）
async def load_workflow_bundle(
    session, contract_id: int
) -> Dict[str, Any]:
    """
    返回合同的完整审批进度，包括：
    - 当前所处步骤

    前端可直接用于渲染进度条 / 审批时间线。
    """
    from apps.system.offline_customer.models import (
        OfflineContract, OfflineContractStatusLog,
    )

    contract: Optional[OfflineContract] = (
        await session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    if not contract:
        raise ValueError(f"合同 {contract_id} 不存在")

    contract_no = contract.contract_no
    from apps.system.offline_customer.view.sys_offline_contract_approve import get_country_by_customer_id
    country = await get_country_by_customer_id(session, contract.customer_id)

    # 该合同所有状态日志，按时间升序
    logs = (
        await session.execute(
            select(OfflineContractStatusLog)
            .where(OfflineContractStatusLog.contract_id == contract_id)
            .order_by(OfflineContractStatusLog.create_time, OfflineContractStatusLog._id)
        )
    ).scalars().all()
    status = contract.status
    total_step = []
    history_steps = []
    steps_raw = await _load_approval_steps(session)
    step_role_name_dict = {steps_raw.step_no: steps_raw.role_name for steps_raw in steps_raw}

    if not logs:
        if status == 10:
            user_id = contract.create_by
            if user_id == 0:
                operator_name = "System"
            else:
                user_name = await UserService.get_users_by_ids(internal_session=session, user_ids=[user_id])
                operator_name = user_name[0].name if user_name else None
            total_step.append({
                "from_status": 10,
                "from_status_str": STATUS_STR.get(10, "审核中"),
                "to_status": 20,
                "to_status_str": STATUS_STR.get(20, "审核中"),
                "step_no": None,
                "operator_id": 1,
                "operator_role_str": "发起人",
                "role_name": "发起人",
                "action_code_str": "办理中",
                "operator_name": operator_name
            })
            for step in steps_raw:
                role_id = step.role_id
                approval_map = await get_approval_users(session,  country, role_id)
                users = approval_map.get((step.step_no, country), "")
                if users:
                    total_step.append({
                        "from_status": 20,
                        "from_status_str": STATUS_STR.get(20, "审核中"),
                        "to_status": 20,
                        "to_status_str": STATUS_STR.get(20, "审核中"),
                        "step_no": step.step_no,
                        "operator_id": role_id,
                        "operator_role_str": step.role_name,
                        "role_name": step.role_name,
                        "action_code_str": "待办理",
                        "operator_name": users
                    })


        if status == 20:
            is_first = True

            for step in steps_raw:
                role_id = step.role_id
                approval_map = await get_approval_users(session, country, role_id)
                users = approval_map.get((step.step_no, country), "")
                if users:
                    total_step.append({
                        "from_status": 10 if is_first else 20,
                        "from_status_str": STATUS_STR.get(20, "审核中"),
                        "to_status": 20,
                        "to_status_str": STATUS_STR.get(20, "审核中"),
                        "step_no": step.step_no,
                        "operator_id": role_id,
                        "operator_role_str": step.role_name,
                        "role_name": step.role_name,
                        "action_code_str": "办理中" if is_first else "待办理",
                        "operator_name": users
                    })
                    is_first = False

    else:
        # trigger_log = next((log for log in reversed(logs) if log.action_code in [1, 7]), None)
        #
        # if trigger_log:
        #     start_time = trigger_log.create_time
        #     target_logs = [log for log in logs if log.create_time >= start_time]
        # else:
        #     target_logs = []

        step_rolename_dict = {step.step_no: step.role_name for step in steps_raw}

        for log in logs:
            operator_id = log.operator_id
            if operator_id != 0:
                operator = await UserService.get_users_by_ids(session, [operator_id])
                operator_name = operator[0].name if operator else None
            else:
                operator_name = "System"

            item = {
                "from_status": log.from_status,
                "from_status_str": STATUS_STR.get(log.from_status, log.from_status),
                "to_status": log.to_status,
                "to_status_str": STATUS_STR.get(log.to_status, log.to_status),
                "action_code": log.action_code,
                "step_no": log.to_step,
                "action_code_str": ACTION_STR.get(log.action_code, log.action_code),
                "operator_id": log.operator_id,
                "operator_name": operator_name,
                "operator_role": log.operator_role,
                "operator_role_str": OPERATOR_ROLE_STR.get(log.operator_role, log.operator_role) if log.operator_role != 2 else step_rolename_dict.get(log.from_step),
                "operated_at": log.create_time.strftime("%Y-%m-%d %H:%M:%S"),
                "remark": log.remark,
            }
            history_steps.append(item)

        # 获取下一步的信息 , 根据 最后的 状态
        last_step = history_steps[-1] if history_steps else {}
        from_status = last_step.get("from_status")

        last_step_no = last_step.get("step_no", None)
        last_action = last_step.get("action_code", None)
        last_to_status = last_step.get("to_status", None)
        is_first = True

        if last_step_no:
            for step in steps_raw:
                step_no = step.step_no
                if step_no >= last_step_no:
                    role_id = step.role_id
                    approval_map = await get_approval_users(session,  country, role_id)
                    users = approval_map.get((step.step_no, country), "")
                    if users:
                        total_step.append({
                            "from_status": 20,
                            "from_status_str": STATUS_STR.get(20, "审核中"),
                            "to_status": 20,
                            "to_status_str": STATUS_STR.get(20, "审核中"),
                            "step_no": step.step_no,
                            "operator_id": role_id,
                            "operator_role_str": step.role_name,
                            "role_name": step.role_name,
                            "action_code_str": "办理中" if is_first else "待办理",
                            "operator_name": users
                        })
                        is_first = False

        elif last_to_status == 10:
            user_id = contract.create_by
            if user_id == 0:
                operator_name = "System"
            else:
                user_name = await UserService.get_users_by_ids(internal_session=session, user_ids=[user_id])
                operator_name = user_name[0].name if user_name else None
            total_step.append({
                "from_status": 20,
                "from_status_str": STATUS_STR.get(20, "审核中"),
                "to_status": 20,
                "to_status_str": STATUS_STR.get(20, "审核中"),
                "step_no": None,
                "operator_id": 1,
                "operator_role_str": "发起人",
                "role_name": "发起人",
                "action_code_str": "办理中",
                "operator_name": operator_name
            })
            for step in steps_raw:
                role_id = step.role_id
                approval_map = await get_approval_users(session,  country, role_id)
                users = approval_map.get((step.step_no, country), "")
                if users:
                    total_step.append({
                        "from_status": 20,
                        "from_status_str": STATUS_STR.get(20, "审核中"),
                        "to_status": 20,
                        "to_status_str": STATUS_STR.get(20, "审核中"),
                        "step_no": step.step_no,
                        "operator_id": role_id,
                        "operator_role_str": step.role_name,
                        "role_name": step.role_name,
                        "action_code_str": "待办理",
                        "operator_name": users
                    })

        if last_action == 5:
            total_step = []
            history_steps = history_steps[:-1]

    return {
        "contract_no": contract_no,
        "current_step": contract.current_step,
        "contract_status": contract.status,
        "contract_status_str": STATUS_STR.get(contract.status, contract.status),
        "history_steps": history_steps,
        "next_steps": total_step
    }


async def get_approval_users(session: AsyncSession, country: str, role_id: int):
    # 1. 编写带参数的 SQL
    sql = text(
        """
        SELECT yrp.`value`             AS country,
               dac.`step_no`           AS step_no,
               GROUP_CONCAT(DISTINCT yu.`name`) as user_names
        FROM internal_app.`user_business_role_permission` yrp
                 INNER JOIN internal_app.business_role_config bsc ON bsc.id = yrp.role_config_id
                 INNER JOIN internal_app.business_role bs ON bsc.role_id = bs.role_id
                 INNER JOIN internal_app.data_sys_offline_contract_approval_config dac ON dac.role_id = bs.role_id
                 INNER JOIN internal_app.yy_user yu on yu._id = yrp.user_id
        WHERE yrp.value = :country AND bsc.role_id =:role_id AND dac.is_active = 1 AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
        GROUP BY dac.step_no, yrp.value
        """
    )

    # 2. 异步执行 SQL
    result = await session.execute(sql, {"country": country, "role_id": role_id})

    # 3. 构建字典 {(step_no, country): user_names}
    approval_map = {}
    for row in result.all():
        # 使用元组作为键
        key = (row.step_no, row.country)
        approval_map[key] = row.user_names

    return approval_map


# ── 当前执行人筛选（对齐客户列表 get_contract_execute_user_name）──────────────

def _normalize_execute_user_ids(user_ids: Optional[List[Any]]) -> List[int]:
    uids: Set[int] = set()
    for x in (user_ids or []):
        if x is None or str(x).strip() == "":
            continue
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0:
            uids.add(n)
    return sorted(uids)


def _clean_executor_display_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    text_name = str(name).strip()
    if not text_name:
        return None
    if text_name.lower() in ("unknow", "unknown", "none", "null"):
        return None
    return text_name


async def customer_ids_matched_by_execute_users(
    session: AsyncSession, user_ids: List[int],
) -> List[int]:
    """
    按「当前执行人」反查客户 id，口径对齐 get_contract_execute_user_name：
    - 草稿(status=10)：owner_staff_id
    - 审核中(status=20)：当前 step 办事角色 + 客户国家匹配的审批人
    """
    uids = _normalize_execute_user_ids(user_ids)
    if not uids:
        return []

    from apps.system.offline_customer.models import OfflineContract

    matched: Set[int] = set()
    draft_rows = (
        await session.execute(
            select(OfflineContract.customer_id).where(
                OfflineContract.status == STATUS_DRAFT,
                OfflineContract.owner_staff_id.in_(uids),
            ).distinct()
        )
    ).scalars().all()
    for cid in draft_rows:
        if cid is not None:
            matched.add(int(cid))

    uid_csv = ",".join(str(i) for i in uids)
    role_sql = text(
        """
        SELECT DISTINCT c.customer_id AS customer_id
        FROM internal_app.data_sys_offline_contract c
        INNER JOIN internal_app.data_sys_offline_customers cust
            ON cust._id = c.customer_id
        INNER JOIN internal_app.data_sys_offline_contract_approval_config dac
            ON dac.step_no = c.current_step
           AND dac.is_active = 1
        INNER JOIN internal_app.business_role bs
            ON bs.role_id = dac.role_id AND bs.invalid_ind = 0
        INNER JOIN internal_app.business_role_config bsc
            ON bsc.role_id = bs.role_id
           AND bsc.invalid_ind = 0
           AND bsc.config_key = 'customer_nation'
        INNER JOIN internal_app.user_business_role_permission yrp
            ON yrp.role_config_id = bsc.id
           AND yrp.invalid_ind = 0
           AND yrp.value = cust.customer_country
           AND yrp.user_id IN (%s)
        WHERE c.status = 20
          AND c.current_step IS NOT NULL
          AND c.current_step > 0
        """ % uid_csv
    )
    for row in (await session.execute(role_sql)).all():
        if row.customer_id is not None:
            matched.add(int(row.customer_id))

    return sorted(matched)


async def collect_related_execute_user_ids(session: AsyncSession) -> List[int]:
    """
    收集在途合同（草稿/审核中）上与「当前执行人」相关的 user_id，
    口径对齐 customer_ids_matched_by_execute_users / get_contract_execute_user_name。
    """
    from apps.system.offline_customer.models import OfflineContract

    uids: Set[int] = set()
    draft_rows = (
        await session.execute(
            select(OfflineContract.owner_staff_id).where(
                OfflineContract.status == STATUS_DRAFT,
                OfflineContract.owner_staff_id.isnot(None),
                OfflineContract.owner_staff_id > 0,
            ).distinct()
        )
    ).all()
    for (uid,) in draft_rows:
        try:
            n = int(uid)
        except (TypeError, ValueError):
            continue
        if n > 0:
            uids.add(n)

    role_sql = text(
        """
        SELECT DISTINCT yrp.user_id AS user_id
        FROM internal_app.data_sys_offline_contract c
        INNER JOIN internal_app.data_sys_offline_customers cust
            ON cust._id = c.customer_id
        INNER JOIN internal_app.data_sys_offline_contract_approval_config dac
            ON dac.step_no = c.current_step
           AND dac.is_active = 1
        INNER JOIN internal_app.business_role bs
            ON bs.role_id = dac.role_id AND bs.invalid_ind = 0
        INNER JOIN internal_app.business_role_config bsc
            ON bsc.role_id = bs.role_id
           AND bsc.invalid_ind = 0
           AND bsc.config_key = 'customer_nation'
        INNER JOIN internal_app.user_business_role_permission yrp
            ON yrp.role_config_id = bsc.id
           AND yrp.invalid_ind = 0
           AND yrp.value = cust.customer_country
        WHERE c.status = 20
          AND c.current_step IS NOT NULL
          AND c.current_step > 0
          AND yrp.user_id > 0
        """
    )
    for row in (await session.execute(role_sql)).all():
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
    missing: List[int] = []
    for uid in uids:
        name = None
        if td:
            name = td.get(str(uid)) or td.get(uid)
        name = _clean_executor_display_name(name)
        if not name:
            missing.append(uid)
            continue
        if kw and kw not in name.lower() and kw not in str(uid):
            continue
        options.append({"label": name, "value": int(uid)})

    if missing:
        users = await UserService.get_users_by_ids(session, missing)
        name_by_id = {
            int(u._id): _clean_executor_display_name(getattr(u, "name", None))
            for u in (users or [])
            if getattr(u, "_id", None) is not None
        }
        for uid in missing:
            name = name_by_id.get(uid)
            if not name:
                continue
            if kw and kw not in name.lower() and kw not in str(uid):
                continue
            options.append({"label": name, "value": int(uid)})

    options.sort(key=lambda item: (item["label"], item["value"]))
    return options


