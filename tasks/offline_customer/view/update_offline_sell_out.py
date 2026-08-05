# -* coding: utf-8 -*-
"""
# @Time    : 2026/3/16
# @Author  : Zhu Yaming
# @File    : update_offline_sell_out.py
# @Description : 线下Sell Out 更新
"""
import asyncio
import concurrent.futures
import datetime
import time
import os
import sys
import uuid
from datetime import date
from decimal import Decimal
import threading
from typing import Dict

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from loguru import logger

from sqlalchemy import text
from apps.common.service.yy_log import log_async_create
from core.db.session import get_async_session
from apps.pyscript.sql_com.sql_com_reflash import pre_main
from apps.system.offline_customer.common_func import find_valid_sku
from apps.system.reports.view.common_func import get_translaiton_dict_from_request

TASK_REGISTRY: Dict[str, dict] = {}
registry_lock = threading.Lock()

executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

import pandas as pd
import numpy as np

sys.path.append(os.getcwd().split('apps')[0])

from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper
from conf.settings import settings

auth_url_part = settings.AuthUrlPart
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=auth_url_part + "/login/")

READ_ONLY_HOST = settings.READ_ONLY_HOST

import pymysql
erp_connect = pymysql.connect(host=settings.HOST, user=settings.USER, password=settings.PASSWORD, db="erp_data", port=3306, charset='utf8')
cursor = erp_connect.cursor()

my_client = DfToMySqlHelper(
    host=READ_ONLY_HOST,
    db="bi",
    user=settings.USER,
    password=settings.PASSWORD,
    port=3306
)

write_client = DfToMySqlHelper(
    host=settings.HOST,
    db="bi",
    user=settings.USER,
    password=settings.PASSWORD,
    port=3306
)

def get_offline_sku_list():
    sql_s = """
        SELECT customer_code, product_id, sku, effective_date
        FROM bi.`data_offline_customer_sku`
        WHERE `status` = 1
        ORDER BY customer_code, product_id, effective_date
    """
    df = my_client.get_df_by_sql(sql_s)
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


def get_sku_level_map(target_date):
    sql_s = f"""
        SELECT product_code as sku, nation, sku_level
        FROM internal_app.data_product_nation_level_change_log 
        where date_format(upload_start_date,'%Y-%m-%d') <= '{target_date}'
            and date_format(upload_end_date,'%Y-%m-%d') >= '{target_date}' 
        GROUP BY nation,product_code
    """

    df = my_client.get_df_by_sql(sql_s)
    if not df.empty:
        key = lambda x: (x['nation'], x['sku'])
        nation_sku_map = {}
        for _, row in df.iterrows():
            key_val = key(row)
            if key_val not in nation_sku_map:
                nation_sku_map[key_val] = row['sku_level']
        return nation_sku_map
    return {}


def get_sku_category_info():
    sql_s = f"""
        SELECT
          p.product_code_sku AS sku,
            CASE
              p.categories
              WHEN '小家电' THEN
                'HA'
              WHEN '家居' THEN
                '家居'
              WHEN ((0 <> '安防') OR (0 <> '影音及其他')) THEN
                '安防及影音'
              ELSE
                p.categories
            END AS category,
          p.first_category first_cat,
          p.secondary_category second_cat,
          p.three_level_category third_cat,
          IF(p.categories_id IS NULL, 0, p.categories_id) AS categories_id
        FROM
          bi.data_info_product_mstr_jz p
        """
    df = my_client.get_df_by_sql(sql_s)

    if not df.empty:
        return df

    return pd.DataFrame()


def process_row(row, cus_sku_map, sku_level_map, date_str= 'sales_date'):
    key = (row['customer_code'], row['product_id'])
    matched_sku = ""

    if key in cus_sku_map:
        history_list = cus_sku_map[key]
        matched_sku = find_valid_sku(history_list, row[date_str])

    sku_level = ""
    if matched_sku:
        sku_level = sku_level_map.get((row['country'], matched_sku), "")

    return pd.Series([matched_sku, sku_level], index=['sku', 'sku_level'])


def get_all_country_tax_config(target_date):

    sql = f"""
        select 
            a.country,
            a.tax,
            a.start_date,
            a.end_date
        from internal_app.country_tax_config a
        where a.status = 2
    """
    country_tax_df = write_client.get_df_by_sql(sql)
    target_date = pd.to_datetime(target_date)
    df = country_tax_df.copy()
    df['start_date'] = pd.to_datetime(df['start_date'], errors='coerce')
    df['end_date'] = pd.to_datetime(df['end_date'], errors='coerce')

    in_range = (df['start_date'] <= target_date) & \
               ((df['end_date'].isna()) | (target_date <= df['end_date']))

    df['effective_tax'] = np.where(in_range, df['tax'], 0)
    df['effective_tax'] = df['effective_tax'] + 1
    df['effective_tax'] = df['effective_tax'].apply(lambda x: Decimal(str(x)))
    return df[['country', 'effective_tax']]


def safe_decimal_convert(value):
    # 处理 NaN 或 None
    if pd.isna(value):
        return None

    try:
        str_value = str(value).strip()
        if not str_value or str_value.lower() in ['nan', 'none', 'null']:
            return None
        return Decimal(str_value)
    except Exception as e:
        logger.error(e)
        return None


def get_offline_sell_out_data(target_date):

    sql_s = f"""
        SELECT
          sales.customer_code,
          o.customer_short_name,
          o.customer_country as country,
          sales.currency,
          sales.store_code as shop_code,
          sales.store_name,
          sales.product_id,
          sales.sales_date,
          sales.sales,
          sales.sales/yer.exchange_rate AS sales_usd,
          sales.item_sold,
          sales.is_tax,
          case when stock.stock_num is null then 0 else stock.stock_num end as stock_num,
          sales_info.thirty_sales_num thirty_sales_num
        FROM
          bi.data_offline_sell_out_sales sales
        LEFT JOIN bi.data_offline_sell_out_stock stock ON 
        sales.customer_code = stock.customer_code
        AND sales.store_code = stock.store_code
        AND sales.sales_date = stock.sales_date
        AND sales.product_id = stock.product_id
        AND sales.`status` = stock.`status`
        LEFT JOIN internal_app.data_sys_offline_customers o on sales.customer_code = o.customer_code
        LEFT JOIN bi.yy_exchange_rate yer on yer.currency = sales.currency and yer.current_date = sales.sales_date 
        LEFT JOIN (
            select 
                sales.customer_code,
                sales.store_code, 
                '{target_date}' as sales_date,
                sales.product_id as product_id,
                sum(sales.item_sold) as thirty_sales_num
            from bi.data_offline_sell_out_sales sales
            WHERE sales.sales_date >= DATE_SUB('{target_date}', INTERVAL 29 DAY)
                    and sales.sales_date <= '{target_date}' AND `status` = 1
            group by sales.customer_code, sales.store_code, sales.product_id 
        ) sales_info 
            on sales_info.sales_date = sales.sales_date
            and sales_info.customer_code = sales.customer_code
            and sales_info.store_code = sales.store_code
            and sales_info.product_id = sales.product_id
        WHERE sales.`status` = 1 AND o.customer_short_name is not null and sales.sales_date = '{target_date}'
        
        UNION ALL
        
        SELECT 
          stock.customer_code,
          o.customer_short_name,
          o.customer_country as country,
          CASE WHEN s.currency IS NOT NULL THEN s.currency
          WHEN o.customer_country = 'TH' THEN 'THB'
            WHEN o.customer_country = 'VN' THEN 'VND'
            WHEN o.customer_country = 'SG' THEN 'SGD'
            WHEN o.customer_country = 'MY' THEN 'MYR'
            WHEN o.customer_country = 'ID' THEN 'IDR'
            WHEN o.customer_country = 'PH' THEN 'PHP'
            WHEN o.customer_country = 'MX' THEN 'MXN'
            WHEN o.customer_country = 'US' THEN 'USD'
            WHEN o.customer_country = 'UK' THEN 'USD'  
            WHEN o.customer_country = 'EU' THEN 'EUR'
            WHEN o.customer_country = 'BR' THEN 'BRL'
        ELSE o.customer_country end AS currency,
          stock.store_code as shop_code,
          stock.store_name,
          stock.product_id,
          stock.sales_date,
          0 AS sales,
          0 AS sales_usd,
          0 AS item_sold,
          1 AS is_tax,
          case when stock.stock_num is null then 0 else stock.stock_num end as stock_num,
          0 AS thirty_sales_num
        FROM
          bi.data_offline_sell_out_stock stock
        LEFT JOIN (
          SELECT store_code,store_name,currency  
          from bi.data_offline_sell_out_sales 
          GROUP BY store_code
        ) s on stock.store_code = s.store_code
        LEFT JOIN bi.data_offline_sell_out_sales sales ON 
        sales.customer_code = stock.customer_code
        AND sales.store_code = stock.store_code
        AND sales.sales_date = stock.sales_date
        AND sales.product_id = stock.product_id
        AND sales.`status` = stock.`status`
        LEFT JOIN internal_app.data_sys_offline_customers o on stock.customer_code = o.customer_code
        WHERE stock.`status` = 1 AND sales._id is null AND o.customer_short_name is not null
             and stock.sales_date = '{target_date}'
    """

    df = my_client.get_df_by_sql(sql_s)

    if not df.empty:
        cus_sku_map = get_offline_sku_list()
        sku_level_map = get_sku_level_map(target_date)
        sku_category_df = get_sku_category_info()
        result = df.apply(process_row, axis=1, args=(cus_sku_map, sku_level_map))

        titles =  ["update_date", "country", "customer_short_name", "shop_name", "product_code",
            "sku_level", "category", "first_cat", "second_cat", "third_cat", "currency", "gmv", "gmv_usd",
            "sale_numbers", "available_num", "thirty_sales_num", "available_cost", "categories_id","product_id" ,"shop_code", "customer_code"]

        df['sku'] = result['sku']
        df['sku_level'] = result['sku_level']

        df['sku'] = df['sku'].astype(str)
        if 'sku' in sku_category_df.columns:
            sku_category_df['sku'] = sku_category_df['sku'].astype(str)

        df['sku'] = df['sku'].replace('', np.nan)
        df = df.dropna(subset=['sku'])
        if df.empty:
            return pd.DataFrame()

        df = df.merge(sku_category_df, how='left', left_on='sku', right_on='sku')
        df.rename(columns={
            "store_name": "shop_name", "sku":"product_code", "sales_date":"update_date", "sales":"gmv", "sales_usd":"gmv_usd",
            "item_sold": "sale_numbers", "stock_num": "available_num"
            }, inplace=True)

        df['transport_num'] = 0
        df['available_cost'] = 0

        country_tax_df = get_all_country_tax_config(target_date)
        df = pd.merge(df, country_tax_df, on='country', how='left')

        df['gmv'] = np.where(df['is_tax'] == 0, df['gmv'] * df['effective_tax'], df['gmv'])
        df['gmv_usd'] = df['gmv_usd'].apply(safe_decimal_convert)
        df['gmv_usd'] = np.where(df['is_tax'] == 0, df['gmv_usd'] * df['effective_tax'], df['gmv_usd'])

        result_df = df.reindex(columns=titles, fill_value=None)
        for col in df.columns:
            df[col] = df[col].apply(lambda x: None if pd.isna(x) else x)

        return result_df

    return pd.DataFrame()

table_name = "erp_data.data_offline_sell_out_sku_detail"

def _sync_process_sell_out_data_logic():
    """
    同步手工数据
    """
    try:
        sql = """
            SELECT DISTINCT sales_date from  bi.data_offline_sell_out_sales WHERE status = 1 
            UNION 
            SELECT DISTINCT sales_date from  bi.data_offline_sell_out_stock WHERE status = 1 
            order by sales_date DESC 
        """

        df_date = my_client.get_df_by_sql(sql)
        date_list = []
        if not df_date.empty:
            date_list = df_date['sales_date'].tolist()

        if not df_date.empty:
            df_date["upload_datetime"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for dat in date_list:
            target_date = dat.strftime('%Y-%m-%d')
            logger.info(f"----同步数据中---·正再处理日期：{target_date}")
            date_df = get_offline_sell_out_data(target_date)

            unikey = ['update_date', 'customer_code', 'shop_name', 'shop_code', 'product_code', 'sku_level']

            # 判断重复的
            duplicate_records = date_df[date_df.duplicated(subset=unikey, keep=False)]

            print(f"共发现 {len(duplicate_records)} 条存在 unikey 重复的记录：")
            print(duplicate_records)

            if not date_df.empty:
                start_time = time.time()

                date_df["data_source_id"] = 1

                # business_keys = ["update_date", "shop_code", "shop_name", "customer_code", "product_code", "sku_level"]

                all_cols = list(date_df.columns)
                update_fields = [c for c in all_cols if c != "_id"]

                insert_cols = ", ".join([f"`{c}`" for c in all_cols])
                placeholders = ", ".join(["%s"] * len(all_cols))

                update_clause = ", ".join([
                    f"`{c}`=VALUES(`{c}`)" for c in update_fields
                ])

                sql = f"""
                   INSERT INTO {table_name} ({insert_cols})
                   VALUES ({placeholders})
                   ON DUPLICATE KEY UPDATE
                   {update_clause}
                   """

                values = (
                    date_df[all_cols]
                    .where(pd.notnull(date_df[all_cols]), None)
                    .to_numpy()
                    .tolist()
                )

                exec_start = time.time()

                try:
                    cursor.executemany(sql, values)
                    affected = cursor.rowcount
                    erp_connect.commit()
                    logger.info(
                        f"[UPSERT_EXEC_DONE] table={table_name}, "
                        f"executed_rows={len(values)}, "
                        f"rowcount={affected}, "
                        f"cost={time.time() - exec_start:.4f}s, "
                        f"total_cost={time.time() - start_time:.4f}s"
                    )

                except Exception as e:
                    erp_connect.rollback()

                    logger.error(
                        f"[UPSERT_FAILED] table={table_name}, "
                        f"error={str(e)}, "
                        f"cost={time.time() - start_time:.4f}s"
                    )
                    raise

                is_zero = (date_df['categories_id'] == 0).any()
                if is_zero:
                    update_sql = f"""
                    update erp_data.data_offline_sell_out_sku_detail set categories_id = 31612
                    where update_date = '{target_date}' and categories_id = 0
                    """
                    write_client.do_action_sql(update_sql)

        return True
    except Exception as e:
        logger.error(f"【线下Sell Out数据同步】同步数据时发生错误: {e}", exc_info=True)
        return False


def _run_full_task(task_id: str, user_name: str, cache):

    try:
        logger.info(f"[{task_id}] 开始执行【线下Sell Out数据同步】任务")

        success = _sync_process_sell_out_data_logic()

        if not success:
            with registry_lock:
                TASK_REGISTRY[task_id]["status"] = "FAILED"
            return

        logger.info(f"[{task_id}] 数据同步完成，开始刷新 Redis")

        redis_key_list = [
            "Report_Offline_Sell_out_Day_v1",
            "Report_Offline_Sell_out_Week_v1",
            "Report_Offline_Sell_out_Month_v1",
            "Report_Offline_Sell_out_Year_v1",
            "Report_Offline_Sell_out_Quarter_v1"
        ]

        # ✅ 正确方式：线程内事件循环
        loop = asyncio.new_event_loop()
        loop.run_until_complete(pre_main(redis_key_list))
        loop.close()

        async def _log():
            async with get_async_session() as session:
                await log_async_create(
                    username=user_name,
                    types="同步",
                    operation_details="",
                    session=session,
                    refer_type='offline_sales_sync',
                    refer_table='offline_sales_sync',
                    refer_id=task_id
                )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_log())
        loop.close()

        with registry_lock:
            TASK_REGISTRY[task_id]["status"] = "SUCCESS"

        logger.info(f"[{task_id}] 全流程执行成功")

    except Exception as e:
        with registry_lock:
            TASK_REGISTRY[task_id]["status"] = "FAILED"
            TASK_REGISTRY[task_id]["error"] = str(e)

        logger.error(f"[{task_id}] 任务异常: {e}", exc_info=True)


def submit_task_safe(user_name: str, cache):
    """
    原子化：检查 + 注册 + 提交
    """

    task_id = str(uuid.uuid4())

    executor.submit(_run_full_task, task_id, user_name, cache)

    return task_id

async def get_latest_offline_task_id(inter_session, refer_table=None):
    if refer_table is None: refer_table = "offline_sales_sync"

    sql = text("""
               SELECT refer_id, DATE_FORMAT(create_datetime, '%Y-%m-%d %H:%i:%s') AS sync_time
               FROM internal_app.yy_log
               WHERE refer_table = :table_name
               ORDER BY create_datetime DESC LIMIT 1
               """)

    params = {"table_name": refer_table}
    result = (await inter_session.execute(sql, params)).fetchone()

    if result is None:
        last_refer_id = None, None
    else:
        last_refer_id = result[0], result[1]

    return last_refer_id


async def sync_offline_sell_out_data(
        request: Request,
        inter_session: AsyncSession = Depends(get_async_session),
        token: str = Depends(oauth2_scheme),
):

    user_name = request.user.display_name

    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['message'])
    cache = request.app.state.data_cache
    cache_key = "off_line_data_sync"
    lock_acquired = await cache.set(cache_key, "LOCKED", ex=30 * 60, nx=True)
    if not lock_acquired:
        existing_task_id = await cache.get(cache_key)

        on_msg = "已有任务正在执行中，请稍后再试"
        if is_trans:
            on_msg = translation_dict.get(on_msg, on_msg)

        logger.warning(f"用户 {user_name} 尝试同步，但被拦截（已有任务运行）")
        return {
            "code": 40000,
            "msg": on_msg,
            "data": {
                "task_id": existing_task_id
            }
        }

    task_id = submit_task_safe(user_name, cache)

    try:
        await cache.set(cache_key, task_id, ex=20 * 60)
    except Exception as e:
        logger.error(f"[Cache Error] 更新缓存 TaskID 失败: {e}")

    su_msg = "同步中, 请稍后查看结果"
    if is_trans:
        su_msg = translation_dict.get(su_msg, su_msg)

    try:
        await log_async_create(
            username=user_name,
            types="同步",
            operation_details="",
            session=inter_session,
            refer_type='offline_sales_sync_start',
            refer_table='offline_sales_sync_start',
            refer_id=task_id
        )
    except Exception as e:
        logger.error(f"[{task_id}] Start log 写入失败: {e}", exc_info=True)

    logger.info(f"任务已提交: {task_id}, 锁已获取")
    return {
        "code": 200,
        "msg": su_msg,
        "data": {
            "task_id": task_id
        }
    }

async def get_task_status(task_id: str):
    task = TASK_REGISTRY.get(task_id)

    if not task: return {"code": 404, "msg": "task not found"}

    return {"code": 200, "data": task}

async def get_all_task_status():
    tasks = TASK_REGISTRY

    if not tasks: return {"code": 404, "msg": "task not found"}

    return {"code": 200, "data": tasks}


async def get_latest_offline_task(request: Request, inter_session: AsyncSession = Depends(get_async_session), token: str = Depends(oauth2_scheme)):

    last_refer_id, last_sync_time = await get_latest_offline_task_id(inter_session, "offline_sales_sync_start")

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "task_id": last_refer_id,
            "sync_time": last_sync_time
        }
    }


if __name__ == "__main__":
    _sync_process_sell_out_data_logic()