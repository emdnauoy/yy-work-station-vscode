# -* coding: utf-8 -*-
"""
# @Time    : 2026/4/27
# @Author  : Zhu Yaming
# @File    : sys_offline_contract_view.py
# @Description : 
"""
import json
import traceback
import datetime
from decimal import Decimal
from distutils.util import execute
from typing import Optional, Any, List
import pandas as pd

from apps.common.model.yy_log import Log
from apps.common.service.table_title_desc_mapping import async_get_one_title_mapping
from loguru import logger
from fastapi import Request, Depends, Query, Body, HTTPException
from fastapi.security import OAuth2PasswordBearer
from apps.common.service.user import UserService
from apps.system.reports.view.common_func import safe_divide_vectorized, get_common_dicts_cache_bysql, get_df_cache_bysql, get_df_bysql, get_translaiton_dict_from_request, translate_all_output, get_erp_df_cache_bysql
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.service.yy_log import log_async_create
from sqlalchemy import select, text, desc, func
from apps.system.offline_customer.change_diff import parse_diff_log, deep_diff_create


from apps.system.offline_customer.schemas import (
    OfflineContractCreateRequest,
    OfflineContractUpdateRequest,
    OfflineContractDeleteRequest,
)
from apps.system.offline_customer.contract_service import (
    create_offline_contract,
    get_offline_contract,
    list_offline_contracts,
    update_offline_contract,
    delete_offline_contract,
    serialize_contract_entity,
    _get_contract_details,
)
from apps.system.offline_customer.contract_workflow_engine import (
    ACTION_ACTIVATE,
    ACTION_APPROVE,
    ACTION_REJECT,
    ACTION_SUBMIT,
    ACTION_TERMINATE,
    ACTION_WITHDRAW,
    CREATOR,
    APPROVER,
    STATUS_BUTTON_LIST,
)
from apps.system.offline_customer.models import OfflineContract, OfflineContractContact, OfflineCustomer, OfflineCustomerContact, OfflineCustomerAddress
from conf.settings import settings
from core.db.session import get_async_session
from core.response import ResultResponse

auth_url_part = settings.AuthUrlPart
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=auth_url_part + "/login/")

CONTRACT_LOG_REFER_TYPE = "offline_contract"
CONTRACT_LOG_REFER_TABLE = "data_sys_offline_contract"


def _log_json_default(obj: Any):
    if obj is None:
        return None
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _display_name(request: Request) -> str:
    u = getattr(request, "user", None)
    if u is None:
        return ""
    return getattr(u, "display_name", None) or getattr(u, "username", None) or str(getattr(u, "id", "") or "")


async def _write_contract_log(
    session,
    *,
    username: str,
    types: str,
    refer_id: int,
    payload: dict,
) -> None:
    operation_details = json.dumps(payload, ensure_ascii=False, default=_log_json_default)
    await log_async_create(
        username=username,
        types=types,
        operation_details=operation_details,
        session=session,
        refer_type=CONTRACT_LOG_REFER_TYPE,
        refer_table=CONTRACT_LOG_REFER_TABLE,
        refer_id=refer_id,
    )


def _bundle_to_response(bundle: dict) -> dict:
    if not bundle:
        return {}
    out = {
        "contract": serialize_contract_entity(bundle["contract"]),
        "uncond_rebates": [serialize_contract_entity(x) for x in bundle.get("uncond_rebates", [])],
        "cond_rebate_steps": [serialize_contract_entity(x) for x in bundle.get("cond_rebate_steps", [])],
        "address": bundle.get("address", {}),
        "contact": bundle.get("contact", {}),
    }
    wf = bundle.get("workflow")
    if wf:
        out["workflow"] = {
            "status_logs": [serialize_contract_entity(x) for x in wf.get("status_logs", [])],
        }
    return out


def serlize_response(bundle: dict) -> dict:
    if not bundle:
        return {}
    out = {}

    for key, value in bundle.items():
        out[key] = [serialize_contract_entity(x) for x in value]

    return out


async def _write_contract_flow_log(
    request: Request,
    inter_session,
    *,
    contract_id: int,
    types: str,
    meta: dict,
) -> None:
    bundle = await get_offline_contract(
        inter_session, contract_id, with_children=True, include_workflow=True
    )
    if not bundle:
        return
    log_body = {
        "update_by": _display_name(request),
        **meta,
        **_bundle_to_response(bundle),
    }
    await _write_contract_log(
        inter_session,
        username=_display_name(request),
        types=types,
        refer_id=int(contract_id),
        payload=log_body,
    )


def _transition_log_type(action_code: int) -> str:
    return {
        ACTION_SUBMIT: "提交审核",
        ACTION_APPROVE: "审核通过",
        ACTION_REJECT: "审核驳回",
        ACTION_WITHDRAW: "撤回审核",
        ACTION_TERMINATE: "终止合同",
        ACTION_ACTIVATE: "生效激活",
    }.get(action_code, f"状态迁移({action_code})")

traget_keys = [
    'name', 'title', 'label', 'msg', 'tips', 'table_name', 'desc', 'status_str', 'title', 'contract_method_str', 'settlement_method_str', 'is_prepayment_str','mt_has_delivery_target_str',
    'mt_has_penalty_str', 'payment_method_str', 'effective_node_str', 'mt_has_delivery_target_str', "fee_category_id_str", "calc_method_str", "uncond_rebates", "sample_policy_str",
    "delivery_method_str", "return_policy_str"
    ]
offline_contract_translator_return = translate_all_output(
    modules= ['common', 'message', 'common_filters', 'offline_customer'],
    translatable_fields=traget_keys,
    skip_fields=['date', 'form_data', 'pageSize', 'page', 'total', 'page_total', 'custom_date', 'keyDesc', 'page', 'pageSize', 'keyDesc', 'keyTitle', 'value', 'fixed', 'width']
)
msg_translator_return = translate_all_output(
    modules= ['offline_customer', 'meaasge'],
    translatable_fields=["none"],
    skip_fields=[ 'tData', 'data', 'pageSize', 'page', 'total', 'page_total', 'custom_date', 'keyDesc', 'page', 'pageSize', 'keyDesc', 'keyTitle', 'value', 'fixed', 'width']
)



@translate_all_output(
    modules= ['common', 'message', 'common_filters', 'offline_customer'],
    translatable_fields=traget_keys,
    skip_fields=['date', 'form_data', 'pageSize', 'page', 'total', 'page_total', 'custom_date', 'keyDesc', 'page', 'pageSize', 'keyDesc', 'keyTitle', 'value', 'fixed', 'width']
)
async def offline_contract_list(
    request: Request,
    page: int =1,
    pageSize: int = 50,
    customer_id: Optional[int] = Query(None),
    status: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    try:
        table_base_data = await async_get_one_title_mapping(inter_session, 315)
        table_base_data = await change_category_tree(request, table_base_data)
        total, rows = await list_offline_contracts(
            inter_session, page, pageSize, customer_id, status, country
        )
        page_total = (total + pageSize - 1) // pageSize
        t_data = [serialize_contract_entity(r) for r in rows]
        filter_value = table_base_data.get("filter_value")
        # 对每一个合同获取关联的信息
        for data in t_data:
            contract_id = data.get("_id")
            data = await _format_contract_extent_data(request, inter_session, data, filter_value)

            if contract_id:
                result_list = await _get_contract_details(inter_session, contract_id)
                result_list = serlize_response(result_list)
                data.update(result_list or {})

            extent_cols = get_key_options_from_filter_value(filter_value)
            recursive_translate_data(data, extent_cols)

        data = {
            "page": page,
            "pageSize": pageSize,
            "total": total,
            "page_total": page_total,
            "t_data": t_data
        }
        data.update(table_base_data)

        return ResultResponse(
            msg="获取数据成功",
            data=data
        )
    except Exception as e:
        logger.error(traceback.format_exc())
        return ResultResponse(code=40000, msg="获取数据失败", data=f"{e}")

async def _get_previous_role_step(db, country: str, current_step: int):
    """获取用户角色"""

    sql = text(f"""
        SELECT
          GROUP_CONCAT(DISTINCT u.`name`) as user_name,
          bs.`name` AS business_role,
          bs.`role_id` AS role_id,
          yrp.`value` AS country,
          dac.`step_no` AS step_no
        FROM
          `user_business_role_permission` yrp
          INNER JOIN business_role_config bsc ON bsc.id = yrp.role_config_id
          INNER JOIN business_role bs ON bsc.role_id = bs.role_id
          INNER JOIN data_sys_offline_contract_approval_config dac ON dac.role_id = bs.role_id
          INNER JOIN yy_user u ON yrp.user_id = u._id
        WHERE
         bsc.config_key = 'customer_nation' and yrp.value = :country
          AND dac.step_no < :current_step and dac.is_active = 1 AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
          group by bs.`role_id`
    """)
    roles = await db.execute(sql, {"country": country, "current_step": current_step})

    return [(row.user_name, row.business_role, row.step_no) for row in roles]


async def _get_now_role_step_users(db, country: str, current_step: int):
    """获取当前步骤执行人"""
    if not current_step: return None

    sql = text(f"""
        SELECT
          GROUP_CONCAT(DISTINCT u.`name`) as user_names
--           bs.`name` AS business_role,
--           bs.`role_id` AS role_id,
--           yrp.`value` AS country,
--           dac.`step_no` AS step_no
        FROM
          `user_business_role_permission` yrp
          INNER JOIN business_role_config bsc ON bsc.id = yrp.role_config_id
          INNER JOIN business_role bs ON bsc.role_id = bs.role_id
          INNER JOIN data_sys_offline_contract_approval_config dac ON dac.role_id = bs.role_id
          INNER JOIN yy_user u ON yrp.user_id = u._id
        WHERE
         bsc.config_key = 'customer_nation' and yrp.value = :country
          AND dac.step_no = :current_step and dac.is_active = 1 AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
          group by bs.`role_id`
    """)
    result = await db.execute(sql, {
        "country": country,
        "current_step": current_step
    })

    # 使用 .scalar() 获取 GROUP_CONCAT 的结果（如果查不到数据会返回 None）
    user_names = result.scalar()

    return user_names


def translate_list_values(lst, col_map):
    """辅助函数：专门用于翻译列表中的值"""
    result = []
    for item in lst:
        if not isinstance(item, dict):
            translated = col_map.get(item)
            if translated is not None:
                result.append(translated)
    return result


async def _get_user_previous_role_step(db,user_id:int, country: str, step: int):
    """获取用户角色"""

    sql = text(f"""
        SELECT
          u.`name` as user_name,
          bs.`name` AS business_role,
          bs.`role_id` AS role_id,
          yrp.`value` AS country,
          dac.`step_no` AS step_no
        FROM
          `user_business_role_permission` yrp
          INNER JOIN business_role_config bsc ON bsc.id = yrp.role_config_id
          INNER JOIN business_role bs ON bsc.role_id = bs.role_id
          INNER JOIN data_sys_offline_contract_approval_config dac ON dac.role_id = bs.role_id
          INNER JOIN yy_user u ON yrp.user_id = u._id
        WHERE yrp.user_id= :user_id AND
         bsc.config_key = 'customer_nation' and yrp.value = :country
          AND dac.step_no =:current_step AND dac.is_active = 1 AND bsc.invalid_ind = 0 AND bs.invalid_ind = 0 AND yrp.invalid_ind =0
    """)
    roles = await db.execute(sql, {"user_id": user_id, "country": country, "current_step": step})

    return [(row.user_name, row.business_role, row.step_no) for row in roles]



def recursive_translate_data(data, dict_map):
    if isinstance(data, dict):
        # 遍历字典副本，避免修改大小报错
        for key, value in list(data.items()):
            if key in dict_map and value is not None:
                col_map = dict_map[key]

                if isinstance(value, list):
                    translated_list = translate_list_values(value, col_map)
                    if translated_list:
                        data[f"{key}_str"] = translated_list

                elif not isinstance(value, dict):
                    translated_value = col_map.get(value)
                    if translated_value is not None:
                        data[f"{key}_str"] = translated_value

            if isinstance(value, dict):
                recursive_translate_data(value, dict_map)
            elif isinstance(value, list):
                recursive_translate_data(value, dict_map)

    elif isinstance(data, list):
        # 如果是列表，遍历每一项进行递归
        for item in data:
            recursive_translate_data(item, dict_map)


def get_key_options_from_filter_value(filter_value, target_keys=None):
    # 定义一个内部递归函数，用于遍历树形结构并提取 value: label
    def extract_tree_options(nodes):
        local_map = {}
        for node in nodes:
            value = node.get('value')
            label = node.get('label')
            # 如果当前节点有有效的 value 和 label，就加入映射表
            if value is not None and label is not None:
                local_map[value] = label

            # 如果当前节点有子节点（常见的字段名如 children, sub, list 等），则递归继续向下找
            children = node.get('children') or node.get('sub') or node.get('list')
            if children:
                # 将递归找到的子节点映射更新到当前映射表中
                local_map.update(extract_tree_options(children))
        return local_map

    result_dict = {}

    for item in filter_value:
        key = item.get('key')
        if target_keys and key not in target_keys: continue
        options = item.get('options') or item.get('search_list') or []

        if not key or not options:
            continue

        # 调用递归函数，获取包含所有层级节点的字典映射
        status_str = extract_tree_options(options)

        result_dict[key] = status_str

    return result_dict


async def _format_contract_extent_data(request,inter_session, data: dict, filter_value) -> dict:
    if not data:  return {}

    owner_staff_id = data.get("owner_staff_id")
    if owner_staff_id:
        from apps.system.user.models import User
        user = (
            await inter_session.execute(select(User).where(User._id == owner_staff_id))
        ).scalar_one_or_none()
        data["owner_staff_name"] = user.name if user else "No Matched"
    else:
        data["owner_staff_name"] = None

    # 当状态为审批 获取 可驳回的 到的 人, 1 审批人  2 创建人
    status = data.get("status")
    from apps.system.offline_customer.view.sys_offline_contract_approve import get_country_by_customer_id
    country = await get_country_by_customer_id(inter_session, data.get("customer_id"))
    button_list = STATUS_BUTTON_LIST.get(status, [])
    data["country"] = country
    # execute_user_name = None

    # if status == 10:
    #     execute_user_name = data.get("owner_staff_name")

    if status == 20:
        step_no = data.get("current_step")
        roles = await _get_user_previous_role_step(inter_session, request.user.id, country, step_no)
        # execute_user_name = await _get_now_role_step_users(inter_session, country, step_no)
        is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer'])
        if not roles:   button_list = [b for b in button_list if b != 'review']
        reject_to_info = []
        if step_no == 1:
            create_by = data.get("create_by")
            if create_by == 0:
                creator = "System"
            else:
                creator = await UserService.get_users_by_ids(inter_session, [create_by])
                creator = creator[0].name if creator else None
            submiter = "发起人"
            if is_trans: submiter = translation_dict.get(submiter, submiter)
            reject_to_info.append({"role": submiter, "operator_role": CREATOR, "name": creator, "to_status": 10, "to_step_no": None})
        else:
            create_by = data.get("create_by")
            if create_by == 0:
                creator = "System"
            else:
                creator = await UserService.get_users_by_ids(inter_session, [create_by])
                creator = creator[0].name if creator else None
            submiter = "发起人"
            if is_trans: submiter = translation_dict.get(submiter, submiter)
            reject_to_info.append({"role":submiter, "operator_role": CREATOR, "name": creator, "to_status": 10, "to_step_no": None})
            previous_roles = await _get_previous_role_step(inter_session, country, step_no)
            if previous_roles:
                for user_name, business_role, step_no in previous_roles:
                    if is_trans: business_role = translation_dict.get(business_role, business_role)
                    reject_to_info.append({"role": business_role, "operator_role": APPROVER, "name": user_name, "to_status": 20, "to_step_no": step_no})
        data["reject_to_info"] = reject_to_info

    # data["execute_user_name"] = execute_user_name
    data["button_list"] = button_list
    return data

@offline_contract_translator_return
async def offline_contract_detail(
    request: Request,
    contract_id: Optional[int] = None,
    is_show_config: int = 0,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    from  apps.system.offline_customer.view.sys_offline_contract_approve import _get_user_next_step
    # try:
    table_base_data = await async_get_one_title_mapping(inter_session, 315)
    table_base_data = await change_category_tree(request, table_base_data)
    if  is_show_config == 1:
        return ResultResponse(code=200,msg="获取数据成功", data=table_base_data)

    if not contract_id and is_show_config == 0:
        return ResultResponse(code=40000, msg="参数错误", data=table_base_data)

    bundle = await get_offline_contract(inter_session, contract_id, with_children=True)
    contract_raw = bundle.get('contract')
    next_step = await _get_user_next_step(inter_session, contract_raw, ACTION_APPROVE, contract_raw.current_step, request.user.id)
    has_approve_permission = next_step is not None

    data = _bundle_to_response(bundle)
    filter_value = table_base_data.get("filter_value")
    contract = data.pop("contract")
    contract = await _format_contract_extent_data(request,inter_session, contract, filter_value)
    data.update(**contract)
    data["has_approve_permission"] = has_approve_permission
    extent_cols = get_key_options_from_filter_value(filter_value)
    recursive_translate_data(data, extent_cols)

    table_base_data.update({'tData': [data]})
    table_base_data.update({'table_key_group': []})
    if not bundle:
        return ResultResponse(code=40000, msg="合同不存在", data=table_base_data)
    return ResultResponse(msg="获取数据成功", data=table_base_data)
    # except Exception as e:
    #     logger.error(traceback.format_exc())
    #     return ResultResponse(code=40000, msg="获取数据失败", data=f"{e}")

@msg_translator_return
async def offline_contract_create(
    request: Request,
    data: OfflineContractCreateRequest = Body(...),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    # try:
    user_id = request.user.id
    if not user_id:
        return ResultResponse(code=40000, msg="未登录", data=None)
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    customer_id = payload.get("customer_id")
    stmt = select(OfflineContract).where(
        OfflineContract.customer_id == customer_id,
        OfflineContract.status == 10
    )

    pending_contracts = (await inter_session.execute(stmt)).scalars().all()

    if pending_contracts:
        return ResultResponse(code=40000, msg="已存在待提交合同", data={})
    o = await create_offline_contract(inter_session, payload, user_id)
    if o:
        await _write_contract_log(
            inter_session,
            username=_display_name(request),
            types="新建",
            refer_id=int(o._id),
            payload=deep_diff_create(payload) or {},
        )
    return ResultResponse(msg="创建成功", data=serialize_contract_entity(o))
    # except ValueError as e:
    #     return ResultResponse(code=40000, msg=str(e), data=None)
    # except Exception as e:
    #     logger.error(traceback.format_exc())
    #     return ResultResponse(code=40000, msg="创建失败", data=f"{e}")

@msg_translator_return
async def offline_contract_update(
    request: Request,
    data = Body(...),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    try:
        payload = data
        c_id = payload.get("_id")
        contract_info = payload.pop("contact_info", None)
        if not c_id:
            raise ValueError("缺少 contract_id")
        user_id = request.user.id
        if not user_id:
            return ResultResponse(code=40000, msg="未登录", data=None)

        # 如果payload只有 {"_id"} 这时候不需要更新
        if set(payload.keys()) == {"_id"}:
            return ResultResponse(msg="更新成功", data={})

        o = await update_offline_contract(inter_session, payload, user_id, contract_id=c_id, user_name=_display_name(request))
        if not o:
            return ResultResponse(code=40000, msg="合同不存在", data=None)
        return ResultResponse(msg="更新成功", data=serialize_contract_entity(o))
    except ValueError as e:
        return ResultResponse(code=40000, msg=str(e), data=None)
    except HTTPException as e:
        return ResultResponse(code=e.status_code, msg=e.detail, data=None)
    except Exception as e:
        logger.error(traceback.format_exc())
        return ResultResponse(code=40000, msg="更新失败", data=f"{e}")

@msg_translator_return
async def offline_contract_delete(
    request: Request,
    data = Body(...),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    try:
        contract_id = data.get("_id")
        if not contract_id:
            raise ValueError("缺少 contract_id")
        ok = await delete_offline_contract(inter_session, contract_id)
        if not ok:
            return ResultResponse(code=40000, msg="合同不存在", data=None)
        return ResultResponse(msg="删除成功", data={"_id": contract_id})
    except ValueError as e:
        return ResultResponse(code=40000, msg=str(e), data=None)
    except HTTPException as e:
        return ResultResponse(code=e.status_code, msg=e.detail, data=None)
    except Exception as e:
        logger.error(traceback.format_exc())
        return ResultResponse(code=40000, msg=f"删除失败", data=f"{e}")


async def get_conract_category_fee_list(
    request: Request,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    """获取线下合同类目费用"""
    first_cat_order = ['销售费用', '营销费用']
    second_cat_order = [
        '无条件返利-大仓物流费', '不退货折扣', '无条件返利-系统使用费',
        '无条件返利-市场费', '无条件返利-后台毛利', '营销支持',
        '线上平台使用费/系统使用费', '新品费', '陈列费', '海报费',
        '特殊月份活动支持', '新店费', '门店装修费', '促销员费用',
        '样品费', '物料制作费', '促销费', '招待费', 'PC工资'
    ]

    sql = """
            SELECT DISTINCT first_fee_name first_cat , second_fee_name second_cat, remark initial_items, id
            FROM(
            select * from erp_data.fee_item_registry where platform = '分销' 
            AND first_fee_name NOT IN ("主营业务收入", "主营业务成本") 
            ) a
          """

    df_key = "all_category_fee_list"
    df = await get_erp_df_cache_bysql(sql, df_key, request, expire=12*60*60)
    if df.empty or df is None:
        return ResultResponse(code=40000, msg="获取数据失败", data=None)

    df[['first_cat', 'second_cat', 'initial_items', 'id']] = df[['first_cat', 'second_cat', 'initial_items', 'id']].fillna("默认项")

    df['first_cat_sort'] = pd.Categorical(df['first_cat'], categories=first_cat_order, ordered=True).codes
    df['first_cat_sort'] = df['first_cat_sort'].fillna(999).astype(int)

    second_cat_sort_map = {cat: i for i, cat in enumerate(second_cat_order)}
    df['second_cat_sort'] = df['second_cat'].map(second_cat_sort_map).fillna(999).astype(int)

    df_sorted = df.sort_values(by=['first_cat_sort', 'second_cat_sort'])

    records = df_sorted[['first_cat', 'second_cat', 'initial_items', 'id']].values.tolist()
    tree_map = {}

    for first_cat, second_cat, initial_items, item_id in records:
        # 1. 处理或创建一级类目节点
        if first_cat not in tree_map:
            tree_map[first_cat] = {
                "label": first_cat,
                "children": []
            }

        # 2. 查找或创建二级类目节点
        second_node = None
        for child in tree_map[first_cat]["children"]:
            if child["label"] == second_cat:
                second_node = child
                break

        if not second_node:
            second_node = {
                "label": second_cat,
                "children": []
            }
            tree_map[first_cat]["children"].append(second_node)

        # 3. 将初始项（三级/叶子节点）添加到二级类目的列表中
        existing_labels = [item["label"] for item in second_node["children"]]
        # 修改这里：append 时加上 value 字段，通常 value 就是数据库的 id
        if initial_items not in existing_labels:
            second_node["children"].append({
                "label": initial_items,
                "value": item_id
            })

    # 4. 将字典映射的值转换为最终的列表
    tree_data = list(tree_map.values())

    return ResultResponse(msg="获取数据成功", data=tree_data)


async def get_conract_category_fee_tree_data(request: Request):
    """获取线下合同类目费用"""
    first_cat_order = ['销售费用', '营销费用']
    second_cat_order = [
        '无条件返利-大仓物流费', '不退货折扣', '无条件返利-系统使用费',
        '无条件返利-市场费', '无条件返利-后台毛利', '营销支持',
        '线上平台使用费/系统使用费', '新品费', '陈列费', '海报费',
        '特殊月份活动支持', '新店费', '门店装修费', '促销员费用',
        '样品费', '物料制作费', '促销费', '招待费', 'PC工资'
    ]

    sql = """
            SELECT DISTINCT first_fee_name first_cat , second_fee_name second_cat, remark initial_items, id
            FROM(
            select * from erp_data.fee_item_registry where platform = '分销' 
            AND first_fee_name NOT IN ("主营业务收入", "主营业务成本") 
            ) a
          """

    df_key = "offline_all_category_fee_list"
    df = await get_df_cache_bysql(sql, df_key, request, expire=12*60*60)
    if df.empty or df is None:
        return False, []

    df[['first_cat', 'second_cat', 'initial_items', 'id']] = df[['first_cat', 'second_cat', 'initial_items', 'id']].fillna("默认项")

    df['first_cat_sort'] = pd.Categorical(df['first_cat'], categories=first_cat_order, ordered=True).codes
    df['first_cat_sort'] = df['first_cat_sort'].fillna(999).astype(int)

    second_cat_sort_map = {cat: i for i, cat in enumerate(second_cat_order)}
    df['second_cat_sort'] = df['second_cat'].map(second_cat_sort_map).fillna(999).astype(int)

    df_sorted = df.sort_values(by=['first_cat_sort', 'second_cat_sort'])

    records = df_sorted[['first_cat', 'second_cat', 'initial_items', 'id']].values.tolist()
    tree_map = {}

    for first_cat, second_cat, initial_items, item_id in records:
        # 1. 处理或创建一级类目节点
        if first_cat not in tree_map:
            tree_map[first_cat] = {
                "label": first_cat,
                "children": []
            }

        # 2. 查找或创建二级类目节点
        second_node = None
        for child in tree_map[first_cat]["children"]:
            if child["label"] == second_cat:
                second_node = child
                break

        if not second_node:
            second_node = {
                "label": second_cat,
                "children": []
            }
            tree_map[first_cat]["children"].append(second_node)

        # 3. 将初始项（三级/叶子节点）添加到二级类目的列表中
        existing_labels = [item["label"] for item in second_node["children"]]
        # 修改这里：append 时加上 value 字段，通常 value 就是数据库的 id
        if initial_items not in existing_labels:
            second_node["children"].append({
                "label": initial_items,
                "value": item_id
            })

    # 4. 将字典映射的值转换为最终的列表
    tree_data = list(tree_map.values())

    return True, tree_data


async def change_category_tree(
    request: Request,
    table_base_data
):
    filter_value = table_base_data.get("filter_value", [])
    for item in filter_value:
        key = item["key"]
        if key == "fee_category_id":
            is_sucess, tree_data = await get_conract_category_fee_tree_data(request)
            if is_sucess:
                item["options"] = tree_data
            else:
                table_base_data["类目错误"] = "未获取到类目树"

    return table_base_data

@msg_translator_return
async def get_contract_operator_logs(
    request: Request,
    contract_id: str = "",
    record_table: str = "data_sys_offline_contract",
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    # try:
    from apps.system.offline_customer.models import OfflineContractStatusLog  # 延迟导入
    from apps.system.offline_customer.contract_workflow_engine import ACTION_STR, STATUS_STR
    table_base_data = await async_get_one_title_mapping(inter_session, 315)
    table_base_data = await change_category_tree(request, table_base_data)
    filter_value = table_base_data.get("filter_value")
    if not all([contract_id, record_table]):
        return ResultResponse(code=40000, msg="参数错误")
    conditions = [
        Log.refer_id == contract_id,
        Log.refer_table == record_table
    ]
    base_query = select(Log).where(*conditions).order_by(desc(Log._id))
    results = (await inter_session.execute(base_query)).scalars().all()
    extent_cols = get_key_options_from_filter_value(filter_value)
    schemas = extent_cols.get("log_display")
    all_logs = []
    is_trans, translation_dict = get_translaiton_dict_from_request(request, ['offline_customer'])

    # 获取联系人
    stmt = select(OfflineCustomerContact._id, OfflineCustomerContact.name).where(OfflineCustomerContact.is_delete==0)
    contacts = await inter_session.execute(stmt)
    contact_dict = {c._id: c.name for c in contacts}
    extent_cols['contact_id'] = contact_dict

    full_address_expr = func.concat_ws(
        "",
        OfflineCustomerAddress.country,
        OfflineCustomerAddress.province,
        OfflineCustomerAddress.city,
        OfflineCustomerAddress.district,
        OfflineCustomerAddress.address,
        OfflineCustomerAddress.post_code
    )

    stmt = select(OfflineCustomerAddress._id, full_address_expr.label("full_address")).where(
        OfflineCustomerAddress.is_delete == 0
    )

    result = await inter_session.execute(stmt)
    # 直接通过字典推导式生成最终结果，逻辑极其清爽
    address_dict = {row._id: row.full_address for row in result}

    extent_cols['address_id'] = address_dict

    for record in results:
        o_details = json.loads(record.operation_details)
        op_time = record.create_datetime.strftime("%Y-%m-%d %H:%M:%S")
        user_name = record.user
        op_type = record.type
        ignore_keys = {"_id", "create_time", "update_time", "create_by", "update_by", "contact_info", "flow_id", "audit_flow_id"}
        for key in ignore_keys:
            if key in o_details:
                o_details.pop(key)
        title = parse_diff_log(o_details, schemas, key_value_dict=extent_cols, user_name=user_name, op_type=op_type, request=request,
                               ignore_keys=ignore_keys)
        log = {
            "content": "",
            "time": op_time,
            "user": user_name,
            "type": op_type,
            "title": title,
        }

        all_logs.append(log)

    # 操作日志
    logs = (
        await inter_session.execute(
            select(OfflineContractStatusLog)
            .where(OfflineContractStatusLog.contract_id == contract_id)
            .order_by(OfflineContractStatusLog.create_time, OfflineContractStatusLog._id)
        )
    ).scalars().all()

    for log in logs:
        operator_id = log.operator_id
        if operator_id != 0:
            operator = await UserService.get_users_by_ids(inter_session, [operator_id])
            operator_name = operator[0].name if operator else None
        else:
            operator_name = "System"

        from_status_str = STATUS_STR.get(log.from_status, log.from_status)
        to_status_str = STATUS_STR.get(log.to_status, log.to_status)
        action_code_str = ACTION_STR.get(log.action_code, log.action_code)
        remark = log.remark
        filed = "状态"
        remark_name = "驳回原因"

        if is_trans:
            from_status_str = translation_dict.get(from_status_str, from_status_str)
            to_status_str = translation_dict.get(to_status_str, to_status_str)
            action_code_str = translation_dict.get(action_code_str, action_code_str)
            filed = translation_dict.get(filed, filed)
            remark_name = translation_dict.get(remark_name, remark_name)

        remark_str = ""
        if remark:
            remark_str = " ," + remark_name + ": " + remark

        title = operator_name + " " + action_code_str + " " + "【 " + filed + ": " + from_status_str + " → " + to_status_str + remark_str + " 】"

        log_r = {
            "content": "",
            "time": log.create_time.strftime("%Y-%m-%d %H:%M:%S"),
            "user": operator_name,
            "type": "操作",
            "title": title,
        }
        all_logs.append(log_r)

    all_logs.sort(key=lambda x: x["time"], reverse=True)

    return ResultResponse(msg="获取数据成功" if all_logs else "暂无日志数据", data=all_logs)
    # except Exception as e:
    #     return ResultResponse(code=50000, msg="获取数据失败")
