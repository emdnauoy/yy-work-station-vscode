# -* coding: utf-8 -*-
"""
# @Time    : 2026/3/13
# @Author  : Zhu Yaming
# @File    : sys_offline_sell_out_sales.py
# @Description : 线下sellout销售数据
"""

import datetime, time
import io
import ast
import json
import math
import secrets
import string
import numpy as np
import urllib.parse
from typing import List, Dict, Any
from datetime import date

from fastapi import UploadFile, File, Response
from apps.common.model.yy_log import Log
import pandas as pd
from fastapi import Depends, Request, Body
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from loguru import logger
from sqlalchemy import select, tuple_, func, update, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.service.table_title_desc_mapping import async_get_one_title_mapping
from apps.common.service.yy_log import log_async_create
from apps.system.offline_customer.models import OfflineSellOutSales
from apps.system.offline_customer.view.sys_offline_sku_view import json_serializer
from apps.system.reports.view.common_func import (get_translaiton_dict_from_request, report_translate_output,
                                                  apply_translation_map, download_data_optimized, get_df_bysql)
from apps.system.offline_customer.models import OfflineCustomer, DataOfflineCustomerSku
from apps.system.offline_customer.common_func import find_valid_sku, safe_format_datetime, upload_df_to_oss, disable_sales_or_stock_by_ids, get_next_day_str,smart_parse_date
from conf.settings import settings
from core.db.session import get_async_session, get_async_data_session

auth_url_part = settings.AuthUrlPart
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=auth_url_part + "/login/")


@report_translate_output(fields_to_translate=[])
async def batch_update_offline_sales(
    request: Request,
    payload: List[Dict[str, Any]] = Body(..., description="批量更新的数据列表"),
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
    ):
    update_by_name = request.user.display_name
    ids = [item["_id"] for item in payload if item.get("_id")]

    stmt = select(OfflineSellOutSales).where(OfflineSellOutSales._id.in_(ids))

    result = await session.execute(stmt)
    old_rows = result.scalars().all()

    old_map = {row._id: row for row in old_rows}

    update_data = []
    logs_to_record = []
    update_ids = []

    for item in payload:
        _id = item.get("_id")
        if not _id: return {"code": 40000, "msg": "Missing _id in payload"}
        if isinstance(_id, str): _id = int(_id)
        old = old_map.get(_id)

        if not old:
            continue

        diff = {}

        for field in ["status"]:
            new_val = item.get(field)

            if new_val is None: continue

            old_val = getattr(old, field)

            if old_val != new_val:
                diff[field] = {"old": old_val,"new": new_val}
                if new_val == 0:
                    update_ids.append(_id)

        if not diff: continue

        update_data.append({
            "_id": _id,
            **{k: v["new"] for k, v in diff.items()},
            "update_by": request.user.id
        })

        logs_to_record.append({
            "refer_id": _id,
            "change_details": diff,
            "username": update_by_name
        })

    # 2 批量更新
    if update_data:
        await session.run_sync(
            lambda s: s.bulk_update_mappings(
                OfflineSellOutSales,
                update_data
            )
        )
        await session.commit()
        if update_ids:
            await disable_sales_or_stock_by_ids(request, session, update_ids, "sales")

    if logs_to_record:
        for log_item in logs_to_record:
            operation_details = json.dumps(
                log_item["change_details"],
                ensure_ascii=False,
                default=json_serializer
            )

            await log_async_create(
                username=log_item["username"],
                types="更新",
                operation_details=operation_details,
                session=inter_session,
                refer_type="offline_sell_out_sales",
                refer_table="data_offline_sell_out_sales",
                refer_id=log_item["refer_id"]
            )

    return {"code": 200, "msg": "批量更新成功"}


def generate_safe_traceable_batch():
    timestamp = datetime.datetime.now().strftime("%y%m%d%H%M")
    alphabet = string.ascii_uppercase + string.digits
    random_part = ''.join(secrets.choice(alphabet) for _ in range(5))

    return f"{timestamp}{random_part}"


@report_translate_output(fields_to_translate=[])
async def upload_offline_sell_out_sales(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
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
    current_rows = df.shape[0]
    if current_rows > 5000: return {"code": 40000, "msg": "上传数据过多,单次最多上传5000条"}

    excel_cls_mapping = {
        "*销售日期(Sales Date)(YYYY-MM-DD/DD-MM-YYYY)": "sales_date",
        "*客户编码(Customer Code)": "customer_code",
        "*币种(Currency)": "currency",
        "*店铺名称(Store Name)": "store_name",
        "*店铺编码(Store Code)": "store_code",
        "*Proudct ID": "product_id",
        "*销量(Item Sold)": "item_sold",
        "销售额(Sales)": "sales",
        "是否含税(Tax Included)": "is_tax",
        "批次号(Batch No.)": "batch_number"
    }

    cols = ["*销售日期(Sales Date)(YYYY-MM-DD/DD-MM-YYYY)", "*客户编码(Customer Code)", "*币种(Currency)", "*店铺名称(Store Name)", "*店铺编码(Store Code)", "*Proudct ID"]

    if not all(col in df.columns for col in cols):
        return {"code": 40000, "msg": "Missing required columns in the Excel file."}

    batch_number = generate_safe_traceable_batch()
    df['批次号(Batch No.)'] = batch_number

    target_first_cols = ['批次号(Batch No.)']
    valid_first_cols = [c for c in target_first_cols if c in df.columns]
    other_cols = [c for c in df.columns if c not in valid_first_cols]

    if df[cols].isna().any().any():
        null_cols = df[cols].columns[df[cols].isna().any()].tolist()
        return {
            "code": 40000,
            "msg": f"Detected empty values in required columns: {', '.join(null_cols)}. Please check the Excel file."
        }

    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['message', 'common', 'common_filters'])
    tax_dict = {"是":1, "否":0}
    revers_tax_dict = {v: k for k, v in tax_dict.items()}

    if "是否含税(Tax Included)" in df.columns:
        df["是否含税(Tax Included)"] = df["是否含税(Tax Included)"].apply(lambda x: tax_dict.get(x, None))

    df = df[valid_first_cols+other_cols]
    df = df.rename(columns=excel_cls_mapping, errors='ignore')

    df['create_by'] = request.user.id
    df['update_by'] = request.user.id
    df_sql = df.copy()
    df_sql['status'] = 1

    c_stmt = select(OfflineCustomer.customer_code).distinct()
    c_result = await session.execute(c_stmt)
    customer_codes = c_result.scalars().all()
    customer_codes = [code for code in customer_codes]

    success_count = 0
    error_list = []
    df_sql['sales_date'] = df_sql['sales_date'].apply(smart_parse_date)
    df_sql = df_sql.replace({np.nan: None})

    records = df_sql.to_dict('records')
    model = OfflineSellOutSales
    str_fields = ['customer_code', 'store_code', 'product_id']
    processed_keys = []

    try:
        for row in records:
            raw_date = row['sales_date']
            if isinstance(raw_date, pd.Timestamp):
                clean_date = raw_date.date()
            elif isinstance(raw_date, datetime.datetime):
                clean_date = raw_date.date()
            elif isinstance(raw_date, date):
                clean_date = raw_date
            elif isinstance(raw_date, str):
                try:
                    clean_date = pd.to_datetime(raw_date).date()
                except Exception as e:
                    logger.error(f"转换时间错误{e}")
                    clean_date = raw_date
            else:
                clean_date = raw_date
            row['sales_date'] = clean_date

            for field in str_fields:
                if pd.isna(row.get(field)):
                    row[field] = None
                else:
                    row[field] = str(row[field])

            key = (row['customer_code'], row['store_code'], row['sales_date'], row['product_id'])
            processed_keys.append(key)

        if not processed_keys:
            existing_keys_set = set()
        else:
            stmt = select(model.customer_code, model.store_code,model.sales_date, model.product_id).where(
                tuple_(model.customer_code, model.store_code, model.sales_date, model.product_id).in_(processed_keys),
                model.status == 1
            )

            result = await session.execute(stmt)
            existing_keys_set = set(result.all())

        success_count = 0
        for row in records:
            product_id_raw = row['product_id']
            product_id = "" if pd.isna(product_id_raw) else str(product_id_raw)
            customer_code = row['customer_code']

            if customer_code not in customer_codes:
                reason = "客户编码不存在"
                if is_trans:
                    reason = translation_dict.get(reason, reason)

                error_list.append({"data": row, "reason": reason})
                continue

            key_tuple = (row['customer_code'],row['store_code'],row['sales_date'], product_id)
            if any(pd.isna(item) for item in key_tuple):
                reason = "存在不能为空的数据列"
                if is_trans:
                    reason = translation_dict.get(reason, reason)
                error_list.append({
                        "data": row,
                        "reason": reason
                    })
                continue

            if not isinstance(row['sales_date'], datetime.date):
                reason = "时间格式错误"
                if is_trans:
                    reason = translation_dict.get(reason, reason)
                error_list.append({
                    "data": row,
                    "reason": reason
                })
                continue

            if key_tuple in existing_keys_set:
                reason = "已存在重复记录"
                if is_trans:
                    reason = translation_dict.get(reason, reason)
                error_list.append({
                    "data": row,
                    "reason": reason
                })
                continue

            if not row['item_sold'] and not row['sales']:
                reason = "无效数据"
                if is_trans:
                    reason = translation_dict.get(reason, reason)
                error_list.append({
                    "data": row,
                    "reason": reason
                })
                continue

            existing_keys_set.add(key_tuple)

            try:
                obj = model(**row)
                session.add(obj)
                await session.flush()
                await session.commit()

                await log_async_create(
                    username=request.user.display_name,
                    types="导入",
                    operation_details="",
                    session=inter_session,
                    refer_type="offline_sell_out_sales",
                    refer_table="data_offline_sell_out_sales",
                    refer_id=obj._id
                )
                success_count += 1
            except Exception as e:
                logger.info(f"{e}")
                await session.rollback()
                reason = f"ERROR:{e}"
                if is_trans:
                    reason = translation_dict.get(reason, reason)
                error_list.append({
                    "data": row,
                    "reason": f"{reason}"
                })

    except IntegrityError as e:
        logger.warning(f"Batch commit failed due to IntegrityError, switching to row-by-row processing: {e}")

    if error_list:
        error_data_rows = [item['data'] for item in error_list]
        error_reasons = [item['reason'] for item in error_list]
        df_error = pd.DataFrame(error_data_rows)
        df_error['错误原因(Error Reason)'] = error_reasons
        df_error['sales_date'] = pd.to_datetime(df_error['sales_date'], errors='coerce').dt.date
        reverse_mapping = {v: k for k, v in excel_cls_mapping.items()}

        df_error = df_error.rename(columns=reverse_mapping)
        if "是否含税(Tax Included)" in df_error.columns:
            if is_trans: revers_tax_dict = {v: translation_dict.get(k, k) for k, v in tax_dict.items()}
            df_error["是否含税(Tax Included)"] = df_error["是否含税(Tax Included)"].apply(lambda x: revers_tax_dict.get(x, x))
        df_error.drop(columns=['status', 'create_by', 'update_by'], errors='ignore',inplace=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Sales_Upload_Error_Records_{timestamp}.xlsx"
        result = await upload_df_to_oss(df_error, filename, file_path='operation/attachment/sales_error')

        return {
            "code": 200,
            "msg": "导入成功",
            "data": {
                "success_count": success_count,
                "error_count": len(error_list),
                "upload_file": result
            }
        }

    return {
        "code": 200,
        "msg": "导入成功",
        "data": {
            "success_count": success_count,
            "error_count": len(error_list)
        }
    }



# API tag: 运营-客户管理-线下sellout-销量明细
@report_translate_output(
    modules=['offline_customer', 'common_filters'],
    skip_trans_dict_value = ['sku', 'shop_name'],
    custom_translators=[("table_key_group", apply_translation_map), ("shop_info", apply_translation_map), ("filter_value", apply_translation_map)],
    common_params={
        'translatable_fields': ['name', 'title', 'label'],
        'kv_fields': ['shop_info', 'table_key_group'],
        'skip_fields': ['type', 'join', 'avg_data', 'values']
    }
)
async def get_offline_customer_slaes_list(
    request: Request,
    nation: str = "[]",
    customer_code: str = "[]",
    batch_number: str = "",
    customer_name_code: str = "",
    store_info: str = "",
    product_info: str = "",
    customer_type: str = "[]",
    customer_short_name: str = "[]",
    sku: str = "[]",
    offline_status:str = "[]",
    product_id: str = "",
    create_time_start: str = "",
    create_time_end: str = "",
    update_time_start: str = "",
    update_time_end: str = "",
    sales_date_start: str = "",
    sales_date_end: str = "",
    date_sort: str="{'key': 'create_time', 'value': 'descend'}",
    page: int = 1,
    pageSize: int = 10,
    is_download: int = 0,
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
    ):
    try:
        page_size = pageSize
        offset_data = int(page_size) * (int(page) - 1)
        if create_time_end: create_time_end = get_next_day_str(create_time_end)
        if update_time_end: update_time_end = get_next_day_str(update_time_end)
        nation = ast.literal_eval(nation)
        customer_code = ast.literal_eval(customer_code)
        customer_type = ast.literal_eval(customer_type)
        if customer_type == ["OTH"]:
            customer_type_first = ["OTH"]
            customer_type_second = []
        elif customer_type:
            customer_type_second = customer_type
            customer_type_first = []
        else:
            customer_type_first = []
            customer_type_second = []
        customer_short_name = ast.literal_eval(customer_short_name)
        sku = ast.literal_eval(sku)
        offline_status = ast.literal_eval(offline_status)
        sort_data = ast.literal_eval(date_sort)
    except Exception as e:
        return {"code": 40000, "msg": f"Params error:{e}"}

    table_mapping = await async_get_one_title_mapping(inter_session, menu_id=304)
    table_structure = table_mapping.get("filter_value", {})

    customer_condition = []
    customer_codes = None

    if customer_type_first or customer_type_second or customer_short_name or nation:

        if customer_name_code:
            pattern = f"%{customer_name_code.lower()}%"
            condition = (func.lower(OfflineCustomer.customer_code).like(pattern)) | \
                        (func.lower(OfflineCustomer.customer_short_name).like(pattern))
            customer_condition.append(condition)
        if customer_code: customer_condition.append(OfflineCustomer.customer_code.in_(customer_code))
        if customer_type_first: customer_condition.append(OfflineCustomer.customer_type_first.in_(customer_type_first))
        if customer_type_second: customer_condition.append(OfflineCustomer.customer_type_second.in_(customer_type_second))
        if customer_short_name: customer_condition.append(OfflineCustomer.customer_short_name.in_(customer_short_name))
        if nation: customer_condition.append(OfflineCustomer.customer_country.in_(nation))

        stmt = select(OfflineCustomer.customer_code).distinct().where(*customer_condition)
        result = await session.execute(stmt)
        customer_codes = result.scalars().all()
        customer_codes = [code for code in customer_codes]

    sku_condition = []
    md = OfflineSellOutSales
    if store_info:
        pattern = f"%{store_info}%"
        condition = (md.store_code.like(pattern)) | (md.store_name.like(pattern))
        sku_condition.append(condition)

    if product_info:
        pattern = f"%{product_info}%"
        condition = (md.product_id.like(pattern)) | (md.sku.like(pattern))
        sku_condition.append(condition)

    if batch_number: sku_condition.append(md.batch_number == batch_number)
    if customer_codes is not None: sku_condition.append(md.customer_code.in_(customer_codes))
    if product_id:
        sku_condition.append(md.product_id.like(f"%{product_id}%"))
    if sku:
        product_id_stmt = select(DataOfflineCustomerSku.product_id).distinct().where(
            DataOfflineCustomerSku.sku.in_(sku)
        )
        result = await inter_session.execute(product_id_stmt)
        product_id_list = result.scalars().all()
        sku_condition.append(md.product_id.in_(product_id_list))
    if offline_status: sku_condition.append(md.status.in_(offline_status))
    if create_time_start: sku_condition.append(md.create_time >= create_time_start)
    if create_time_end: sku_condition.append(md.create_time <= create_time_end)
    if update_time_start: sku_condition.append(md.update_time >= update_time_start)
    if update_time_end: sku_condition.append(md.update_time <= update_time_end)
    if sales_date_start: sku_condition.append(md.sales_date >= sales_date_start)
    if sales_date_end: sku_condition.append(md.sales_date <= sales_date_end)

    sort_col = sort_data.get('key', 'create_time')
    sort_order = sort_data.get('value', 'descend')
    if sort_order == 'ascend':
        order_by_data = [md.__table__.c[sort_col]]
    else:
        order_by_data = [md.__table__.c[sort_col].desc()]

    count_stmt = select(func.count()).select_from(md).where(*sku_condition)
    total_count = await session.scalar(count_stmt)

    if is_download: page_size=total_count

    stmt = select(md).where(*sku_condition).order_by(*order_by_data)

    result = await session.execute(stmt.offset(offset_data).limit(page_size))
    skus_result = result.scalars().all()
    sku_customer_codes = list({item.customer_code for item in skus_result})

    customer_dict = {}

    if sku_customer_codes:
        customer_info = (select(OfflineCustomer.customer_code, OfflineCustomer.customer_short_name, OfflineCustomer.customer_country,
                                OfflineCustomer.customer_type_first, OfflineCustomer.customer_type_second)
                         .where(OfflineCustomer.customer_code.in_(sku_customer_codes)))
        customer_info = await inter_session.execute(customer_info)
        customer_info = customer_info.fetchall()
        customer_dict = {info.customer_code: info for info in customer_info}

    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common', 'common_filters'])

    mssku = "SKU未匹配"
    data = []
    cus_sku_map = await get_customer_sku_dict(request)

    for sku in skus_result:
        customer_obj = customer_dict.get(sku.customer_code)
        short_name = customer_obj.customer_short_name if customer_obj else ""
        country = customer_obj.customer_country if customer_obj else ""
        # type_first = customer_obj.customer_type_first if customer_obj else ""
        # type_second = customer_obj.customer_type_second if customer_obj else ""
        # fstatus = status_dict.get(sku.status, sku.status)
        if  sku.is_tax == 1:
            fis_tax = "是"
        elif sku.is_tax == 0:
            fis_tax = "否"
        else:
            fis_tax = "-"

        if is_trans:
            # fstatus = translation_dict.get(fstatus, fstatus)
            fis_tax = translation_dict.get(fis_tax, fis_tax)
            # mssku = translation_dict.get(mssku, mssku)

        key = (sku.customer_code, sku.product_id)
        matched_sku = ""
        if key in cus_sku_map:
            history_list = cus_sku_map[key]
            matched_sku = find_valid_sku(history_list, sku.sales_date)

        data.append({
            "_id": sku._id,
            "batch_number": sku.batch_number,
            "sales_date": sku.sales_date.strftime('%Y-%m-%d') if sku.sales_date else "",
            "customer_code": sku.customer_code,
            "customer_short_name": short_name,
            "customer_country": country,
            "currency": sku.currency,
            "store_code": sku.store_code,
            "store_name": sku.store_name,
            "product_id": sku.product_id,
            "sku": matched_sku or mssku,
            "sales": sku.sales,
            "item_sold": sku.item_sold,
            "is_tax": fis_tax,
            "status": sku.status,
            "create_time": safe_format_datetime(sku.create_time),
            "update_time": safe_format_datetime(sku.update_time),
            "create_by": sku.create_by,
            "update_by": sku.update_by,
            "botton_list": ["select", "disable", "log"],
        })

    if is_download:
        filter_values = table_structure.get('filter_value', [])
        status_dict = {}

        for f in filter_values:
            if f["name"] == "状态":
                label_dict_list = f.get("search_list")
                for l in label_dict_list:
                    status_dict[l["value"]] = l["label"]

        for d in data:
            status = d.get("status", "")
            fstatus = status_dict.get(status, status)
            if is_trans:
                fstatus = translation_dict.get(fstatus, fstatus)
            d["status"] = fstatus

        download_headers = table_structure.get("download_headers", [])
        header = []
        data_col = []

        for head in download_headers:
            lab = head.get("label", "")
            val = head.get("value", "")
            header.append(lab)
            data_col.append(val)

        if is_trans:
            header = [translation_dict.get(lab, lab) for lab in header]

        sio, headers = await download_data_optimized(header, data_col, data, f"Offline_Customer_Sell_Out_Sales_{int(time.time())}")
        return StreamingResponse(sio, media_type='xls/xlsx', headers=headers)

    table_structure["tData"] = data
    table_structure["total"] = total_count
    table_structure["page"] = page
    table_structure["pageSize"] = page_size
    table_structure["totalPages"] = math.ceil(total_count/page_size)


    return {
        "code": 200,
        "msg": "获取数据成功",
        "data": table_structure
    }


async def get_customer_sku_dict(request):
    sql_s = """
        SELECT customer_code, product_id, sku, effective_date
        FROM bi.`data_offline_customer_sku`
        WHERE `status` = 1
        ORDER BY customer_code, product_id, effective_date
    """

    df = await get_df_bysql(sql_s)
    cus_sku_map = {}

    if not df.empty:
        if not isinstance(df['effective_date'].iloc[0], date):
            df['effective_date'] = pd.to_datetime(df['effective_date']).dt.date

        for _, row in df.iterrows():
            key = (row['customer_code'], row['product_id'])
            if key not in cus_sku_map:
                cus_sku_map[key] = []
            cus_sku_map[key].append((row['effective_date'], row['sku']))

        for key in cus_sku_map:
            cus_sku_map[key].sort(key=lambda x: x[0])

    return cus_sku_map


@report_translate_output(fields_to_translate=[])
async def batch_disabel_customer_slaes(
    request: Request,
    nation: str = "[]",
    customer_code: str = "[]",
    batch_number: str = "",
    customer_name_code: str = "",
    store_info: str = "",
    product_info: str = "",
    customer_type: str = "[]",
    customer_short_name: str = "[]",
    sku: str = "[]",
    offline_status:str = "[]",
    product_id: str = "",
    create_time_start: str = "",
    create_time_end: str = "",
    update_time_start: str = "",
    update_time_end: str = "",
    sales_date_start: str = "",
    sales_date_end: str = "",
    is_all: int = 1,
    operation_type: str = "disabel",
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
    ):
    try:
        if create_time_end: create_time_end = get_next_day_str(create_time_end)
        if update_time_end: update_time_end = get_next_day_str(update_time_end)
        nation = ast.literal_eval(nation)
        customer_code = ast.literal_eval(customer_code)
        customer_type = ast.literal_eval(customer_type)
        if customer_type == ["OTH"]:
            customer_type_first = ["OTH"]
            customer_type_second = []
        elif customer_type:
            customer_type_second = customer_type
            customer_type_first = []
        else:
            customer_type_first = []
            customer_type_second = []
        customer_short_name = ast.literal_eval(customer_short_name)
        sku = ast.literal_eval(sku)
        offline_status = ast.literal_eval(offline_status)
    except Exception as e:
        return {"code": 40000, "msg": f"Params error:{e}"}

    customer_condition = []
    customer_codes = None
    if not is_all or operation_type!="disabel":
        return {"code": 40000, "msg": "Invalid params: is_all or operation_type must be valid"}

    if customer_type_first or customer_type_second or customer_short_name or nation:

        if customer_name_code:
            pattern = f"%{customer_name_code.lower()}%"
            condition = (func.lower(OfflineCustomer.customer_code).like(pattern)) | \
                        (func.lower(OfflineCustomer.customer_short_name).like(pattern))
            customer_condition.append(condition)
        if customer_code: customer_condition.append(OfflineCustomer.customer_code.in_(customer_code))
        if customer_type_first: customer_condition.append(OfflineCustomer.customer_type_first.in_(customer_type_first))
        if customer_type_second: customer_condition.append(OfflineCustomer.customer_type_second.in_(customer_type_second))
        if customer_short_name: customer_condition.append(OfflineCustomer.customer_short_name.in_(customer_short_name))
        if nation: customer_condition.append(OfflineCustomer.customer_country.in_(nation))

        stmt = select(OfflineCustomer.customer_code).distinct().where(*customer_condition)
        result = await session.execute(stmt)
        customer_codes = result.scalars().all()
        customer_codes = [code for code in customer_codes]

    sku_condition = []
    md = OfflineSellOutSales
    if store_info:
        pattern = f"%{store_info}%"
        condition = (md.store_code.like(pattern)) | (md.store_name.like(pattern))
        sku_condition.append(condition)

    if product_info:
        pattern = f"%{product_info}%"
        condition = (md.product_id.like(pattern)) | (md.sku.like(pattern))
        sku_condition.append(condition)

    if batch_number: sku_condition.append(md.batch_number == batch_number)
    if customer_codes is not None: sku_condition.append(md.customer_code.in_(customer_codes))
    if product_id:
        sku_condition.append(md.product_id.like(f"%{product_id}%"))
    if sku:
        product_id_stmt = select(DataOfflineCustomerSku.product_id).distinct().where(
            DataOfflineCustomerSku.sku.in_(sku)
        )
        result = await inter_session.execute(product_id_stmt)
        product_id_list = result.scalars().all()
        sku_condition.append(md.product_id.in_(product_id_list))
    if offline_status: sku_condition.append(md.status.in_(offline_status))
    if create_time_start: sku_condition.append(md.create_time >= create_time_start)
    if create_time_end: sku_condition.append(md.create_time <= create_time_end)
    if update_time_start: sku_condition.append(md.update_time >= update_time_start)
    if update_time_end: sku_condition.append(md.update_time <= update_time_end)
    if sales_date_start: sku_condition.append(md.sales_date >= sales_date_start)
    if sales_date_end: sku_condition.append(md.sales_date <= sales_date_end)

    all_ids = []

    sku_condition.append(md.status==1)
    base_stmt = select(md._id).where(*sku_condition).order_by(md._id)

    batch_size = 500
    offset = 0

    while True:
        stmt = base_stmt.offset(offset).limit(batch_size)

        result = await session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            break

        all_ids.extend(rows)

        if len(rows) < batch_size:
            break

        offset += batch_size

    if all_ids:
        await disable_sales_or_stock_by_ids(request, session, all_ids, "sales")

    try:
        total_updated = 0
        for i in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[i: i + batch_size]

            stmt = update(md).where(md._id.in_(batch_ids), md.status==1).values(status=0)
            result = await session.execute(stmt)
            count = result.rowcount
            total_updated += count
        await session.commit()

    except Exception as e:
        await session.rollback()
        return {"code": 40000, "msg": f"Update error: {e}"}

    user_id = request.user.id
    user_name = request.user.display_name
    if all_ids and inter_session:
        logs_to_insert = []

        for row_id in all_ids:
            logs_to_insert.append({
                "user": user_name,
                "type": "批量作废",
                "refer_type": "offline_sell_out_sales",
                "refer_table": "data_offline_sell_out_sales",
                "refer_id": row_id,
                "operation_details": "",
                "create_datetime": datetime.datetime.now(),
                "user_id": user_id,
            })

        async with inter_session.begin():
            log_stmt = insert(Log).values(logs_to_insert)

            await inter_session.execute(log_stmt)

    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['message'])

    result = {"code": 200, "msg": "批量作废数据成功", "total": total_updated, "data": {}}

    if is_trans:
        result["msg"] = translation_dict.get(result["msg"], result["msg"])


    return result