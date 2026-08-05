# -* coding: utf-8 -*-
"""
# @Time    : 2026/3/9
# @Author  : Zhu Yaming
# @File    : sys_offline_sku_view.py
# @Description : 线下渠道客户SKU映射编码管理
"""

import ast
import datetime
import io
import json
import math
import urllib.parse
import os
import time
from typing import List, Dict, Any

from fastapi import UploadFile, File, Response
import pandas as pd
from fastapi import Depends, Request, status, Body
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import OAuth2PasswordBearer
from apps.common.model.yy_log import Log
from loguru import logger
from sqlalchemy import select, func, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from apps.common.service.table_title_desc_mapping import async_get_one_title_mapping
from apps.common.service.yy_log import log_async_create
from apps.system.offline_customer.models import OfflineCustomer, DataOfflineCustomerSku
from apps.system.market.models import DataInfoProductMstrJz
from apps.system.reports.view.common_func import download_data_optimized
from apps.system.reports.view.common_func import get_translaiton_dict_from_request, report_translate_output, apply_translation_map
from apps.system.offline_customer.common_func import safe_parse_date, safe_format_datetime, upload_df_to_oss, get_next_day_str
from conf.settings import settings
from core.db.session import get_async_session, get_async_data_session


auth_url_part = settings.AuthUrlPart
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=auth_url_part + "/login/")


@report_translate_output(fields_to_translate=[])
async def get_offline_customer_detail(
    request: Request,
    name: str = "",
    inter_session: Session = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    if not name: return {"code": 40000, "msg": "name is required"}

    search_pattern = f"%{name.lower()}%"
    stmt = select(OfflineCustomer).where(func.lower(OfflineCustomer.customer_short_name).like(search_pattern))
    result = await inter_session.execute(stmt)

    customers = result.scalars().all()

    data_list = [
        {
            "customer_short_name": c.customer_short_name,
            "customer_country": c.customer_country,
            "customer_code": c.customer_code
        }
        for c in customers
    ]

    return {
        "code": 200,
        "msg": "获取数据成功",
        "data": data_list
    }


@report_translate_output(fields_to_translate=[])
async def create_offline_customer_sku(
        request: Request,
        payload: dict,
        session: AsyncSession = Depends(get_async_data_session),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):
    customer_code = str(payload.get("customer_code", "")).strip()
    product_id = payload.get("product_id")
    sku = payload.get("sku")
    effective_date = safe_parse_date(payload.get("effective_date"), datetime.date(1970, 1, 1))
    remark = payload.get("remark")

    if effective_date is None:
        effective_date = datetime.date(1970, 1, 1)

    try:
        status_val = int(payload.get("status", 1))
    except (TypeError, ValueError):
        return {"code": 40000, "msg": "参数类型错误" }

    if not customer_code:
        return {"code": 40000, "msg": "缺少必要参数" }

    update_by_name = request.user.display_name

    obj = DataOfflineCustomerSku(
        customer_code=customer_code,
        product_id=product_id,
        sku=sku,
        status=status_val,
        effective_date=effective_date,
        remark=remark,
        create_by=request.user.id,
        update_by=request.user.id
    )

    try:
        async with session.begin():
            # 特殊重复值检验 customer_code + product_id + effective_date + status
            stmt = select(DataOfflineCustomerSku).where(
                DataOfflineCustomerSku.customer_code == customer_code,
                DataOfflineCustomerSku.product_id == product_id,
                DataOfflineCustomerSku.effective_date == effective_date
            )
            result = await session.execute(stmt)
            existing_record = result.scalars().first()
            if existing_record:
                return {"code": 40000, "msg": "已存在生效日期相同的记录"}

            session.add(obj)
            await session.flush()

    except IntegrityError:
        return {"code": 40000, "msg": f"存在重复记录"}

    new_id = obj._id

    change_dict = {
        "customer_code": customer_code,
        "product_id": product_id,
        "sku": sku,
        "status": status_val,
        "update_by": update_by_name,
        "effective_date": effective_date,
        "remark": remark
    }

    operation_details = json.dumps(
        change_dict,
        ensure_ascii=False,
        default=json_serializer
    )

    await log_async_create(
        username=update_by_name,
        types="新建",
        operation_details=operation_details,
        session=inter_session,
        refer_type='offline_customer_sku',
        refer_table='data_offline_customer_sku',
        refer_id=new_id
    )

    return {
        "code": 200,
        "msg": "新建成功",
        "data": {"_id": new_id}
    }

def json_serializer(obj):
    if obj is None:
        return "None"
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return str(obj)


@report_translate_output(fields_to_translate=[])
async def batch_update_offline_customer_sku(
    request: Request,
    payload: List[Dict[str, Any]] = Body(..., description="批量更新的数据列表"),
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme)
    ):
    update_by_name = request.user.display_name
    ids = [item["_id"] for item in payload if item.get("_id")]

    stmt = select(DataOfflineCustomerSku).where(DataOfflineCustomerSku._id.in_(ids))

    result = await session.execute(stmt)
    old_rows = result.scalars().all()

    old_map = {row._id: row for row in old_rows}

    update_data = []
    logs_to_record = []

    for item in payload:

        _id = item.get("_id")
        if not _id: return {"code": 200, "msg": "Missing _id in payload"}
        if isinstance(_id, str): _id = int(_id)
        old = old_map.get(_id)

        if not old:
            continue

        diff = {}

        for field in ["customer_code", "product_id", "sku", "status", "effective_date", "remark"]:
            new_val = item.get(field)

            if new_val is None: continue

            old_val = getattr(old, field)
            if field == "effective_date":
                old_val = old_val.strftime("%Y-%m-%d") if old_val else old_val

            if old_val != new_val:
                if field in ["sku", "product_id"]:
                    return {"code": 40000, "msg": "不允许编辑SKU或Product ID"}

                if field == "effective_date":
                    customer_code = getattr(old, "customer_code")
                    product_id = getattr(old, "product_id")
                    effective_date =  item.get( "effective_date")
                    stmt = select(DataOfflineCustomerSku).where(
                        DataOfflineCustomerSku.customer_code == customer_code,
                        DataOfflineCustomerSku.product_id == product_id,
                        DataOfflineCustomerSku.effective_date == effective_date
                    )
                    result = await session.execute(stmt)
                    existing_record = result.scalars().first()
                    if existing_record:
                        return {"code": 40000, "msg": "已存在生效日期相同的记录"}

                diff[field] = {"old": old_val,"new": new_val}

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
        try:
            await session.run_sync(
                lambda s: s.bulk_update_mappings(
                    DataOfflineCustomerSku,
                    update_data
                )
            )
            await session.commit()
        except IntegrityError as e:
            return {"code": 40000, "msg": f"IntegrityError: {e}"}

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
                refer_type="offline_customer_sku",
                refer_table="data_offline_customer_sku",
                refer_id=log_item["refer_id"]
            )

    return {"code": 200, "msg": "更新成功"}


# API tag: 运营-运营工具-运营上架商品监控列表
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
async def get_offline_customer_skus(
    request: Request,
    nation: str = "[]",
    customer_type: str = "[]",
    customer_name_code: str = "",
    customer_short_name: str = "[]",
    sku: str = "[]",
    offline_status:str = "[]",
    product_id: str = "",
    create_time_start: str = "",
    create_time_end: str = "",
    update_time_start: str = "",
    update_time_end: str = "",
    date_sort: str="{'key': 'create_time', 'value': 'descend'}",
    page: int = 1,
    pageSize: int = 10,
    is_download: int = 0,
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
    ):
    try:
        if create_time_end: create_time_end = get_next_day_str(create_time_end)
        if update_time_end: update_time_end = get_next_day_str(update_time_end)
        page_size = pageSize
        offset_data = int(page_size) * (int(page) - 1)
        nation = ast.literal_eval(nation)
        customer_type = ast.literal_eval(customer_type)
        sku = ast.literal_eval(sku)
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
        offline_status = ast.literal_eval(offline_status)
        sort_data = ast.literal_eval(date_sort)
    except Exception as e:
        return {"code": 40000, "msg": f"Params error:{e}"}

    table_mapping = await async_get_one_title_mapping(inter_session, menu_id=303)
    table_structure = table_mapping.get("filter_value", {})

    customer_condition = []
    customer_codes = None

    if customer_type_first or customer_type_second or customer_short_name or nation:
        if customer_name_code:
            pattern = f"%{customer_name_code.lower()}%"
            condition = (func.lower(OfflineCustomer.customer_code).like(pattern)) | \
                        (func.lower(OfflineCustomer.customer_short_name).like(pattern))
            customer_condition.append(condition)
        if customer_type_first: customer_condition.append(OfflineCustomer.customer_type_first.in_(customer_type_first))
        if customer_type_second: customer_condition.append(OfflineCustomer.customer_type_second.in_(customer_type_second))
        if customer_short_name: customer_condition.append(OfflineCustomer.customer_short_name.in_(customer_short_name))
        if nation: customer_condition.append(OfflineCustomer.customer_country.in_(nation))

        stmt = select(OfflineCustomer.customer_code).distinct().where(*customer_condition)
        result = await session.execute(stmt)
        customer_codes = result.scalars().all()
        customer_codes = [code for code in customer_codes]

    sku_condition = []
    if customer_codes is not None: sku_condition.append(DataOfflineCustomerSku.customer_code.in_(customer_codes))
    if product_id:
        sku_condition.append(DataOfflineCustomerSku.product_id.like(f"%{product_id}%"))

    if sku: sku_condition.append(DataOfflineCustomerSku.sku.in_(sku))
    if offline_status: sku_condition.append(DataOfflineCustomerSku.status.in_(offline_status))
    if create_time_start: sku_condition.append(DataOfflineCustomerSku.create_time >= create_time_start)
    if create_time_end: sku_condition.append(DataOfflineCustomerSku.create_time <= create_time_end)
    if update_time_start: sku_condition.append(DataOfflineCustomerSku.update_time >= update_time_start)
    if update_time_end: sku_condition.append(DataOfflineCustomerSku.update_time <= update_time_end)

    sort_col = sort_data.get('', 'create_time')
    sort_order = sort_data.get('value', 'descend')
    if sort_order == 'ascend':
        order_by_data = [DataOfflineCustomerSku.__table__.c[sort_col]]
    else:
        order_by_data = [DataOfflineCustomerSku.__table__.c[sort_col].desc()]

    count_stmt = select(func.count()).select_from(DataOfflineCustomerSku).where(*sku_condition)
    total_count = await session.scalar(count_stmt)

    if is_download: page_size=total_count

    stmt = select(DataOfflineCustomerSku).where(*sku_condition).order_by(*order_by_data)
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

    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['offline_customer', 'common_filters', 'common'])

    data = []
    # filter_values = table_structure.get('filter_value', [])
    # status_dict = {}
    #
    # for f in filter_values:
    #     if f["name"] == "状态":
    #         label_dict_list = f.get("search_list")
    #         for l in label_dict_list:
    #             status_dict[l["value"]] = l["label"]

    for sku in skus_result:
        customer_obj = customer_dict.get(sku.customer_code)
        short_name = customer_obj.customer_short_name if customer_obj else ""
        country = customer_obj.customer_country if customer_obj else ""
        type_first = customer_obj.customer_type_first if customer_obj else ""
        type_second = customer_obj.customer_type_second if customer_obj else ""
        # fstatus = status_dict.get(sku.status, sku.status)
        # if is_trans:
        #     fstatus = translation_dict.get(fstatus, fstatus)

        data.append({
            "_id": sku._id,
            "customer_code": sku.customer_code,
            "customer_short_name": short_name,
            "customer_country": country,
            "customer_type_first": type_first,
            "customer_type_second": type_second,
            "product_id": sku.product_id,
            "sku": sku.sku,
            "status": sku.status,
            "effective_date": sku.effective_date,
            "remark": sku.remark,
            "create_time": safe_format_datetime(sku.create_time),
            "update_time": safe_format_datetime(sku.update_time),
            "create_by": sku.create_by,
            "update_by": sku.update_by,
            "botton_list": ["select", "update", "log"]
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
            stat = d.get("status", "")
            fstatus = status_dict.get(stat, stat)
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

        sio, headers = await download_data_optimized(header, data_col, data, f"Offline_Customer_SKU_{int(time.time())}")
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


async def download_offline_customer_excel_template(
    request: Request,
    template_name: str = "线下客户sku导入模板",
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
    ):
    """
    1.线下客户sku导入模板
    2.线下Sell Out 销量数据导入模板
    3.线下Sell Out 库存数据导入模板
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))

    possible_extensions = ['.xlsx', '.xls']
    found_path = None
    real_extension = '.xlsx'

    root_template_dir = os.path.join(
        os.path.dirname(os.path.dirname(base_dir)),
        "templates"
    )

    for ext in possible_extensions:
        candidate = os.path.join(root_template_dir, f"{template_name}{ext}")
        if os.path.exists(candidate):
            found_path = candidate
            real_extension = ext
            break

        candidate_rel = os.path.join("apps", "system", "offline_customer", "templates", f"{template_name}{ext}")
        if os.path.exists(candidate_rel):
            found_path = candidate_rel
            real_extension = ext
            break

    if not found_path:
        return {"code": 404, "msg": f"Template '{template_name}' not found."}

    original_filename = f"{template_name}{real_extension}"

    encoded_filename = urllib.parse.quote(original_filename)

    ascii_filename = f"template{real_extension}"

    media_type = "application/vnd.ms-excel" if real_extension == '.xls' else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    content_disposition = f"attachment; filename={ascii_filename}; filename*=UTF-8''{encoded_filename}"

    headers = {
        "Content-Disposition": content_disposition
    }

    return FileResponse(
        path=found_path,
        media_type=media_type,
        filename=ascii_filename,
        headers=headers
    )


@report_translate_output(fields_to_translate=[])
async def upload_offline_customer_sku(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_data_session),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    try:
        update_by_name = request.user.display_name
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
    if current_rows > 3000: return {"code": 40000, "msg": "上传数据过多,单次最多上传3000条"}

    excel_cls_mapping = {
        "客户编码(Customer Code)": "customer_code",
        "Proudct ID": "product_id",
        "SKU": "sku",
        "状态(Status)": "status"
    }

    status_dict = { "启用":1, "禁用":0}

    if "状态(Status)" not in df.columns:
        df["状态(Status)"] = 1
    else:
        df["状态(Status)"] = df["状态(Status)"].apply(lambda x: status_dict.get(x, x))

    df = df.rename(columns=excel_cls_mapping, errors='ignore')
    if status not in df.columns:
        df["status"] = 1

    cols = ["customer_code", "product_id", "sku", "status"]

    if not all(col in df.columns for col in cols):
        return {"code": 40000, "msg": "Missing required columns in the Excel file."}

    df_sql = df[cols].dropna(subset=["customer_code", "product_id", "sku"])
    df_sql["effective_date"] = datetime.date(1970, 1, 1)

    c_stmt = select(OfflineCustomer.customer_code).distinct()
    c_result = await session.execute(c_stmt)
    customer_codes = c_result.scalars().all()
    customer_codes = [code for code in customer_codes]
    sku_stmt = select(DataInfoProductMstrJz.product_code_sku).distinct()
    sku_result = await session.execute(sku_stmt)
    skus = sku_result.scalars().all()
    skus = [sku for sku in skus]

    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['message'])

    if df_sql.empty:
        return {"code": 200, "msg": "No data to import."}

    error_list = []
    duplicate_mask = df_sql.duplicated(keep=False)

    duplicate_indices = df[duplicate_mask].index.tolist()

    if duplicate_indices:
        excel_rows = [str(i + 2) for i in duplicate_indices]
        count = len(excel_rows)
        display_rows = excel_rows[:5]
        suffix = ", ..." if count > 5 else ""

        msg = (
            f"Duplicate records found in the file. "
            f"Total duplicates: {count}. Please check Excel rows: {', '.join(display_rows)}{suffix}."
        )

        return {"code": 40000, "msg": msg}

    records = df_sql.to_dict('records')
    model = DataOfflineCustomerSku
    try:
        check_keys = [(r['customer_code'], r['product_id'], r['sku']) for r in records]

        stmt = select(model.customer_code,model.product_id,model.sku).where(
            tuple_(model.customer_code,model.product_id,model.sku).in_(check_keys)
        )

        result = await session.execute(stmt)
        existing_rows = set(result.all())

        for row in records:
            product_id_raw = row['product_id']
            product_id = "" if pd.isna(product_id_raw) else str(product_id_raw)
            sku = "" if pd.isna(row['sku']) else str(row['sku'])
            customer_code = row['customer_code']
            if sku not in skus:
                reason = "SKU不存在"
                if is_trans:
                    reason = translation_dict.get(reason, reason)

                error_list.append({"data": row, "reason": reason})
                continue

            if customer_code not in customer_codes:
                reason = "客户编码不存在"
                if is_trans:
                    reason = translation_dict.get(reason, reason)

                error_list.append({"data": row, "reason": reason})
                continue

            key_tuple = (row['customer_code'], product_id, sku)

            if key_tuple in existing_rows:
                reason = "已存在重复记录"
                if is_trans:
                    reason = translation_dict.get(reason, reason)

                error_list.append({"data": row, "reason": reason})
                continue

            existing_rows.add(key_tuple)

            try:
                row['update_by'] = request.user.id
                row['create_by'] = request.user.id

                new_obj = DataOfflineCustomerSku(**row)
                session.add(new_obj)

                await session.flush()
                await session.commit()
                new_id = new_obj._id

                change_dict = {
                    "customer_code": row['customer_code'],
                    "product_id": row['product_id'],
                    "sku": row['sku'],
                    "status": row['status']
                }
                operation_details = json.dumps(change_dict, ensure_ascii=False, default=json_serializer)

                await log_async_create(
                    username=update_by_name,
                    types="导入",
                    operation_details=operation_details,
                    session=inter_session,
                    refer_type='offline_customer_sku',
                    refer_table='data_offline_customer_sku',
                    refer_id=new_id
                )

            except (IntegrityError, Exception) as e:
                await session.rollback()
                if isinstance(e, IntegrityError):
                    logger.warning(f"Row skipped due to IntegrityError: {e}")
                    reason = f"Duplicate entry: {str(e.orig) if hasattr(e, 'orig') else str(e)}"
                else:
                    logger.error(f"Row skipped due to general error: {e}")
                    reason = f"Processing failed: {str(e)}"

                error_list.append({"data": row, "reason": reason})
                continue
    except IntegrityError as e:
        logger.warning(f"Batch commit failed:{e}")

    success_count = len(records) - len(error_list)

    if error_list:
        error_data_rows = [item['data'] for item in error_list]
        error_reasons = [item['reason'] for item in error_list]
        df_error = pd.DataFrame(error_data_rows)
        df_error.drop(columns=['effective_date', 'create_by', 'update_by'], inplace=True, errors='ignore')
        df_error['错误原因（Error Reason)'] = error_reasons
        reverse_mapping = {v: k for k, v in excel_cls_mapping.items()}
        reverse_status_dict = {v: k for k, v in status_dict.items()}
        df_error = df_error.rename(columns=reverse_mapping)
        df_error["状态(Status)"] = df_error["状态(Status)"].apply(lambda x: reverse_status_dict.get(x, x))

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Sku_Upload_EError_Records_{timestamp}.xlsx"
        result = await upload_df_to_oss(df_error, filename)

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

def get_display_dict(data, is_trans, translation_dict):
    display_dict = {}
    attr_dict = {}
    table_structure = data.get("filter_value", {})
    tb_key = table_structure.get("logs_headers", {})
    for tb in tb_key:
        la = tb.get("label", "")
        va = tb.get("value", "")
        if is_trans:
            la = translation_dict.get(la, la)
        display_dict[va] = la

    filter_value = table_structure.get("filter_value", [])
    for fil in filter_value:
        ctype = fil.get("ctype", "")
        if ctype == "select":
            key = fil.get("key", "")
            search_list = fil.get("search_list", [])
            k_map = {}
            for sl in search_list:
                la = sl.get("label", "")
                va = sl.get("value", "")
                if is_trans:
                    la = translation_dict.get(la, la)
                    k_map[va] = la

            attr_dict[key] = k_map

    return display_dict, attr_dict


def safe_parse_json_dict(value, default=None):
    """安全解析 JSON 字符串为字典"""
    if default is None: default = {}

    if not value: return default

    try:
        data = json.loads(value)
        if isinstance(data, dict):
            return data
        else:
            logger.warning(f"Parsed JSON is not a dict: {type(data)}. Content: {str(value)[:50]}")
            return default

    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Invalid JSON format. Error: {e}. Content: {str(value)[:100]}...")
        return default


@report_translate_output(fields_to_translate=[])
async def get_offline_logs(
        request: Request,
        mode_type: str = "sku",
        refer_id: int = None,
        session: AsyncSession = Depends(get_async_session),
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme)
    ):
    if not refer_id:
        return {"code": 40000, "msg": "refer_id is required"}

    tabel_map = {
        "sku": ["data_offline_customer_sku", "offline_customer_sku", 303],
        "sales": ["data_offline_sell_out_sales", "offline_sell_out_sales", 304],
        "stock": ["data_offline_sell_out_stock", "offline_sell_out_stock", 305]
    }

    if mode_type not in tabel_map:
        return {"code": 40000, "msg": "Invalid mode_type"}

    table_name = tabel_map[mode_type][0]
    table_type = tabel_map[mode_type][1]
    menu_id = tabel_map[mode_type][2]

    table_mapping = await async_get_one_title_mapping(inter_session, menu_id=menu_id)

    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['offline_customer','common', 'common_filters'])
    display_dict, attr_dict = get_display_dict(table_mapping,is_trans,translation_dict)

    stmt = (select(Log.user,Log.create_datetime,Log.operation_details,Log.type)
            .where(Log.refer_table==table_name,Log.refer_id ==refer_id,Log.refer_type==table_type).order_by(Log.create_datetime.desc()))
    log_sql_datas=(await inter_session.execute(stmt)).fetchall()
    log_data_lsit = [{'user':lsd.user,'ctime':lsd.create_datetime,'operation_details':lsd.operation_details,'type':lsd.type} for lsd in log_sql_datas]

    remark_info = []

    for log in log_data_lsit:
        op_details = safe_parse_json_dict(log.get("operation_details"))

        # 处理新增
        op_type = log.get("type", "")
        if op_type in ["新建", "导入"]: o_type = 0
        elif op_type in ["更新", "编辑", "修改", "作废", "批量作废"]: o_type = 1
        else: o_type = 0

        if is_trans: op_type = translation_dict.get(op_type, op_type)
        op_str = f'{log.get("user", "")}  {op_type} <br>'
        col_log_str = ''
        col_log_str = one_to_many_cols_log(op_details, col_log_str, attr_dict,display_dict,o_type)
        op_str += col_log_str
        op_details["create_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        ctime = log.get("ctime")
        remark_info.append({'time':datetime.datetime.strftime(ctime,'%Y-%m-%d %H:%M:%S'),'title':op_str})

    return {'code': 200, 'data': {'remark_info':remark_info}, 'msg': "获取数据成功"}


def one_to_many_cols_log(add_dict, col_log_str, attr_dict, columns_dict, log_type):
    """
    优化版：使用列表推导式或临时列表收集片段，最后一次性 join，提升性能。
    """
    if not add_dict:
        return col_log_str

    log_parts = []

    if col_log_str:
        log_parts.append(col_log_str)

    for add_key, add_value in add_dict.items():
        fragment = update_str(
            add_key,
            add_value,
            attr_dict,
            columns_dict,
            log_type
        )
        if fragment:
            log_parts.append(fragment)

    log_parts.append('<br>')

    return "".join(log_parts)


def get_flexible_display(value, mapping_dict):
    if not mapping_dict:
        return value

    lookup_key = value
    if isinstance(value, str):
        try:
            lookup_key = int(value)
        except ValueError:
            return value

    return mapping_dict.get(lookup_key, value)

def update_str(akey, avalue, attr_dict, columns_dict, log_type):
    mapping_dict = attr_dict.get(akey)

    if log_type == 1:
        old_val = None
        new_val = None
        if isinstance(avalue, dict) and "old" in avalue and "new" in avalue:
            old_val = avalue["old"]
            new_val = avalue["new"]
        elif isinstance(avalue, list) and len(avalue) >= 2:
            old_val, new_val = avalue[0], avalue[1]

        else:
            display_value = str(avalue)
            key_cn = columns_dict.get(akey, akey)
            return f'<b>【{key_cn}】</b>: {display_value},<br>'

        if mapping_dict:
            old_display = get_flexible_display(old_val, mapping_dict)
            new_display = get_flexible_display(new_val, mapping_dict)
        else:
            old_display = old_val
            new_display = new_val

        display_value = f"{str(old_display)}-->{str(new_display)}"

    elif log_type == 0:
        single_val = avalue
        if mapping_dict:
            display_value = mapping_dict.get(single_val, single_val)
        else:
            display_value = single_val

        display_value = str(display_value)
    else:
        display_value = str(avalue)

    key_cn = columns_dict.get(akey, akey)

    return f'<b>【{key_cn}】</b>: {display_value},<br>'