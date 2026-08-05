# -* coding: utf-8 -*-
"""
# @Time    : 2026/4/27
# @Author  : Zhu Yaming
# @File    : contract_service.py
# @Description : 线下合同增删增删改查
"""
from __future__ import annotations
import json
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from Crypto.SelfTest.Cipher.test_pkcs1_oaep import rws
from fastapi import HTTPException
from sqlalchemy import select, func, desc, delete, case
import base64
import time
from apps.common.service.yy_log import log_async_create

from apps.system.offline_customer.models import (OfflineContract, OfflineContractAttachment, OfflineContractUncondRebate,
    OfflineContractCondRebateStep, OfflineCustomer, ContractStatus,OfflineCustomerContact, OfflineCustomerAddress
)
from apps.system.offline_customer.schemas import OfflineContractUpdateRequest
from apps.system.offline_customer.contract_workflow_engine import STATUS_DRAFT, ACTION_SUBMIT, ACTION_APPROVE, ACTION_REJECT, ACTION_WITHDRAW, ACTION_TERMINATE

NESTED_KEYS = ("uncond_rebates", "cond_rebate_steps")


def _pydantic_row(x: Any) -> dict:
    if isinstance(x, dict):
        return x
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return x.dict()

NUMERIC_COLS = (
    "prepayment_ratio",
    "mt_min_order_amount",
    "mt_delivery_target_ratio",
    "return_ratio",
    "sample_discount",
)


def _d(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _validate_cond_rebate_steps(steps: List[dict]) -> None:
    if not steps:
        return
    by_no = sorted(steps, key=lambda x: x.get("step_no", 0))
    prev = None
    for row in by_no:
        sno = row.get("step_no")
        amt = row.get("annual_purchase_amount")
        if sno is None or amt is None:
            raise ValueError("有条件返利行缺少 step_no 或 annual_purchase_amount")
        if prev is not None and float(amt) <= float(prev):
            raise ValueError("有条件返利台阶: step_no 越大 annual_purchase_amount 须严格递增")
        prev = amt


def _orm_row_dict(clean: dict) -> dict:
    col_names = {c.key for c in OfflineContract.__table__.columns}
    out = {k: v for k, v in clean.items() if k in col_names and k not in ("_id", "create_time", "update_time")}
    for k in NUMERIC_COLS:
        if k in out and out[k] is not None:
            out[k] = _d(out[k])
    return out


EPOCH_TIME = 1704067200000


def int_to_base64_url(num: int) -> str:
    """
    将整数转换为 URL 安全的 Base64 字符串 (去除填充符)
    """
    if num == 0: return "0"

    num_bytes = num.to_bytes(6, byteorder='big')
    encoded_bytes = base64.urlsafe_b64encode(num_bytes)
    return encoded_bytes.decode('ascii').rstrip('=')


async def generate_contract_no(session, customer_code: str, customer_id, sign_d: Optional[datetime.date] = None) -> str:
    """
    生成合同号: 客户编号-合同创建日期加2位自增ID
    """
    if not sign_d: sign_d = datetime.date.today()

    day = sign_d.strftime("%Y%m%d")
    prefix = f"{customer_code}-{day}-"

    data_q = select(OfflineContract).where(
        OfflineContract.customer_id == customer_id,
        OfflineContract.contract_no.like(f"{prefix}%")
    ).order_by(OfflineContract.contract_no.desc())

    rows = (await session.execute(data_q)).scalars().all()
    next_seq = 1
    if rows:
        last_contract_no = rows[0].contract_no
        try:
            last_seq = int(last_contract_no[-2:])
            next_seq = last_seq + 1
        except (ValueError, IndexError):
            # 如果提取失败（比如历史数据格式不从1开始对），默认
            next_seq = 1

    final_contract_no = f"{prefix}{next_seq:02d}"

    return final_contract_no

async def create_offline_contract(
    db_session, data: dict, user_id: int
) -> OfflineContract:
    raw = dict(data)

    uncond_rebates = raw.pop("uncond_rebates", None) or []
    cond_steps = raw.pop("cond_rebate_steps", None) or []

    _validate_cond_rebate_steps([_pydantic_row(x) for x in cond_steps])

    if raw.get("customer_id") is None: raise ValueError("缺少 customer_id")
    customer_id = raw.get("customer_id")

    cust = (
        await db_session.execute(
            select(OfflineCustomer).where(OfflineCustomer._id == customer_id)
        )
    ).scalar_one_or_none()

    raw['customer_code'] = cust.customer_code
    raw['mt_currency'] = cust.settlement_currency

    raw["contract_no"] = await generate_contract_no(db_session, cust.customer_code, customer_id)

    raw.setdefault("status", ContractStatus.DRAFT)
    raw["create_by"] = user_id
    raw["update_by"] = user_id

    payment_ratio = raw.get("prepayment_ratio", 0.0)
    if not payment_ratio:
        raw["prepayment_ratio"] = 0.0

    obj = OfflineContract(**_orm_row_dict(raw))
    db_session.add(obj)
    await db_session.flush()
    c_id = obj._id

    for u in uncond_rebates:
        ud = _pydantic_row(u)
        db_session.add(
            OfflineContractUncondRebate(
                contract_id=c_id,
                fee_category_id=ud["fee_category_id"],
                calc_method=ud["calc_method"],
                calc_base=ud.get("calc_base"),
                value=_d(ud["value"]),
                currency=ud.get("currency"),
                remark=ud.get("remark"),
            )
        )
    for s in cond_steps:
        sd = _pydantic_row(s)
        db_session.add(
            OfflineContractCondRebateStep(
                contract_id=c_id,
                step_no=sd["step_no"],
                annual_purchase_amount=_d(sd["annual_purchase_amount"]),
                rebate_ratio=_d(sd["rebate_ratio"]),
                currency=sd.get("currency"),
            )
        )

    await db_session.commit()
    await db_session.refresh(obj)
    return obj


async def get_offline_contract(
    db_session,
    contract_id: int,
    with_children: bool = True,
    include_workflow: bool = False,
) -> Optional[Dict[str, Any]]:
    o = (
        await db_session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    if not o:
        return None
    if not with_children:
        out: Dict[str, Any] = {
            "contract": o,
            "uncond_rebates": [],
            "cond_rebate_steps": [],
            "address": {},
            "contact": {},
        }
        if include_workflow:
            from apps.system.offline_customer.contract_workflow_engine import load_workflow_bundle

            out["workflow"] = await load_workflow_bundle(db_session, contract_id)
        return out

    currency = (
        await db_session.execute(select(OfflineCustomer.settlement_currency).where(OfflineCustomer._id == o.customer_id))
    ).scalar_one_or_none()

    ureb = (
        await db_session.execute(
            select(OfflineContractUncondRebate).where(OfflineContractUncondRebate.contract_id == contract_id)
        )
    ).scalars().all()
    cst = (
        await db_session.execute(
            select(OfflineContractCondRebateStep).where(OfflineContractCondRebateStep.contract_id == contract_id)
        )
    ).scalars().all()

    contact_id = o.contact_id
    address_id = o.address_id

    if contact_id:
        contact = (
            await db_session.execute(
                select(OfflineCustomerContact).where(OfflineCustomerContact._id == contact_id)
            )
        ).scalar_one_or_none()
        if not contact: contact = {}

    if not contact_id: contact = {}

    if address_id:
        address = (
            await db_session.execute(
                select(OfflineCustomerAddress).where(OfflineCustomerAddress._id == address_id)
            )
        ).scalar_one_or_none()
        if not address: address = {}

    if not address_id: address = {}

    for cs in cst:
        cs.currency = currency

    result = {
        "contract": o,
        "uncond_rebates": list(ureb),
        "cond_rebate_steps": list(cst),
        "address": serialize_contract_entity(address),
        "contact": serialize_contract_entity(contact)
    }
    if include_workflow:
        from apps.system.offline_customer.contract_workflow_engine import load_workflow_bundle

        result["workflow"] = await load_workflow_bundle(db_session, contract_id)
    return result

async def _get_contract_details(db_session, contract_id: int) -> Dict[str, Any]:
    ureb = (
        await db_session.execute(
            select(OfflineContractUncondRebate).where(OfflineContractUncondRebate.contract_id == contract_id)
        )
    ).scalars().all()
    cst = (
        await db_session.execute(
            select(OfflineContractCondRebateStep).where(OfflineContractCondRebateStep.contract_id == contract_id)
        )
    ).scalars().all()
    result = {
        "uncond_rebates": list(ureb),
        "cond_rebate_steps": list(cst),
    }

    return result


async def list_offline_contracts(
    db_session,
    page: int = 1,
    page_size: int = 20,
    customer_id: Optional[int] = None,
    status: Optional[int] = None,
    country: Optional[str] = None,
) -> Tuple[int, List[OfflineContract]]:
    cond = []
    if customer_id is not None:
        cond.append(OfflineContract.customer_id == customer_id)
    if status is not None:
        cond.append(OfflineContract.status == status)
    if country:
        cond.append(OfflineContract.country == country)
    count_q = select(func.count(OfflineContract._id))
    if cond:
        count_q = count_q.where(*cond)
    total = (await db_session.execute(count_q)).scalar() or 0
    data_q = select(OfflineContract)
    if cond:
        data_q = data_q.where(*cond)

    status_order = case(
        (OfflineContract.status == 40, 1),
        (OfflineContract.status == 30, 2),
        (OfflineContract.status == 20, 3),
        (OfflineContract.status == 10, 4),
        (OfflineContract.status == 50, 5),
        else_=6
    )
    data_q = (
        data_q.order_by(status_order, desc(OfflineContract.create_time))
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db_session.execute(data_q)).scalars().all()

    return int(total), list(rows)


def serialize_contract_entity(obj) -> dict:
    """ORM -> JSON 友好 dict"""
    if obj is None: return None
    if obj == {}: return {}
    out: Dict[str, Any] = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name, None)
        if v is None:
            out[c.name] = None
        elif isinstance(v, Decimal):
            out[c.name] = float(v)
        elif isinstance(v, datetime.datetime):
            out[c.name] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, datetime.date):
            out[c.name] = v.isoformat()
        elif isinstance(v, (dict, list)):
            out[c.name] = v
        else:
            out[c.name] = v
    return out

def normalize_date(val):
    if not val:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    if isinstance(val, str):
        try:
            return datetime.datetime.fromisoformat(val).date()
        except ValueError:
            return val # 如果转换失败，保留原值
    return val


def convert_to_serializable(obj):
    """递归将复杂对象转为可序列化的基础类型"""
    if isinstance(obj, datetime.datetime):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(obj, datetime.date):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(i) for i in obj]
    elif hasattr(obj, "__table__"):
        return {c.name: convert_to_serializable(getattr(obj, c.name)) for c in obj.__table__.columns if c.name not in ('_id', 'contract_id')}
    else:
        return obj

def json_serializer(obj):
    if obj is None:
        return "None"
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return str(obj)

async def update_offline_contract(
    db_session, data: dict, user_id: int, contract_id:int, user_name: str = ""
) -> Optional[OfflineContract]:

    bundle = await get_offline_contract(db_session, contract_id, with_children=True)
    contract = bundle["contract"]
    bundle_dict = convert_to_serializable(bundle)

    from apps.system.offline_customer.change_diff import deep_diff

    old_data = bundle_dict.copy()
    old_contract_dict = old_data.pop("contract", {})
    old_data.update(old_contract_dict)
    old_prepayment_ratio = old_contract_dict.get("prepayment_ratio", None)
    if not old_prepayment_ratio:
        payment_ratio = data.get("prepayment_ratio", 0.0)
        if not payment_ratio:
            data["prepayment_ratio"] = 0.0

    clean_logs = deep_diff(old_data=old_data, new_data=data)

    if not contract: return None

    if contract.status != STATUS_DRAFT:
        raise HTTPException(40000, "当前状态不允许编辑，请刷新页面")

    uncond = data.pop("uncond_rebates", None)
    cond_rebate_steps = data.pop("cond_rebate_steps", None)

    main_keys = {c.key for c in OfflineContract.__table__.columns} - {
        "_id", "create_time", "update_time", "create_by", "contract_no"
    }

    for k, v in data.items():
        if k not in main_keys:
            continue

        setattr(contract, k, v)

    contract.update_by = user_id
    contract.update_time = datetime.datetime.now()

    if uncond is not None:
        await db_session.execute(
            delete(OfflineContractUncondRebate)
            .where(OfflineContractUncondRebate.contract_id == contract_id)
            .execution_options(synchronize_session="fetch")  # ✅
        )
        for u in uncond:
            ud = _pydantic_row(u)
            db_session.add(
                OfflineContractUncondRebate(
                    contract_id=contract_id,
                    fee_category_id=ud["fee_category_id"],
                    calc_method=ud.get("calc_method", None),
                    calc_base=ud.get("calc_base"),
                    value=_d(ud["value"]),
                    currency=ud.get("currency"),
                    remark=ud.get("remark"),
                )
            )

    if cond_rebate_steps is not None:
        await db_session.execute(
            delete(OfflineContractCondRebateStep)
            .where(OfflineContractCondRebateStep.contract_id == contract_id)
            .execution_options(synchronize_session="fetch")  # ✅
        )
        for c in cond_rebate_steps:
            ud = _pydantic_row(c)
            db_session.add(
                OfflineContractCondRebateStep(
                    contract_id=contract_id,
                    rebate_ratio=ud.get("rebate_ratio", None),
                    currency=ud.get("currency", None),
                    annual_purchase_amount=ud.get("annual_purchase_amount", None),
                    step_no=ud.get("step_no", None),
                )
            )

    operation_details = json.dumps(
        clean_logs,
        ensure_ascii=False,
        default=json_serializer
    )
    if clean_logs:
        await log_async_create(
            username=user_name,
            types="更新",
            operation_details=operation_details,
            session=db_session,
            refer_type="offline_contract",
            refer_table="data_sys_offline_contract",
            refer_id=contract_id
        )

    await db_session.commit()
    await db_session.refresh(contract)
    return contract


async def delete_offline_contract(db_session, contract_id: int) -> bool:
    o = (
        await db_session.execute(select(OfflineContract).where(OfflineContract._id == contract_id))
    ).scalar_one_or_none()
    if not o:
        return False
    if o.status != ContractStatus.DRAFT:
        raise ValueError("仅草稿(10)状态可物理删除")

    await db_session.execute(
        delete(OfflineContractUncondRebate).where(OfflineContractUncondRebate.contract_id == contract_id)
    )
    await db_session.execute(
        delete(OfflineContractCondRebateStep).where(OfflineContractCondRebateStep.contract_id == contract_id)
    )
    await db_session.execute(delete(OfflineContract).where(OfflineContract._id == contract_id))
    await db_session.commit()
    return True
