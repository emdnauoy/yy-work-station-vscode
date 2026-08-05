# -*- coding:utf-8-*-
# @FileName : sys_offline_customers_view.py
# @Time     : 2024/11/25 17:07
# @Author   : yuhaiping
# @Email    : ping.yu@yaoyao-inc.com
# @Software : PyCharm
import ast
import json
import io
import time
import sys
import os
import traceback
from collections import defaultdict
import datetime
from typing import Optional, Union, Tuple, Any, List
from decimal import Decimal
import asyncio

import numpy as np
from loguru import logger
import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func, or_, update, and_, not_, case, desc, delete, insert, asc
from fastapi import Request, Depends, Query, Body, UploadFile, File
from fastapi.security import OAuth2PasswordBearer
from dateutil.relativedelta import relativedelta
from apps.common.service.user import UserService
from apps.common.service.yy_log import log_async_create
from apps.system.reports.view.common_func import get_translaiton_dict_from_request, translate_all_output
from apps.common.service.code_mstr_static import get_some_code_mstr

from apps.common.model.yy_log import Log
from apps.common.service.decorator import with_translation
from apps.common.service.table_title_desc_mapping import async_get_one_title_mapping
from apps.pyscript.translations.translations_helper import TranslationsHelper
from apps.system.offline_customer.model_response import OfflineCustomerResponse, OfflineCustomerFollowupRecordResponse, OfflineContractResponse
from apps.system.reports.view.common_func import get_common_user_dict
from apps.system.offline_customer.model_response import OfflineCustomerResponse, OfflineCustomerFollowupRecordResponse
from apps.system.offline_customer.models import OfflineCustomer, OfflineCustomerFollowupRecord, OfflineCustomerContact, OfflineCustomerAddress, OfflineContract
from apps.system.offline_customer.schemas import (OfflineCustomerUpdateRequest, OfflineCustomerFollowupCreateRequest, OfflineCustomerContactCreateRequest,
                                                  OfflineCustomerAddressCreateRequest, OfflineCustomerContactListRequest, OfflineCustomerAddressListRequest)
from apps.system.offline_customer.service import upsert_offline_customer, insert_offline_customer_followup_records, insert_offline_customer_contact_records, update_offline_customer_contact_records
from apps.system.offline_customer.contract_workflow_engine import (
    SETTLEMENT_NODE_STR, PAYMENT_METHOD_STR, DELIVERY_METHOD_STR, CONTRACT_METHOD_STR,
    STATUS_DRAFT, STATUS_IN_REVIEW,
    customer_ids_matched_by_execute_users, list_execute_user_filter_options,
)
from apps.system.offline_customer.common_func import get_table_key_cols
from apps.system.offline_customer.change_diff import parse_diff_log, deep_diff_create
from apps.system.offline_customer.contract_service import get_offline_contract


from conf.settings import settings
from core.db.session import get_async_session, get_async_data_session
from core.response import ResultResponse

sys.path.append(os.getcwd().split('apps')[0])

from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper, generate_date_list

auth_url_part = settings.AuthUrlPart
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=auth_url_part + "/login/")


async def get_contract_execute_user_name(inter_session, customer_id, country):
    from apps.system.offline_customer.view.sys_offline_contract_view import _get_now_role_step_users
    """
    获取客户合同的执行人
    这里可能存在既有审核中合同也有待提交合同，先取审核中的合同
    """
    stmt = select(OfflineContract).where(
        OfflineContract.customer_id == customer_id,
        OfflineContract.status.in_([STATUS_DRAFT, STATUS_IN_REVIEW]),
    ).order_by(
        case(
            (OfflineContract.status == STATUS_IN_REVIEW, 1),
            (OfflineContract.status == STATUS_DRAFT, 2),
            else_=3
        ).asc(),
        desc(OfflineContract.create_time)
    ).limit(1)

    result = await inter_session.execute(stmt)
    contract = result.scalar_one_or_none()
    if not contract: return None , None

    related_contract_id = contract._id

    if contract.status == STATUS_DRAFT:
        owner_staff_id = contract.owner_staff_id
        if owner_staff_id == 0:
            execute_user_name = "System"
        else:
            creator = await UserService.get_users_by_ids(inter_session, [owner_staff_id])
            execute_user_name = creator[0].name if creator else None
        return execute_user_name, related_contract_id
    else:
        step_no = contract.current_step
        execute_user_name = await _get_now_role_step_users(inter_session, country, step_no)
        return execute_user_name, related_contract_id


# 线下客户多语言装饰器
offline_customer_translator_return = with_translation("offline_customer",
target_keys=['label', 'title', 'titles', 'placeholder', 'formTitle', 'name', 'delivery_method_str', 'settlement_method_str', 'fee_category_id_str', 'sample_policy_str',
             'table_name', 'keyDesc', 'table_name', 'data', 'tData', 'contact_frequency_str', 'contract_method_str', 'create_time', 'upodate_time', 'return_policy_str',
             'settlement_method_str', 'payment_method_str', 'effective_node_str', 'afterstr', 'customer_status_str', 'is_reviewing_str', 'is_pending_str', 'value',
             'cooperation_method_str', 'is_tax_free_str']
)

async def _extent_offline_customer_data(inter_session: Session,request, customer_result, customer_table_base_data):
    # 生效合同信息
    from apps.system.offline_customer.contract_service import get_offline_contract
    from apps.system.offline_customer.view.sys_offline_contract_view import _bundle_to_response, _format_contract_extent_data, get_key_options_from_filter_value, recursive_translate_data,change_category_tree
    current_contract_id = customer_result.get('current_contract_id', None)
    customer_id = customer_result.get('_id', None)
    if isinstance(customer_id, str):
        customer_id = int(customer_id)
    customer_country = customer_result.get('customer_country', None)
    if not current_contract_id:
        execute_user_name, related_contract_id = await get_contract_execute_user_name(inter_session, customer_id, customer_country)
        return {"execute_user_name":execute_user_name, "related_contract_id":related_contract_id}

    table_base_data = await async_get_one_title_mapping(inter_session, 315)
    table_base_data = await change_category_tree(request, table_base_data)
    contract_cols = get_table_key_cols(customer_table_base_data.get("table_key_group", []), source='contract')
    bundle = await get_offline_contract(inter_session, current_contract_id, with_children=True)
    data = _bundle_to_response(bundle)
    filter_value = table_base_data.get("filter_value")
    contract = data.pop("contract")

    contract = await _format_contract_extent_data(request, inter_session, contract, filter_value)
    execute_user_name, related_contract_id = await get_contract_execute_user_name(inter_session, customer_id, customer_country)
    data.update(**contract)
    extent_cols = get_key_options_from_filter_value(filter_value)
    recursive_translate_data(data, extent_cols)
    data = {k: v for k, v in data.items() if k in contract_cols}
    data["execute_user_name"] = execute_user_name
    data["related_contract_id"] = related_contract_id

    return data


async def _get_customer_tags(inter_session: Session, customer_ids):
    customer_ids = [int(customer_id) for customer_id in customer_ids]

    tags = {cid: {"is_reviewing": False, "is_reviewing_str": "",
                  "is_pending": False, "is_pending_str": ""} for cid in customer_ids}

    stmt = select(OfflineContract.customer_id, OfflineContract.status).distinct().where(
        OfflineContract.customer_id.in_(customer_ids),
        OfflineContract.status.in_([20, 30])
    )

    rows = (await inter_session.execute(stmt)).fetchall()

    for customer_id, status in rows:
        if status == 20:
            tags[customer_id]["is_reviewing"] = True
            tags[customer_id]["is_reviewing_str"] = "审核中"
        elif status == 30:
            tags[customer_id]["is_pending"] = True
            tags[customer_id]["is_pending_str"] = "待生效"

    return tags


async def get_ower_staffs_options(inter_session: Session, request):
    result = select(OfflineContract.owner_staff_id.distinct())

    rows = await inter_session.execute(result)
    distinct_staff_ids = rows.fetchall()

    user_dict = await get_common_user_dict(request)

    opts = []
    for item in distinct_staff_ids:
        user_id_int = item[0]
        if user_id_int:
            user_id = str(user_id_int)
            opt = {"label": user_dict.get(user_id, "Unknow"), "value": user_id_int}

            opts.append(opt)

    return opts


async def _set_cusotmer_owner_list(inter_session: Session, table_base_data, request):
    filter_value = table_base_data.get("filter_value")

    for item in filter_value:
        key = item.get("key")
        if key == "owner_staff_id":
            options = await get_ower_staffs_options(inter_session, request)
            item["options"] = options

    table_base_data["filter_value"] = filter_value
    return table_base_data


@offline_customer_translator_return
async def get_sys_offline_customers_list(
    request: Request,
    is_download: int = 0,
    nation: str = "[]",
    customer_type: str = "[]",
    customer_name_code: str = "",
    contract_method: str = "[]",
    # contract_points: str = "",
    settlement_method: str = "[]",
    payment_method: str = "[]",
    # effective_node: str = "[]",
    recipient_name: str = "",
    # prepayment_ratio: str = "",
    # settlement_node: str = "[]",
    owner_staff_id: str = "[]",
    customer_status: str = "[]",
    status: str = "[]",
    is_ka: str = "[]",
    execute_user_ids: str = "[]",
    page: int = 1,
    pageSize: int = 50,
    create_time_desc: int = 1,
    date_sort: str = '{"key":"create_time","value":"descend"}',
    bi_session: Session = Depends(get_async_data_session),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    table_base_data = await async_get_one_title_mapping(inter_session, 149)
    table_base_data = await _set_cusotmer_owner_list(inter_session, table_base_data, request)

    try:
        nation = ast.literal_eval(nation)
        customer_type = ast.literal_eval(customer_type)
        contract_method = ast.literal_eval(contract_method)
        customer_status = ast.literal_eval(customer_status)
        status = ast.literal_eval(status)
        is_ka = ast.literal_eval(is_ka)
        sort_method = ast.literal_eval(date_sort)
        # contract_points_list = []
        # if contract_points:
        #     contract_points_list = [contract_points]
        # prepayment_ratio_list = []
        # if prepayment_ratio:
        #     prepayment_ratio_list = [prepayment_ratio]
        owner_staff_id = ast.literal_eval(owner_staff_id)
        execute_user_id_list = ast.literal_eval(execute_user_ids)

        settlement_method = ast.literal_eval(settlement_method)
        payment_method = ast.literal_eval(payment_method)
        # effective_node = ast.literal_eval(effective_node)
        # settlement_node = ast.literal_eval(settlement_node)

        customer_ids = []

        if payment_method or settlement_method or contract_method:
            contract_cons = [OfflineContract.status.in_([20, 30, 40])]  # 修正拼写

            if payment_method:
                contract_cons.append(OfflineContract.payment_method.in_(payment_method))
            if settlement_method:
                contract_cons.append(OfflineContract.settlement_method.in_(settlement_method))
            if contract_method:
                contract_cons.append(OfflineContract.contract_method.in_(contract_method))
            if owner_staff_id:
                contract_cons.append(OfflineContract.owner_staff_id.in_(owner_staff_id))

            customer_query = select(OfflineContract.customer_id.distinct()).where(*contract_cons)
            result = await inter_session.execute(customer_query)
            customer_ids = result.scalars().all()

            if not customer_ids:
                customer_ids = [-1]

        customer_ids_second = []
        if owner_staff_id or status:
            contract_con_second = []

            if owner_staff_id:
                contract_con_second.append(OfflineContract.owner_staff_id.in_(owner_staff_id))
            if status:
                contract_con_second.append(OfflineContract.status.in_(status))

            customer_query_second = select(OfflineContract.customer_id.distinct()).where(*contract_con_second)
            result_second = await inter_session.execute(customer_query_second)
            customer_ids_second = result_second.scalars().all()

            if not customer_ids_second:
                customer_ids_second = [-1]

        # 当前执行人：对齐 get_contract_execute_user_name（草稿 owner_staff / 审核中角色审批人）
        customer_ids_execute = []
        if execute_user_id_list:
            customer_ids_execute = await customer_ids_matched_by_execute_users(
                inter_session, execute_user_id_list,
            )
            if not customer_ids_execute:
                customer_ids_execute = [-1]

        conditions = [
            or_(OfflineCustomer.customer_country.in_(nation), nation == []),
            or_(
                OfflineCustomer.customer_type_second.in_(customer_type),
                OfflineCustomer.customer_type_first.in_(customer_type),
                customer_type == []
            )
        ]
        if customer_ids:
            conditions.append(OfflineCustomer._id.in_(customer_ids))

        if customer_ids_second:
            conditions.append(OfflineCustomer._id.in_(customer_ids_second))

        if customer_ids_execute:
            conditions.append(OfflineCustomer._id.in_(customer_ids_execute))

        if is_ka:
            conditions.append(OfflineCustomer.is_ka.in_(is_ka))

        if customer_status:
            conditions.append(OfflineCustomer.customer_status.in_(customer_status))

        if customer_name_code:
            conditions.append(
                or_(
                    OfflineCustomer.customer_short_name.ilike(f'%{customer_name_code}%'),
                    OfflineCustomer.customer_code.ilike(f'%{customer_name_code}%')
                )
            )
        # if settlement_node:
        #     conditions.append(
        #         or_(
        #             or_(OfflineCustomer.settlement_method.in_(settlement_node), settlement_node == []),
        #             or_(OfflineCustomer.effective_node.in_(settlement_node), settlement_node == []),
        #         )
        #     )
        #
        # if recipient_name:
        #     conditions.append(
        #         or_(
        #             OfflineCustomer.recipient_name == recipient_name
        #         )
        #     )

        default_sort = OfflineCustomer.create_time.desc()
        sort_conditions = [default_sort]

        if sort_method and sort_method.get("value") in ["ascend", "descend"]:
            key = sort_method["key"]
            order = sort_method["value"]

            sort_columns = {
                "create_time": OfflineCustomer.create_time
            }

            if key in sort_columns:
                column = sort_columns[key]
                sort_conditions = [column.desc() if order == "descend" else column.asc()]

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"参数错误：{tb}")
        return ResultResponse(code=40000, msg="参数错误", data=[])

    base_query = select(OfflineCustomer)
    total_query = select(func.count(OfflineCustomer._id).label('total_num')).where(*conditions)
    total_num = (await inter_session.execute(total_query)).scalar()
    page_total = (total_num + pageSize - 1) // pageSize
    query = base_query.where(*conditions).order_by(*sort_conditions).offset((page - 1) * pageSize).limit(pageSize)
    results = (await inter_session.execute(query)).scalars().all()

    table_base_data.update({'tData': [
        OfflineCustomerResponse.from_orm(off_cust) for off_cust in results
    ]})

    all_customer_ids = [result.get('_id') for result in table_base_data.get('tData', [])]
    customer_tags = await _get_customer_tags(inter_session, all_customer_ids)
    for result in table_base_data.get('tData', []):
        customer_id = result.get('_id')
        contact_frequency = result.get('contact_frequency', None)
        if contact_frequency:
            last_contact_time, next_contact_time = await _get_followup_records(inter_session, customer_id, contact_frequency)
            result.update({"last_contact_time": last_contact_time, "next_contact_time": next_contact_time})

        inresult = await _extent_offline_customer_data(inter_session,request, result, customer_table_base_data= table_base_data)
        tags = customer_tags.get(int(customer_id), {})
        result.update(tags)
        result.update(inresult)

    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer'])
    table_key_group = table_base_data.get('table_key_group', [])
    if is_trans:
        for item in table_key_group:
            label = item.get('label')
            if label == "时间":
                values = item.get('value', [])
                for v in values:
                    lable = v.get('label')
                    lable = translation_dict.get(lable, lable)
                    v ["label"] = lable

    data = {
        "page": page,
        "pageSize": pageSize,
        "total": total_num,
        "page_total": page_total
    }
    data.update(table_base_data)
    return ResultResponse(msg="获取数据成功", data=data)


async def offline_customer_execute_user_options(
    request: Request,
    keyword: str = "",
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    """当前执行人筛选项：[{label, value}, ...]。"""
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    try:
        user_dict = await get_common_user_dict(request)
        options = await list_execute_user_filter_options(
            inter_session, user_dict=user_dict, keyword=keyword,
        )
    except Exception as e:
        logger.error(f"执行人筛选项查询失败：{e}")
        msg = "获取数据失败"
        if is_trans:
            msg = translation_dict.get(msg, msg)
        return ResultResponse(code=40000, msg=msg, data=[])
    msg = "获取数据成功"
    if is_trans:
        msg = translation_dict.get(msg, msg)
    return ResultResponse(msg=msg, data=options)


def robust_format_time(
        dt: Optional[Union[datetime.datetime, str, int, float]],
        default: str = ""
) -> str:
    """
    安全的时间格式化器
    - 处理 None
    - 处理非 datetime 类型（可选扩展）
    - 捕获潜在异常
    """
    if dt is None:
        return default

    try:
        if isinstance(dt, datetime.datetime):
            return dt.strftime("%Y-%m-%d")
        else:
            return default
    except Exception as e:
        logger.error(f"Time format error: {e}")
        return default


async def _get_followup_records(inter_session: Session, offline_customer_id: str, contact_frequenc: int):
    """
    获取末次联络时间和下次联络时间
    """

    base_query = select(OfflineCustomerFollowupRecord)
    sort_conditions = [desc(OfflineCustomerFollowupRecord.contact_time)]
    query = base_query.where(OfflineCustomerFollowupRecord.offline_customer_id == offline_customer_id).order_by(*sort_conditions)
    result = (await inter_session.execute(query)).scalars().first()
    last_contact_time = result.contact_time if result else None
    next_contact_time = None
    if last_contact_time:
        CONTACT_FREQUENCY_MAP = {
            1: ("周度", {"weeks": 1}),
            2: ("双周度", {"weeks": 2}),
            3: ("月度", {"months": 1}),
            4: ("双月度", {"months": 2}),
            5: ("季度", {"months": 3}),
            6: ("半年度", {"months": 6}),
            7: ("年度", {"years": 1})
        }

        if contact_frequenc in CONTACT_FREQUENCY_MAP:
            freq_name, time_delta = CONTACT_FREQUENCY_MAP[contact_frequenc]
            next_contact_time = last_contact_time + relativedelta(**time_delta)

    last_str, next_str = robust_format_time(last_contact_time), robust_format_time(next_contact_time)
    return last_str, next_str


@offline_customer_translator_return
async def get_sys_offline_customers_detail(
    request: Request,
    offline_customer_id: str = "",
    is_show_config: int = 0,
    bi_session: Session = Depends(get_async_data_session),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    table_base_data = await async_get_one_title_mapping(inter_session, 148)
    if not offline_customer_id and is_show_config == 0:
        return ResultResponse(code=40000, msg="参数错误", data=table_base_data)
    elif not offline_customer_id and is_show_config == 1:
        return ResultResponse(msg="获取数据成功", data=table_base_data)

    base_query = select(OfflineCustomer).where(OfflineCustomer._id == offline_customer_id)
    customer_result = (await inter_session.execute(base_query)).scalars().first()

    customer_addresses = (await inter_session.execute(
        select(OfflineCustomerAddress).where(OfflineCustomerAddress.customer_id == offline_customer_id, OfflineCustomerAddress.is_delete == 0)
    )).scalars().all()

    customer_contacts = (await inter_session.execute(
        select(OfflineCustomerContact).where(OfflineCustomerContact.customer_id == offline_customer_id, OfflineCustomerContact.is_delete == 0)
    )).scalars().all()

    last_contact_time, next_contact_time = await _get_followup_records(inter_session, offline_customer_id, customer_result.contact_frequency)

    customer_data = OfflineCustomerResponse.from_orm(customer_result)

    final_data = {
        **customer_data,
        "last_contact_time": last_contact_time,
        "next_contact_time": next_contact_time,
        "addresses": [OfflineCustomerAddressListRequest.from_orm(addr).dict(by_alias=True) for addr in customer_addresses],
        "contacts": [OfflineCustomerContactListRequest.from_orm(contact).dict(by_alias=True) for contact in customer_contacts]
    }
    table_base_data.update({'tData': [final_data]})
    table_base_data.update({'table_key_group': []})
    return ResultResponse(msg="获取数据成功", data=table_base_data)


async def get_offline_customers_detail(request,inter_session, customer_code):
    base_query = select(OfflineCustomer).where(OfflineCustomer.customer_code == customer_code)
    customer_result = (await inter_session.execute(base_query)).scalars().first()
    customer_id = customer_result._id

    customer_addresses = (await inter_session.execute(
        select(OfflineCustomerAddress).where(OfflineCustomerAddress.customer_id == customer_id, OfflineCustomerAddress.is_delete == 0)
    )).scalars().all()

    customer_contacts = (await inter_session.execute(
        select(OfflineCustomerContact).where(OfflineCustomerContact.customer_id == customer_id, OfflineCustomerContact.is_delete == 0)
    )).scalars().all()

    customer_data = OfflineCustomerResponse.from_orm(customer_result)

    final_data = {
        **customer_data,
        "addresses": [OfflineCustomerAddressListRequest.from_orm(addr).dict(by_alias=True) for addr in customer_addresses],
        "contacts": [OfflineCustomerContactListRequest.from_orm(contact).dict(by_alias=True) for contact in customer_contacts]
    }
    return final_data

async def upsert_related_objects(
    session,
    data_list,
    model_class,
    id_field: str,
    extra_fields: dict,
    existing_ids=None,
):
    """
    通用 upsert 函数，同时返回本次处理的 ID 集合（用于后续删除对比）
    """
    objects = []
    seen_ids = set()

    for item in data_list:
        insert_data = item.copy()
        insert_data.update(extra_fields)

        obj_id = insert_data.pop(id_field, None)
        if obj_id:
            insert_data["_id"] = obj_id
            seen_ids.add(obj_id)

        obj = model_class(**insert_data)
        await session.merge(obj)
        objects.append(obj)

    return objects, seen_ids

async def delete_removed_objects(
    session,
    model_class,
    customer_id: str,
    seen_ids: set,
):
    """
    删除本次请求中不再存在的记录
    """
    result = await session.execute(
        select(model_class).where(
            model_class.customer_id == customer_id,
            model_class._id.notin_(seen_ids),
        )
    )
    for obj in result.scalars():
        await session.delete(obj)


def _display_name(request: Request) -> str:
    u = getattr(request, "user", None)
    if u is None:
        return ""
    return getattr(u, "display_name", None) or getattr(u, "username", None) or str(getattr(u, "id", "") or "")


def _log_json_default(obj: Any):
    if obj is None:
        return None
    if isinstance(obj, datetime.datetime):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(obj, datetime.date):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)

def json_serializer(obj):
    if obj is None:
        return "None"
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return str(obj)


@offline_customer_translator_return
async def update_sys_offline_customers(
    request: Request,
    data: OfflineCustomerUpdateRequest = Body(...),
    bi_session: Session = Depends(get_async_data_session),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    # try:
    operator = request.user.display_name
    user_id = request.user.id
    update_data = data.dict(exclude_unset=True)
    update_data.update({"update_by": user_id, "create_by": user_id})
    customer_code = update_data.get("customer_code")
    is_create = customer_code is None
    if not is_create: old_data = await get_offline_customers_detail(request, inter_session, customer_code=customer_code)
    oringinal_data = update_data.copy()

    address_data = update_data.pop("addresses", [])
    contact_data = update_data.pop("contacts", [])
    # 判断删除的联系人是否已经关联到合同
    to_delete_ids = [c.get("contact_id") for c in contact_data if c.get("is_delete", False)]

    delete_contact_names = []

    if to_delete_ids:
        contracts_stmt = select(OfflineContract.contact_id).where(
            OfflineContract.contact_id.in_(to_delete_ids)
        ).distinct()

        result = await inter_session.execute(contracts_stmt)
        exist_contact_ids = {row[0] for row in result.fetchall()}

        if not exist_contact_ids:
            pass
        else:
            for contact in contact_data:
                if contact.get("is_delete", False):
                    contact_id = contact.get("contact_id")
                    if contact_id in exist_contact_ids:
                        delete_contact_names.append(contact.get("name"))
            va_msg = "联系人已关联合同，不允许删除"
            is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer'])
            if is_trans:
                va_msg = translation_dict.get(va_msg, va_msg)
            return ResultResponse(code=40000, msg=f"{va_msg}：{', '.join(delete_contact_names)}", data={})

    to_delete_address_ids = [a.get("address_id") for a in address_data if a.get("is_delete", False)]

    delete_address_info = []

    if to_delete_address_ids:
        address_stmt = select(OfflineContract.address_id).where(
            OfflineContract.address_id.in_(to_delete_address_ids)
        ).distinct()

        result = await inter_session.execute(address_stmt)
        exist_address_ids = {row[0] for row in result.fetchall()}

        # 3. 找出哪些被删的地址命中了合同关联
        if exist_address_ids:
            for address in address_data:
                if address.get("is_delete", False):
                    addr_id = address.get("address_id")
                    if addr_id in exist_address_ids:
                        # 这里可以根据实际情况拼接提示信息，比如取 street 或 remark
                        addr_detail = address.get("address")
                        delete_address_info.append(addr_detail)
            va_msg = "地址已关联合同，不允许删除"
            is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer'])
            if is_trans:
                va_msg = translation_dict.get(va_msg, va_msg)
            return ResultResponse(code=40000, msg=f"{va_msg}：{', '.join(delete_address_info)}", data={})

    customer = await upsert_offline_customer(inter_session, update_data, operator=operator)
    if isinstance(customer, dict):
        customer_id = customer.get("_id")
    else:
        customer_id = customer._id

    if isinstance(customer_id, str): customer_id = int(customer_id)
    user_name = _display_name(request)
    if is_create:
        c_data = deep_diff_create(oringinal_data) or {}
        operation_details = json.dumps(c_data, ensure_ascii=False, default=_log_json_default)
        await log_async_create(
            username=user_name,
            types="新建",
            operation_details=operation_details,
            session=inter_session,
            refer_type='线下客户管理-新建',
            refer_table='data_sys_offline_customers',
            refer_id=customer_id,
        )
    else:
        from apps.system.offline_customer.change_diff import deep_diff
        clean_logs = deep_diff(old_data=old_data, new_data=oringinal_data,
                               ignore_keys ={"contract_no", "_id", "create_time", "update_time", "created_by", "updated_by", "create_by", "update_by", "button_list"})
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
                session=inter_session,
                refer_type='线下客户管理-修改',
                refer_table='data_sys_offline_customers',
                refer_id=customer_id
            )

    common_fields = {
        "customer_id": customer_id,
        "create_by": user_id,
        "update_by": user_id,
    }

    addresses, address_seen_ids = [], set()
    if address_data:
        addresses, address_seen_ids = await upsert_related_objects(
            session=inter_session,
            data_list=address_data,
            model_class=OfflineCustomerAddress,
            id_field="address_id",
            extra_fields=common_fields,
        )
        # 删除本次未传入的旧地址
        await delete_removed_objects(inter_session, OfflineCustomerAddress, customer_id, address_seen_ids)

    contacts, contact_seen_ids = [], set()
    if contact_data:
        contacts, contact_seen_ids = await upsert_related_objects(
            session=inter_session,
            data_list=contact_data,
            model_class=OfflineCustomerContact,
            id_field="contact_id",
            extra_fields=common_fields,
        )
        await delete_removed_objects(inter_session, OfflineCustomerContact, customer_id, contact_seen_ids)
    from apps.system.offline_customer.view.sys_offline_contract_view import serialize_contract_entity
    if not isinstance(customer, dict):
        customer_data = serialize_contract_entity(customer)
    else:
        customer_data = customer
    customer_data.update({"addresses": addresses, "contacts": contacts})
    await inter_session.commit()

    return ResultResponse(msg="操作成功", data=customer_data)
    # except Exception as e:
    #     return ResultResponse(code=50000, msg=f"操作失败:{e}")


@offline_customer_translator_return
async def add_offline_customer_followup_record(
    request: Request,
    data: OfflineCustomerFollowupCreateRequest = Body(...),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    try:
        op_user = request.user.display_name
        op_user_id = request.user.id
        insert_data = data.dict(exclude_unset=True)
        offline_customer_id = insert_data.get("offline_customer_id")
        if isinstance(offline_customer_id, str):
            offline_customer_id = int(offline_customer_id)

        company_contact_id = insert_data.get("company_contact_id", None)
        log_data = {}
        contact_time = insert_data.get("contact_time", None)
        if contact_time:
            log_data["contact_time"] = contact_time
        customer_contact_name = insert_data.get("customer_contact_name", None)
        if customer_contact_name:
            log_data["customer_contact_name"] = customer_contact_name
        content = insert_data.get("content", None)
        if content:
            log_data["content"] = content

        if company_contact_id:
            user = await UserService.get_users_by_ids(inter_session, [company_contact_id])
            company_contact_name = user[0].name if user else None
            log_data.update({"company_contact_name": company_contact_name})

        c_data = deep_diff_create(log_data) or {}
        operation_details = json.dumps(c_data, ensure_ascii=False, default=_log_json_default)
        await log_async_create(
            username=request.user.display_name,
            types="新建",
            operation_details=operation_details,
            session=inter_session,
            refer_type='线下客户管理-新建',
            refer_table='data_sys_offline_customers',
            refer_id=offline_customer_id,
        )
        insert_data.update({"operator": op_user, "operator_user_id": op_user_id})
        record_data = await insert_offline_customer_followup_records(inter_session, insert_data)
        res_data = [
            OfflineCustomerFollowupRecordResponse.from_orm(record_data)
        ]
        return ResultResponse(msg="操作成功", data=res_data)
    except Exception as e:
        return ResultResponse(code=50000, msg=f"操作失败:{e}")


@offline_customer_translator_return
async def get_offline_customer_followup_record_list(
    request: Request,
    offline_customer_id: str = "",
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    """

    :param request:
    :param offline_customer_id:
    :param inter_session:
    :param token:
    :return:
    """
    # try:
    base_query = select(OfflineCustomerFollowupRecord)
    sort_conditions = [desc(OfflineCustomerFollowupRecord.contact_time)]
    query = base_query.where(OfflineCustomerFollowupRecord.offline_customer_id==offline_customer_id).order_by(*sort_conditions)
    results = (await inter_session.execute(query)).scalars().all()
    offline_customer_records = [
        OfflineCustomerFollowupRecordResponse.from_orm(off_record) for off_record in results
    ]

    for item in offline_customer_records:
        user = await UserService.get_users_by_ids(inter_session, [item.company_contact_id])
        item.company_contact_name = user[0].name if user else None

    return ResultResponse(msg="获取数据成功", data=offline_customer_records)

    # except Exception as e:
    #     return ResultResponse(code=50000, msg="获取数据失败")


def extract_update_dict(text: str) -> dict:
    prefixes = ["Update :", "Create :"]
    for prefix in prefixes:
        if prefix in text:
            # 提取前缀之后的内容
            dict_str = text.split(prefix, 1)[1].strip()
            try:
                # 方案 A: 如果字符串里有 'None' 或 'True'，用这个
                data = ast.literal_eval(dict_str)
                return data, prefix
            except (ValueError, SyntaxError):
                try:
                    # 方案 B: 如果是标准 JSON 格式，用这个
                    data = json.loads(dict_str.replace("'", '"'))  # 尝试处理单双引号替换
                    return data, prefix
                except Exception as e:
                    print(f"解析失败: {e}")
                    return {}, ""
    return {}, ""


@offline_customer_translator_return
async def get_sys_operator_logs_old(
    request: Request,
    record_id: str = "",
    record_table: str = "data_sys_offline_customers",
    bi_session: Session = Depends(get_async_data_session),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    try:
        if not all([record_id, record_table]):
            return ResultResponse(code=40000, msg="参数错误")
        conditions = [
            Log.refer_id == record_id,
            Log.refer_table == record_table
        ]
        base_query = select(Log).where(*conditions).order_by(desc(Log._id))
        results = (await inter_session.execute(base_query)).scalars().all()
        language = request.headers.get('Language', 'cn')
        translation_helper = TranslationsHelper([language, "cn"], 'offline_customer')

        log_datas = []
        for log_obj in results:
            instance = dict()
            instance["operator"] = log_obj.user
            instance["operate_type"] = log_obj.type
            instance["record_operate_type"] = log_obj.refer_type
            instance["record_id"] = log_obj.refer_id
            instance["record_table"] = log_obj.refer_table
            instance["operate_time"] = log_obj.create_datetime.strftime("%Y-%m-%d %H:%M:%S")
            instance["operation_details"] = log_obj.operation_details
            op_dict, op_str = extract_update_dict(log_obj.operation_details)
            tmp_dict = dict()
            for key, value in op_dict.items():
                if key == '公司材料':
                    key = '客户资料'
                _, new_key = translation_helper.get_text(key)
                tmp_dict[new_key] = value
                if isinstance(value, dict):
                    child_dict = dict()
                    for k, v in value.items():
                        _, new_k = translation_helper.get_text(k)
                        child_dict[new_k] = v
                    tmp_dict[new_key] = child_dict
                instance["operation_details"] = op_str + f" {str(tmp_dict)}"
            log_datas.append(instance)
        return ResultResponse(msg="获取数据成功" if log_datas else "暂无日志数据", data=log_datas)
    except Exception as e:
        return ResultResponse(code=50000, msg="获取数据失败")


async def get_sys_operator_logs(
        request: Request,
        record_id,
        record_table: str = "data_sys_offline_customers",
        bi_session: Session = Depends(get_async_data_session),
        inter_session: Session = Depends(get_async_session),
        token: str = Depends(oauth2_scheme)
):
    customer_id = record_id
    from apps.system.offline_customer.view.sys_offline_contract_view import get_key_options_from_filter_value
    # try:
    table_base_data = await async_get_one_title_mapping(inter_session, 149)
    filter_value = table_base_data.get("filter_value")
    if not all([customer_id, record_table]):
        return ResultResponse(code=40000, msg="参数错误")
    conditions = [
        Log.refer_id == customer_id,
        Log.refer_table == record_table
    ]
    base_query = select(Log).where(*conditions).order_by(desc(Log._id))
    results = (await inter_session.execute(base_query)).scalars().all()
    extent_cols = get_key_options_from_filter_value(filter_value)
    schemas = extent_cols.get("log_display")
    all_logs = []
    language = request.headers.get('Language', 'cn')

    for record in results:
        try:
            o_details = json.loads(record.operation_details)
            op_time = record.create_datetime.strftime("%Y-%m-%d %H:%M:%S")
            user_name = record.user
            op_type = record.type
            title = parse_diff_log(o_details, schemas, key_value_dict=extent_cols, user_name=user_name, op_type=op_type, request=request,
                                   ignore_keys={"_id", "contract_id","contact_id","address_id","ref_id", "create_time", "update_time",  "create_by", "update_by"})
            log = {
                "content": "",
                "time": op_time,
                "user": user_name,
                "type": op_type,
                "title": title,
            }
            all_logs.append(log)
        except Exception as e:
            instance = dict()
            instance["operation_details"] = record.operation_details
            op_dict, op_str = extract_update_dict(record.operation_details)
            translation_helper = TranslationsHelper([language, "cn"], 'offline_customer')
            tmp_dict = dict()
            for key, value in op_dict.items():
                if key == '公司材料':
                    key = '客户资料'
                _, new_key = translation_helper.get_text(key)
                tmp_dict[new_key] = value
                if isinstance(value, dict):
                    child_dict = dict()
                    for k, v in value.items():
                        _, new_k = translation_helper.get_text(k)
                        child_dict[new_k] = v
                    tmp_dict[new_key] = child_dict
                instance["operation_details"] = op_str + f" {str(tmp_dict)}"
            log = {
                "content": "",
                "time": record.create_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                "user": record.user,
                "type": record.type,
                "title": instance["operation_details"] ,
            }
            all_logs.append(log)


    return ResultResponse(msg="获取数据成功" if all_logs else "暂无日志数据", data=all_logs)


@offline_customer_translator_return
async def add_offline_customer_contact(
    request: Request,
    data: OfflineCustomerContactCreateRequest = Body(...),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    try:
        op_user_id = request.user.id
        insert_data = data.dict(exclude_unset=True)
        insert_data.update({"update_by": op_user_id, "create_by": op_user_id})
        record_data = await insert_offline_customer_contact_records(inter_session, insert_data)
        va_msg = "创建成功"
        is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'msg'])
        if is_trans:
            va_msg = translation_dict.get(va_msg, va_msg)
        return ResultResponse(msg=va_msg, data=record_data)
    except ValidationError as e:
        return ResultResponse(code=40000, msg="参数错误", data=str(e))
    except ValueError as e:
        return ResultResponse(code=40000, msg="参数错误", data=str(e))
    except IntegrityError as e:
        return ResultResponse(code=40000, msg="已存在相同记录", data=str(e))
    except Exception as e:
        return ResultResponse(code=40000, msg="操作失败", data=str(e))


@offline_customer_translator_return
async def update_offline_customer_contact(
    request: Request,
    contact_id: int,
    data: OfflineCustomerContactCreateRequest = Body(...),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    try:
        op_user_id = request.user.id
        update_data = data.dict(exclude_unset=True)
        update_data.update({"update_by": op_user_id, "_id": contact_id})
        record_data = await update_offline_customer_contact_records(inter_session, update_data)
        va_msg = "更新成功"
        is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'msg'])
        if is_trans:
            va_msg = translation_dict.get(va_msg, va_msg)

        return ResultResponse(msg=va_msg, data=record_data)
    except ValidationError as e:
        return ResultResponse(code=40000, msg="参数错误", data=str(e))
    except ValueError as e:
        return ResultResponse(code=40000, msg="参数错误", data=str(e))
    except IntegrityError as e:
        return ResultResponse(code=40000, msg="已存在相同记录", data=str(e))
    except Exception as e:
        return ResultResponse(code=40000, msg="操作失败", data=str(e))


@offline_customer_translator_return
async def delete_offline_customer_contact(
    request: Request,
    contact_id,
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    try:
        if not contact_id:
            return ResultResponse(code=40000, msg="参数错误")
        await inter_session.execute(delete(OfflineCustomerContact).where(OfflineCustomerContact._id == contact_id))
        await inter_session.commit()
        return ResultResponse(msg="删除成功")
    except Exception as e:
        return ResultResponse(code=50000, msg="删除失败", data=str(e))


@offline_customer_translator_return
async def get_offline_customer_contacts(
    request: Request,
    customer_id: int,
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    try:
        if not customer_id:
            return ResultResponse(code=40000, msg="参数错误")
        base_query = select(OfflineCustomerContact)
        sort_conditions = [desc(OfflineCustomerContact.update_time)]
        query = base_query.where(OfflineCustomerContact.customer_id == customer_id).order_by(*sort_conditions)
        results = (await inter_session.execute(query)).scalars().all()
        return ResultResponse(msg="获取数据成功", data=results)
    except Exception as e:
        return ResultResponse(code=50000, msg="获取数据失败", data=str(e))


async def _extent_offline_customer_data_all(inter_session: Session,request, customer_result, customer_table_base_data):
    # 生效合同信息
    from apps.system.offline_customer.contract_service import get_offline_contract
    from apps.system.offline_customer.view.sys_offline_contract_view import _bundle_to_response, _format_contract_extent_data, get_key_options_from_filter_value, recursive_translate_data,change_category_tree
    current_contract_id = customer_result.get('current_contract_id', None)
    if not current_contract_id:
        return {}
    table_base_data = await async_get_one_title_mapping(inter_session, 315)
    table_base_data = await change_category_tree(request, table_base_data)
    bundle = await get_offline_contract(inter_session, current_contract_id, with_children=True)
    data = _bundle_to_response(bundle)
    filter_value = table_base_data.get("filter_value")
    contract = data.pop("contract")

    contract = await _format_contract_extent_data(request, inter_session, contract, filter_value)
    data.update(**contract)
    extent_cols = get_key_options_from_filter_value(filter_value)
    recursive_translate_data(data, extent_cols)

    not_in_list = ["_id", "create_time", "update_time", "create_by", "update_by", "customer_code", "customer_id", "status", "terminate_type", "current_step", "button_list_str"]
    data = {k: v for k, v in data.items() if k not in not_in_list}

    return data


@offline_customer_translator_return
async def get_sys_offline_customers_contract_detail(
    request: Request,
    offline_customer_id: str = "",
    is_show_config: int = 0,
    bi_session: Session = Depends(get_async_data_session),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    table_base_data = await async_get_one_title_mapping(inter_session, 148)
    table_base_data_set_price = await async_get_one_title_mapping(inter_session, 207)
    if not offline_customer_id and is_show_config == 0:
        return ResultResponse(code=40000, msg="参数错误", data=table_base_data)
    elif not offline_customer_id and is_show_config == 1:
        return ResultResponse(msg="获取数据成功", data=table_base_data)

    base_query = select(OfflineCustomer).where(OfflineCustomer._id == offline_customer_id)
    customer_result = (await inter_session.execute(base_query)).scalars().first()

    customer_addresses = (await inter_session.execute(
        select(OfflineCustomerAddress).where(OfflineCustomerAddress.customer_id == offline_customer_id, OfflineCustomerAddress.is_delete == 0)
    )).scalars().all()

    customer_contacts = (await inter_session.execute(
        select(OfflineCustomerContact).where(OfflineCustomerContact.customer_id == offline_customer_id, OfflineCustomerContact.is_delete == 0)
    )).scalars().all()

    customer_data = OfflineCustomerResponse.from_orm(customer_result)

    nation_vat_rate = 0.00

    filter_value = table_base_data_set_price.get("filter_value")
    nation_vat_rate_dict = {}
    for item in filter_value:
        key = item.get("key")
        if key == "vat_rate_dict":
            search_list = item.get("search_list")
            for s in search_list:
                nation_vat_rate_dict[s.get("value")] = s.get("label")

    final_data = {
        **customer_data,
        "addresses": [OfflineCustomerAddressListRequest.from_orm(addr).dict(by_alias=True) for addr in customer_addresses],
        "contacts": [OfflineCustomerContactListRequest.from_orm(contact).dict(by_alias=True) for contact in customer_contacts],
        "vat_rate": nation_vat_rate,
    }
    inresult = await _extent_offline_customer_data_all(inter_session,request, final_data, customer_table_base_data= table_base_data)

    final_data.update(inresult)

    customer_country = final_data.get("customer_country")
    if customer_country:
        nation_vat_rate = nation_vat_rate_dict.get(customer_country, nation_vat_rate)
        if customer_country in ["MY"]:
            nation_vat_rate = 0.00
        final_data.update({"vat_rate": nation_vat_rate})

    table_base_data.update({'tData': [final_data]})
    table_base_data.update({'table_key_group': []})
    return ResultResponse(msg="获取数据成功", data=table_base_data)


@offline_customer_translator_return
async def get_active_offline_customers(
    bi_session: Session = Depends(get_async_data_session),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    base_query = select(OfflineCustomer._id,OfflineCustomer.customer_code, OfflineCustomer.customer_short_name).where(
        OfflineCustomer.customer_status == 20,
        OfflineCustomer.current_contract_id != None
    )

    result = (await inter_session.execute(base_query)).all()

    data_list = [
        {"customer_code": row.customer_code, "customer_short_name": row.customer_short_name, "offline_customer_id":row._id}
        for row in result
    ]

    return ResultResponse(msg="获取数据成功", data=data_list)



write_client = DfToMySqlHelper(
    host=settings.HOST,
    db="bi",
    user=settings.USER,
    password=settings.PASSWORD,
    port=settings.PORT
)


async def update_customer_address(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_async_data_session),
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    try:
        content = await file.read()
        excel_list = ['xlsm', 'xlsx', 'xls']
        filename = file.filename or ""
        if not any(filename.lower().endswith(ext) for ext in excel_list):
            return {"code": 40000, "msg": "Invalid file type. Only Excel files are allowed."}
        file_stream = io.BytesIO(content)
        df = pd.read_excel(file_stream)
    except Exception as e:
        return {"code": 40000, "msg": f"File read error:{e}"}

    if df.empty: return {"code": 40000, "msg": f"该文件无数据"}

    try:
        excel_cls_mapping = {
            "地址ID": "_id",
            "地址-国家": "country",
            "地址-省州": "province",
            "地址-城市": "city",
            "地址-县区": "district",
            "地址-详细地址": "address",
            "地址-邮编": "post_code"
        }

        df = df.rename(columns=excel_cls_mapping)
        df.replace(np.nan, None, inplace=True)

        write_client.insert_many_by_executemany(table_name="internal_app.`data_sys_offline_customer_address`", tmp_df=df, with_id=True)

        return {"code": 200,"msg": "导入成功"}
    except Exception as e:
        logger.error(e)
        return {"code": 40000, "msg": f"File import error:{e}"}