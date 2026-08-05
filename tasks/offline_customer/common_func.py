# -* coding: utf-8 -*-
"""
# @Time    : 2026/3/17
# @Author  : Zhu Yaming
# @File    : common_func.py
# @Description : 
"""
import time
import datetime
import bisect
from dateutil import parser
import urllib.parse
from conf.settings import settings
from sqlalchemy import select, tuple_, func, update, insert
from apps.common.service.aliyun_oss import OSSRunner
from apps.system.reports.view.common_func import get_df_cache_bysql, get_df_bysql, get_common_dicts_cache_bysql
from apps.system.offline_customer.models import OfflineSellOutStock, OfflineSellOutSales
from datetime import timedelta
import pandas as pd
import io
from typing import Dict, Any
import logging

import os
import sys
sys.path.append(os.getcwd().split('apps')[0])

from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper
write_client = DfToMySqlHelper(
    host=settings.HOST,
    db="bi",
    user=settings.USER,
    password=settings.PASSWORD,
    port=3306
)

logger = logging.getLogger(__name__)

def safe_parse_date(value, default = None, formats = None):
    """
    安全地将各种类型的输入转换为 datetime.date 对象。

    参数:
        value: 输入值，可以是 string, datetime, date, int/float (时间戳), 或 None。
        default: 当解析失败或输入为 None 时返回的默认日期。默认为今天 (date.today())。
        formats: 可选的自定义日期格式列表。如果未提供，使用内置的常用格式列表。

    返回:
        datetime.date 对象。
    """
    # 1. 设置默认值
    if default is None:
        default = datetime.date.today()

    # 2. 处理 None 或 空字符串
    if value is None or (isinstance(value, str) and not value.strip()):
        return default

    # 3. 如果已经是 date 类型，直接返回
    if isinstance(value, datetime.date):
        if isinstance(value, datetime.datetime):
            return value.date()
        return value

    if isinstance(value, datetime.datetime):
        return value.date()

    if isinstance(value, (int, float)):
        try:
            if value > 1e10:
                ts = value / 1000.0
            else:
                ts = float(value)
            return datetime.datetime.fromtimestamp(ts).date()
        except (ValueError, OSError, OverflowError):
            return default

    if isinstance(value, str):
        value = value.strip()

        if formats is None:
            formats = [
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%Y%m%d",
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%d-%m-%Y",
                "%d/%m/%Y",
                "%m-%d-%Y",
                "%m/%d/%Y",
            ]

        for fmt in formats:
            try:
                dt_obj = datetime.datetime.strptime(value, fmt)
                return dt_obj.date()
            except ValueError:
                continue

        return default

    return default


def find_valid_sku(history_list, sales_date):
    """
    根据销售日期，在历史生效记录列表中查找匹配的 SKU。
    逻辑：找到 effective_date <= sales_date 且最接近 sales_date 的那条记录的 SKU。

    参数:
        1. 优先找到 effective_date <= sales_date 且最接近 sales_date 的那条记录的 SKU。
        2. 如果所有记录的 effective_date 都大于 sales_date（即 idx == 0），则返回最早的一条记录（列表第一条）。
        3. 如果列表为空，返回空字符串。

    返回:
        str: 匹配到的 SKU，如果未找到则返回空字符串
    """
    if not history_list:
        return ""

    target_date = sales_date
    if isinstance(target_date, datetime.datetime):
        target_date = target_date.date()

    search_target = (target_date, '\xff')

    idx = bisect.bisect_right(history_list, search_target)

    if idx > 0:
        return history_list[idx - 1][1]
    else:
        return history_list[0][1]


def safe_format_datetime(dt, fmt: str = "%Y-%m-%d %H:%M:%S"):
    """
    安全地将 datetime 对象格式化为字符串。

    参数:
        dt: 可能是 datetime 对象、字符串或 None
        fmt: 目标格式，默认去掉 'T'

    返回:
        格式化后的字符串，如果输入为 None 则返回 None
    """
    if dt is None:
        return None

    if isinstance(dt, str):
        return dt

    if isinstance(dt, datetime.datetime):
        return dt.strftime(fmt)

    return str(dt)


async def upload_df_to_oss(
        df: pd.DataFrame,
        file_name: str,
        file_type: str = "xlsx",
        file_path: str = "operation/attachment/sku_error",
) -> Dict[str, Any]:
    """
    将 Pandas DataFrame 生成文件并上传到 OSS。

    Args:
        df: Pandas DataFrame 对象。
        file_path: 存储的位置
        file_name: 期望的文件名 (例如: "data.xlsx")。
        file_type: 文件类型，目前支持 'xlsx'。

    Returns:
        包含结果或错误的字典。
    """

    if df is None or not isinstance(df, pd.DataFrame):
        return {'file': file_name, 'error': 'Invalid DataFrame provided'}

    if not file_name.endswith(f'.{file_type}'):
        file_name = f"{file_name}.{file_type}"

    safe_filename = urllib.parse.unquote(file_name)

    if not safe_filename.endswith(('.xls', '.xlsx')):
        return {'file': file_name, 'error': 'Only xls/xlsx files are allowed'}

    buffer = io.BytesIO()
    content = None  # 初始化变量

    try:
        if file_type == "xlsx":
            df.to_excel(buffer, index=False)
        elif file_type == "xls":
            df.to_excel(buffer, index=False, engine='xlwt')
        else:
            return {'file': file_name, 'error': f'Unsupported file type: {file_type}'}

        buffer.seek(0)
        content = buffer

    except Exception as e:
        logger.error(f"DataFrame 转换失败: {str(e)}")
        buffer.close()
        return {'file': file_name, 'error': f'DataFrame conversion failed: {str(e)}'}

    object_name = f"{file_path}/{safe_filename}"

    oss_runner = OSSRunner()

    try:
        upload_success = await oss_runner.async_upload_file(object_name, content)

        if not upload_success:
            return {'file': file_name, 'error': 'Upload to OSS failed'}

        signed_url = await oss_runner.async_sign_url(object_name)

        return {
            'file': safe_filename,
            'object_name': object_name,
            'url': signed_url,
            'status': 'success'
        }

    except Exception as e:
        logger.error(f"OSS 操作错误: {str(e)}")
        return {'file': file_name, 'error': str(e)}


async def get_customer_info_df(request):
    sql = """
    SELECT DISTINCT customer_code,customer_short_name, customer_country
    FROM `data_sys_offline_customers`
    """
    key = 'offline_customer_info'

    df = await get_df_cache_bysql(sql, key, request=request, db='inernal_app')
    return df


async def get_store_info_df(request):
    sql = """
    SELECT store_code, store_name, currency
    FROM (
        SELECT 
            store_code, 
            store_name, 
            currency,
            status,
            ROW_NUMBER() OVER (ORDER BY status DESC, store_code ASC) as rn
        FROM bi.data_offline_sell_out_sales
        WHERE status IS NOT NULL 
    ) t
    WHERE t.rn = 1;
    """

    df = await get_df_bysql(sql)
    return df


async def get_product_info_df(request):
    sql = """
    SELECT product_id, sku
    FROM bi.data_offline_customer_sku
    WHERE `status` =1 
    GROUP BY product_id
    """

    df = await get_df_bysql(sql)
    return df


async def get_user_name_dict(request):
    sql = """
        SELECT _id, name
        FROM internal_app.yy_user
        WHERE invalid_ind = 0
    """

    a_dict = await get_common_dicts_cache_bysql(sql,dict_name='offline_user_dict', request=request, db="internal_app")
    return a_dict


def get_next_day_str(date_str):
    if not date_str:
        return None
    dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    next_dt = dt + timedelta(days=1)
    return next_dt.strftime('%Y-%m-%d')


COUNTRY_CURRCNCY_DICT = {
        "TH":"THB",
        "VN":"VND",
        "SG":"SGD",
        "MY":"MYR",
        "ID":"IDR",
        "PH":"PHP",
        "MX":"MXN",
        "US":"USD",
        "UK":"USD",
        "EU":"EUR",
        "BR":"BRL"
}


async def disable_sales_or_stock_by_ids(request, session, ids, model_type):
    """
    根据主键id将 目标表中的数据制空
    """
    if model_type == "sales":
        set_cols = ["gmv", "gmv_usd", "sale_numbers", "thirty_sales_num"]
    else:
        set_cols = ["available_num", "available_cost"]

    customer_df = await get_customer_info_df(request)
    cus_name_dict = customer_df.set_index('customer_code')['customer_short_name'].to_dict()
    cus_country_dict = customer_df.set_index('customer_code')['customer_country'].to_dict()
    store_info = await get_store_info_df(request)
    store_currency_dict = store_info.set_index('store_code')['currency'].to_dict()
    product_info = await get_product_info_df(request)
    product_sku_dict = product_info.set_index('product_id')['sku'].to_dict()

    smodel = OfflineSellOutStock if model_type == 'stock' else OfflineSellOutSales
    try:
        stmt = select(smodel).where(smodel._id.in_(ids))
        result = await session.execute(stmt)
        result = result.scalars().all()
        all_tuples = []
        for item in result:
            customer_code = item.customer_code
            customer_short_name = cus_name_dict.get(customer_code, "")
            customer_country = cus_country_dict.get(customer_code, "")
            store_name = item.store_name
            sales_date = item.sales_date
            currency = store_currency_dict.get(item.store_code, "") if model_type == 'stock' else item.currency
            if not currency:
                currency = COUNTRY_CURRCNCY_DICT.get(customer_country, "")
            product_id = item.product_id
            product_code = product_sku_dict.get(product_id, "")

            key = (customer_short_name, customer_country, store_name, sales_date, currency, product_code)
            all_tuples.append(key)

        set_clause = ", ".join([f"{col} = NULL" for col in set_cols])

        if not all_tuples:
            logger.warning("all_tuples is empty, skipping update.")
        else:
            if len(all_tuples) > 0:
                tuple_len = len(all_tuples[0])
            else:
                tuple_len = 0

            single_placeholder = "(" + ", ".join(["%s"] * tuple_len) + ")"

            placeholders_list = ", ".join([single_placeholder] * len(all_tuples))

            update_sql = f"""
                UPDATE erp_data.data_offline_sell_out_sku_detail
                SET {set_clause}
                WHERE (customer_short_name, country, shop_name, update_date, currency, product_code) 
                IN ({placeholders_list})
            """

            params_tuple = tuple(val for tup in all_tuples for val in tup)

            try:
                s_time = time.time()
                rows_affected = write_client.do_action_sql_params(update_sql, params_tuple)
                logger.info(f"更新成功：共：{len(all_tuples)} 条记录，实际更新 {rows_affected} 行, 耗时：{time.time() - s_time:.2f}秒")
            except Exception as e:
                logger.error(f"Update failed: {e}")

    except Exception as e:
        await session.rollback()
        logger.error(f"Update Error:{e}")


def smart_parse_date(date_str):
    """固定会传入  2023-03-17 或者 20230317 或者 YYYY-MM-DD YYYY-M-D DD-MM-YYYY YYYY-MM-DD YYYY/M/D D/M/YYYY """
    if pd.isna(date_str) or str(date_str).strip() == '':
        return pd.NaT

    date_str = str(date_str).strip()

    formats = [
        '%Y-%m-%d',    # 2023-03-17
        '%Y%m%d',      # 20230317
        '%Y/%m/%d',    # 2023/3/17
        '%d-%m-%Y',    # 17-03-2023
        '%d/%m/%Y',    # 17/3/2023
    ]

    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    try:
        parsed = parser.parse(date_str, dayfirst=False, yearfirst=True)
        return parsed
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def get_table_key_cols(table_key_group, source=None):
    result_cols = []

    if not table_key_group:
        return result_cols

    for group in table_key_group:
        values = group.get('value', [])

        for item in values:
            if isinstance(item, dict):
                inner_value = item.get('value')
                source_val = item.get('source')
                key = item.get('key')
                if source_val == source:
                    if key:
                        result_cols.append(key)
                    else:
                        if isinstance(inner_value, list):
                            result_cols.extend(inner_value)
                        elif inner_value:
                            result_cols.append(inner_value)

    return result_cols
