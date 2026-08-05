# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : distribution_order.py
# @Description : 分销订单主单 list / detail / draft.save
"""
import ast
import time
from decimal import Decimal
from typing import Any, Dict, List
import math
import datetime
from dateutil.relativedelta import relativedelta

from apps.system.reports.view.common_func import get_nation_currency_exchange_rate_df
from fastapi import Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_async_data_session, get_async_session
from apps.system.reports.view.common_func import (
    get_common_shop_dict, download_data_optimized, get_common_user_dict,
)

from apps.system.distribution_order.auth import oauth2_scheme
from apps.system.distribution_order.distribution_order_extent import (
    build_distribution_order_download_rows,
    format_order_extent_data,
    _extent_list_detail_data,
    get_table_config,
    _add_exchange_rate,
    patch_download_response_headers,
    resolve_download_columns,
)
from apps.system.reports.view.common_func import get_common_exchange_rate_dict
from apps.system.distribution_order.constants import STATUS_LABELS
from apps.system.distribution_order.distribution_order_service import (
    DistributionOrderError,
    append_list_date_range,
    append_list_datetime_range,
    build_distribution_order_list_order_by,
    build_order_save_data,
    get_distribution_order_detail,
    list_distribution_orders,
    save_distribution_order_create,
    save_distribution_order_draft,
    save_distribution_order_remark,
    void_distribution_order,
)
from apps.system.distribution_order.schemas import (
    DistributionOrderCreateIn,
    DistributionOrderDraftIn,
    RemarkSaveIn,
    VoidIn,
)
from apps.system.distribution_order.translate import (
    get_translaiton_dict_from_request,
    translate_all_output,
    translate_text,
)
from apps.system.distribution_order.distribution_order_workflow_engine import (
    build_execute_user_list_filter,
    list_execute_user_filter_options,
)
from apps.system.distribution_order.models import DistributionOrder
from apps.system.distribution_order.distribution_order_tags import lookup_exchange_rate
from apps.system.distribution_order.distribution_order_service import _serialize_list_row
from apps.system.distribution_order.operation_log import (
    LOG_SCOPE_ORDER_DETAIL, LOG_SCOPE_QUOTE_DETAIL,
    get_operator_display_name,
    log_distribution_order_create,
    log_distribution_order_update,
)

trans_target_fields = ["status_str", "void_from_status_str", "create_source_str", "cooperation_method_str", "msg", 'label', 'title', 'titles', 'placeholder', 'formTitle', 'name', 'delivery_method_str', 'settlement_method_str', 'fee_category_id_str', 'sample_policy_str',
             'table_name', 'keyDesc', 'table_name', 'data', 'tData', 'contact_frequency_str', 'contract_method_str', 'create_time', 'upodate_time', 'return_policy_str',
             'settlement_method_str', 'payment_method_str', 'effective_node_str', 'afterstr', 'customer_status_str', 'is_reviewing_str', 'is_pending_str', 'order_delivery_fee_payment_str',
             'order_status_str', 'tags_str', 'is_prepayment_str', "mt_delivery_mode_str", "desc"]
trans_skip_fields = ["page", "page_size", "total", "page_total"]


@translate_all_output(
    modules=["offline_customer","order_fulfillment", "common","common_filters", "msg"],
    translatable_fields=trans_target_fields,
    skip_fields=trans_skip_fields,
)
async def distribution_order_list(
    request: Request,
    keyword: str = "",
    order_sn: str = "",
    status: str = "[]",
    offline_customer_ids: str = "[]",
    customer_country: str = "[]",
    customer_type: str = "[]",
    customer_name_code: str = "",
    shop_id: str = "[]",
    tags: str = "[]",
    is_prepayment: str = "[]",
    settlement_method: str = "[]",
    logistics_status: str = "[]",
    order_status: str = "[]",
    execute_user_ids: str = "[]",
    batch_id: str = "",
    is_download: int = 0,
    date_type: str = "create_time",
    select_date_type: str = "day",
    status_type: str = "order_status",
    status_value: str = "[]",
    start_date: str = "",
    end_date: str = "",
    show_time: str = "",
    date_sort: str = "{'key':'create_time','value':'descend'}",
    page: int = 1,
    page_size: int = 50,
    is_show_config: int = 0,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    table_base_data = await get_table_config(inter_session, request, is_list=True)
    filter_value = table_base_data.get("filter_value") or []
    table_key_group = table_base_data.get("table_key_group", [])
    if is_show_config: return {"code": 200, "msg": "获取数据成功", "data": table_base_data}
    try:
        status_list = ast.literal_eval(status)
        offline_customer_ids = ast.literal_eval(offline_customer_ids)
        customer_country_list = ast.literal_eval(customer_country)
        customer_type_list = ast.literal_eval(customer_type)
        shop_id_list = ast.literal_eval(shop_id)
        tags_list = ast.literal_eval(tags)
        is_prepayment_list = ast.literal_eval(is_prepayment)
        settlement_method_list = ast.literal_eval(settlement_method)
        online_status_list = ast.literal_eval(status_value)
        order_status_list = ast.literal_eval(order_status)
        logistic_status_list = ast.literal_eval(logistics_status)
        execute_user_id_list = ast.literal_eval(execute_user_ids)
    except Exception as e:
        logger.error(f"参数错误：{e}")
        return {"code": 40000, "msg": "参数错误", "data": {}}
    if is_download == 1:
        page_size = 100000
    try:
        time_s = None
        time_e = None
        date_s = start_date
        date_e = end_date
        if len(start_date) > 10:
            time_s = start_date
            date_s = start_date[:10]
        if len(end_date) > 10:
            time_e = end_date
            date_e = end_date[:10]

        conds = [DistributionOrder.is_delete == 0]
        if offline_customer_ids: conds.append(DistributionOrder.offline_customer_id.in_(offline_customer_ids))
        if customer_country_list:  conds.append(DistributionOrder.customer_country.in_(customer_country_list))
        if customer_type_list:
            conds.append(
                or_(
                    DistributionOrder.customer_type_first.in_(customer_type_list),
                    DistributionOrder.customer_type_second.in_(customer_type_list),
                    customer_type_list == []
                )
            )

        if "Others" not in shop_id_list:
            conds.append(DistributionOrder.shop_id.in_(shop_id_list))
        else:
            conds.append(
                or_(
                    DistributionOrder.shop_id.in_(shop_id_list),
                    DistributionOrder.shop_id.is_(None)
                )
            )
        if status_list: conds.append(DistributionOrder.status.in_(status_list))
        if is_prepayment_list: conds.append(DistributionOrder.is_prepayment.in_(is_prepayment_list))
        if settlement_method_list: conds.append(DistributionOrder.settlement_method.in_(settlement_method_list))
        execute_user_filter = build_execute_user_list_filter(execute_user_id_list or [])
        if execute_user_filter is not None:
            conds.append(execute_user_filter)
        if order_sn:
            like = "%{}%".format(order_sn)
            conds.append(DistributionOrder.order_sn.like(like))

        batch_id = (batch_id or "").strip()
        if batch_id:
            conds.append(DistributionOrder.batch_id == batch_id)

        customer_name_code = (customer_name_code or "").strip()
        if customer_name_code:
            like = "%{}%".format(customer_name_code)
            conds.append(or_(DistributionOrder.customer_code.like(like),DistributionOrder.customer_short_name.like(like),))

        if date_s:
            date_s = datetime.datetime.strptime(date_s, "%Y-%m-%d").date()
            if hasattr(DistributionOrder, date_type):
                conds.append(getattr(DistributionOrder, date_type) >= date_s)
                if time_s:
                        conds.append(getattr(DistributionOrder, date_type) >= time_s)
        if date_e:
            date_e_add_one = datetime.datetime.strptime(date_e, "%Y-%m-%d").date() + relativedelta(days=1)
            if hasattr(DistributionOrder, date_type):
                conds.append(getattr(DistributionOrder, date_type) < date_e_add_one)
                if time_e:
                        conds.append(getattr(DistributionOrder, date_type) <= time_e)

        if tags_list:
            label_conditions = []
            for val in tags_list:
                try:
                    bit = int(val)
                except (TypeError, ValueError):
                    continue
                if bit <= 0:
                    continue
                label_conditions.append(
                    (DistributionOrder.tags_bitmask.op("&")(bit)) == bit,
                )
            if label_conditions:
                conds.append(or_(*label_conditions))

        if status_type == "order_status":
            if order_status_list: conds.append(DistributionOrder.order_status.in_(order_status_list))
        elif status_type == "online_status":
            if online_status_list: conds.append(DistributionOrder.online_status.in_(online_status_list))

        if order_status_list: conds.append(DistributionOrder.order_status.in_(order_status_list))
        if logistic_status_list: conds.append(DistributionOrder.logistic_status.in_(logistic_status_list))

        kw = (keyword or "").strip()
        if kw:
            like = "%{}%".format(kw)
            conds.append(
                or_(
                    DistributionOrder.order_sn.like(like),
                    DistributionOrder.customer_code.like(like),
                    DistributionOrder.customer_short_name.like(like),
                )
            )

        total = int(
            await inter_session.scalar(
                select(func.count(DistributionOrder._id)).where(*conds)
            ) or 0
        )
        page = max(page, 1)
        if is_download != 1:
            page_size = max(min(page_size, 200), 1)
        else:
            page_size = max(page_size, 1)
        offset = (page - 1) * page_size

        sort_data = ast.literal_eval(date_sort)
        sort_conditions = build_distribution_order_list_order_by(sort_data)

        rows = (
            await inter_session.execute(
                select(DistributionOrder).where(*conds)
                .order_by(*sort_conditions)
                .offset(offset).limit(page_size)
            )
        ).scalars().all()
        t_data = [_serialize_list_row(r) for r in rows]
        rows_dict = {r._id: r for r in rows}
        s_time = time.time()
        shop_dict = await get_common_shop_dict(request)
        for item in t_data:
            order = rows_dict.get(item["_id"])
            exchange_df = await get_nation_currency_exchange_rate_df(request, update_date="2026-05-15")
            exchange_nation_date_dict = exchange_df.set_index(["currency", "update_date"])["exchange_rate"].to_dict()
            await _extent_list_detail_data(request, item, inter_session, filter_value, shop_dict, order, exchange_nation_date_dict)
        logger.info(f"耗时：{time.time() - s_time:.2f}s")

        page_total = int(math.ceil(total / page_size)) if total else 0
    except DistributionOrderError as exc:
        data = {
            "t_data": [],
            "page": page,
            "page_size": page_size,
            "total": 0,
            "page_total": 0,
            "select_date_type": select_date_type,
            "status_type": status_type,
            "show_time": show_time
        }
        data.update(table_base_data)
        return {"code": 40000, "msg": exc.msg, "data": table_base_data}
    except Exception as e:
        logger.error(f"列表查询失败：{e}")
        data = {
            "t_data": [],
            "page": page,
            "page_size": page_size,
            "total": 0,
            "page_total": 0,
            "select_date_type": select_date_type,
            "status_type": status_type,
            "show_time": show_time
        }
        data.update(table_base_data)
        return {"code": 40000, "msg": "列表查询失败", "data": data}

    data = {
            "t_data": t_data,
            "page": page,
            "page_size": page_size,
            "total": total,
            "page_total": page_total,
            "select_date_type": select_date_type,
            "status_type": status_type,
            "show_time": show_time
        }
    data.update(table_base_data)

    if is_download:
        download_headers = []
        for item in filter_value:
            if item.get("key") == "download_headers":
                download_headers = item.get("options") or item.get("search_list") or []
                break
        columns = resolve_download_columns(download_headers, table_key_group)
        if not columns:
            return {"code": 40000, "msg": "未配置导出列", "data": {}}
        is_trans, translation_dict = get_translaiton_dict_from_request(
            request, ["offline_customer", "order_fulfillment", "common", "common_filters", "msg"],
        )
        excel_data = build_distribution_order_download_rows(
            t_data,
            columns,
            filter_value,
            exchange_rate_dict=await get_common_exchange_rate_dict(request),
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
        header = [col["label"] for col in columns]
        data_col = list(header)
        file_name = translate_text("分销下单", is_trans, translation_dict)
        if is_trans:
            header = [translation_dict.get(lab, lab) for lab in header]

        sio, resp_headers = await download_data_optimized(
            header,
            data_col,
            excel_data,
            file_name,
        )
        resp_headers = patch_download_response_headers(resp_headers, file_name)
        return StreamingResponse(sio, media_type="xls/xlsx", headers=resp_headers)

    return {"code": 200, "msg": "获取数据成功", "data": data}


async def distribution_order_execute_user_options(
    request: Request,
    keyword: str = "",
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
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
        msg = translate_text("获取数据失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": []}
    msg = translate_text("获取数据成功", is_trans, translation_dict)
    return {"code": 200, "msg": msg, "data": options}


@translate_all_output(
    modules=["offline_customer","order_fulfillment", "common","common_filters", "msg"],
    translatable_fields=trans_target_fields,
    skip_fields=trans_skip_fields,
)
async def distribution_order_detail(
    request: Request,
    order_id: int = None,
    is_show_config: int = 0,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    try:
        table_base_data = await get_table_config(inter_session, request)
        table_base_data = await _add_exchange_rate(request, table_base_data)

        if is_show_config: return {"code": 200, "msg": "获取数据成功", "data": table_base_data}
        if not order_id:
            return {"code": 40000, "msg":"获取数据失败"}
        data = await get_distribution_order_detail(inter_session, order_id)
        filter_value = table_base_data.get("filter_value") or []
        data = await format_order_extent_data(
            request, inter_session, data, filter_value,
        )
        table_base_data.update({'tData': [data]})
        table_base_data.update({'table_key_group': []})
    except DistributionOrderError as exc:
        return {"code": 40000, "msg": exc.msg, "data": {}}
    except Exception as e:
        logger.error(f"详情查询失败：{e}")
        return {"code": 40000, "msg": "详情查询失败", "data": {}}
    return {"code": 200, "msg": "获取数据成功", "data": table_base_data}


@translate_all_output(
    modules=["offline_customer","order_fulfillment", "common","common_filters", "msg"],
    translatable_fields=trans_target_fields,
    skip_fields=trans_skip_fields,
)
async def distribution_history_order_list(
    request: Request,
    offline_customer_id: int =None,
    order_sn: str = "",
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
):
    try:
        exchange_rate_dict = await get_common_exchange_rate_dict(request)
        conds = [DistributionOrder.is_delete == 0]
        conds += [DistributionOrder.status.in_([60, 70, 80, 90])]
        if offline_customer_id is not None:
            conds += [DistributionOrder.offline_customer_id == offline_customer_id]
        if order_sn is not None:
            conds += [DistributionOrder.order_sn != order_sn]

        rows = (await inter_session.execute(
            select(DistributionOrder._id, DistributionOrder.order_sn, DistributionOrder.status, DistributionOrder.order_amount_with_vat, DistributionOrder.currency,
                   DistributionOrder.create_time).where(*conds)
            .order_by(DistributionOrder.create_time.desc()))
        ).all()
        t_data = []
        total_usd = Decimal("0")
        for row in rows:
            rate = lookup_exchange_rate(row.currency, exchange_rate_dict) or Decimal("1")
            amt_usd = Decimal("0")
            if row.order_amount_with_vat is not None:
                amt_usd = Decimal(str(row.order_amount_with_vat)) / rate
                amt_usd = round(amt_usd, 2)
            total_usd += amt_usd
            t_data.append({
                "order_id": row._id,
                "order_sn": row.order_sn,
                "status": row.status,
                "status_str": STATUS_LABELS[row.status],
                "order_amount_with_vat": row.order_amount_with_vat,
                "order_amount_with_vat_usd": amt_usd,
                "currency": row.currency,
                "create_time": row.create_time,
            })

        if t_data:
            t_data.append({
                "order_sn": "合计",
                "is_summary": 1,
                "status": None,
                "order_amount_with_vat": total_usd,
                "order_amount_with_vat_usd": total_usd,
                "currency": "USD",
                "create_time": None,
            })
        return {"code": 200, "msg": "获取数据成功", "data": t_data}

    except Exception as e:
        logger.error(f"列表查询失败：{e}")
        return {"code": 40000, "msg": "列表查询失败", "data": []}


async def distribution_order_draft_save(
    request: Request,
    body: DistributionOrderDraftIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    operator_id = getattr(getattr(request, "user", None), "id", None)
    is_create = not body.id
    username = get_operator_display_name(request)
    try:
        table_base_data = await get_table_config(inter_session, request)
        filter_value = table_base_data.get("filter_value") or []
        old_data = None
        if not is_create:
            old_data = await get_distribution_order_detail(inter_session, int(body.id))
        exchange_rate_dict = await get_common_exchange_rate_dict(request)
        order_id, order_sn = await save_distribution_order_draft(
            inter_session, body, operator_id=operator_id,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
            exchange_rate_dict=exchange_rate_dict,
        )
        if is_create:
            await log_distribution_order_create(
                inter_session,
                username=username,
                order_id=order_id,
                snapshot=body.dict(exclude_unset=True, by_alias=True),
            )
        else:
            new_data = await get_distribution_order_detail(inter_session, order_id)
            new_quote_lines = new_data.pop("quote_details", None)
            old_data.pop("quote_details", None)
            await log_distribution_order_update(
                inter_session, username=username, order_id=order_id,
                old_data=old_data, new_data=new_data,
            )
            if new_quote_lines:
                await log_distribution_order_create(
                    inter_session, username=username, order_id=order_id,
                    snapshot=new_quote_lines, scope=LOG_SCOPE_QUOTE_DETAIL,
                )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        msg = translate_text(exc.msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"保存草稿失败：{e}")
        msg = translate_text("保存失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("保存成功", is_trans, translation_dict)
    return {
        "code": 200,
        "msg": msg,
        "data": build_order_save_data(order_id, order_sn),
    }


async def distribution_order_create_save(
    request: Request,
    body: DistributionOrderCreateIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    operator_id = getattr(getattr(request, "user", None), "id", None)
    username = get_operator_display_name(request)
    try:
        table_base_data = await get_table_config(inter_session, request)
        filter_value = table_base_data.get("filter_value") or []
        old_data = await get_distribution_order_detail(inter_session, int(body.id))
        exchange_rate_dict = await get_common_exchange_rate_dict(request)
        order_id, order_sn = await save_distribution_order_create(
            inter_session, body, operator_id=operator_id,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
            exchange_rate_dict=exchange_rate_dict,
        )
        new_data = await get_distribution_order_detail(inter_session, order_id)
        new_order_lines = new_data.pop("order_details", None)
        old_data.pop("order_details", None)
        await log_distribution_order_update(
            inter_session, username=username, order_id=order_id,
            old_data=old_data, new_data=new_data,
        )
        if new_order_lines:
            await log_distribution_order_create(
                inter_session, username=username, order_id=order_id,
                snapshot=new_order_lines, scope=LOG_SCOPE_ORDER_DETAIL,
            )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        msg = translate_text(exc.msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"订单创建保存失败：{e}")
        msg = translate_text("保存失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("保存成功", is_trans, translation_dict)
    return {
        "code": 200,
        "msg": msg,
        "data": build_order_save_data(order_id, order_sn),
    }


async def distribution_order_void(
    request: Request,
    body: VoidIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    inremark = body.remark
    if not inremark:
        msg = "请填写备注信息"
        msg = translate_text(msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}

    operator_id = getattr(getattr(request, "user", None), "id", None)
    try:
        data = await void_distribution_order(
            inter_session, body, operator_id=operator_id,
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        msg = translate_text(exc.msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"订单作废失败：{e}")
        msg = translate_text("操作失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("操作成功", is_trans, translation_dict)
    return {"code": 200, "msg": msg, "data": data}


async def distribution_order_remark_save(
    request: Request,
    body: RemarkSaveIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    operator_id = getattr(getattr(request, "user", None), "id", None)
    username = get_operator_display_name(request)
    try:
        old_data = await get_distribution_order_detail(inter_session, int(body.order_id))
        order_id = await save_distribution_order_remark(
            inter_session, body, operator_id=operator_id,
        )
        new_data = await get_distribution_order_detail(inter_session, order_id)
        await log_distribution_order_update(
            inter_session, username=username, order_id=order_id,
            old_data=old_data, new_data=new_data,
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        msg = translate_text(exc.msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"修改备注失败：{e}")
        msg = translate_text("操作失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("操作成功", is_trans, translation_dict)
    order_sn = new_data.get("order_sn") if isinstance(new_data, dict) else None
    return {
        "code": 200,
        "msg": msg,
        "data": build_order_save_data(order_id, order_sn),
    }
