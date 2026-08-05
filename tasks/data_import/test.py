# -* coding: utf-8 -*-
"""
# @Time    : 2026/4/14
# @Author  : Zhu Yaming
# @File    : real_time_erp_order_sync.py
# @Description : 实时qianyi订单同步
"""

import datetime
import optparse
import os
import sys
import time

import numpy as np

# timezone = pytz.timezone("Asia/Shanghai")

from loguru import logger
import pandas as pd
from multiprocessing import Pool

sys.path.append(os.getcwd().split('apps')[0])

from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper
from conf.settings import settings
from apps.pyscript.qianyi_api.common_serve import build_country_en

from concurrent.futures import ThreadPoolExecutor, as_completed
from apps.pyscript.sales_order_scripts.update_order_info_from_qy_db import update_order_info_from_qy_db_real_time

qy_client = DfToMySqlHelper(host=settings.QIANYIDB_HOST,db="gerp", user=settings.QIANYIDB_USER,password=settings.QIANYIDB_PASSWORD,port=settings.PORT)
my_read_client = DfToMySqlHelper(host=settings.READ_ONLY_HOST,db="bi",user=settings.USER,password=settings.PASSWORD,port=settings.PORT)
my_client = DfToMySqlHelper(host=settings.HOST,db="bi",user=settings.USER,password=settings.PASSWORD,port=settings.PORT)

CACHE_TIME_FILE = os.path.join(os.path.dirname(__file__), "real_time_erp_order_sync_time.txt")
SQL_TIME_FILE = os.path.join(os.path.dirname(__file__), "real_time_erp_order_sql_time.txt")

def _save_sync_time():
    """保存缓存运行时间"""
    with open(CACHE_TIME_FILE, "w") as f:
        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

def _read_sync_time() -> str:
    """读取缓存运行时间"""
    if not os.path.exists(CACHE_TIME_FILE):
        return None
    with open(CACHE_TIME_FILE, "r") as f:
        return f.read()

def _delete_sync_time():
    """删除缓存运行时间文件"""
    if os.path.exists(CACHE_TIME_FILE):
        os.remove(CACHE_TIME_FILE)

def _save_sql_time():
    """保存缓存运行时间（当前时间往前推1小时）"""
    # 计算当前时间减去1小时
    one_hour_ago = datetime.datetime.now() - datetime.timedelta(hours=1)

    with open(SQL_TIME_FILE, "w") as f:
        # 写入推算后的时间
        f.write(one_hour_ago.strftime("%Y-%m-%d %H:%M:%S"))

def _read_sql_time() -> str:
    """读取读取备库数据时间"""
    if not os.path.exists(SQL_TIME_FILE):
        return datetime.datetime.now().strftime("%Y-%m-%d 00:00:00")
    with open(SQL_TIME_FILE, "r") as f:
        return f.read()

def _delete_sql_time():
    """删除上次sql时间文件"""
    if os.path.exists(SQL_TIME_FILE):
        os.remove(SQL_TIME_FILE)


# # 实行夏令时的 IANA 时区统一按冬令时（标准时间）固定偏移，不随 DST 切换
# WINTER_TZ_OFFSET_HOURS = {
#     "Europe/Berlin": 1,
#     "Europe/Paris": 1,
#     "Europe/Rome": 1,
#     "Europe/Madrid": 1,
#     "Europe/London": 0,
#     "America/New_York": -5,
#     "America/Toronto": -5,
#     "Australia/Sydney": 10,
#     "Pacific/Auckland": 12,
#     "America/Santiago": -4,
#     "America/Sao_Paulo": -3,
# }


# def _resolve_tz(tz_name):
#     """夏令时时区取冬令时固定偏移；无 DST 的时区仍用 pytz"""
#     from datetime import timezone, timedelta
#     if tz_name in WINTER_TZ_OFFSET_HOURS:
#         return timezone(timedelta(hours=WINTER_TZ_OFFSET_HOURS[tz_name]))
#     import pytz as _pytz
#     return _pytz.timezone(tz_name)


# def _localize_naive_dt(naive_dt, tz_name):
#     # tz = _resolve_tz(tz_name)
#     if tz_name in WINTER_TZ_OFFSET_HOURS:
#         return naive_dt.replace(tzinfo=tz)
#     return tz.localize(naive_dt)


def batch_convert_format_date_time_zone(df, time_cols, tz_col, output_cols):
    for i, col in enumerate(time_cols):
        if col not in df.columns:
            continue

        out_col_name = output_cols[i]
        raw_col = df[col].copy()

        def convert_single_row(ts, tz_name):
            if pd.isna(ts) or pd.isna(tz_name):
                return None, None
            try:
                ts = float(ts)
                if ts > 1e11:
                    ts = ts / 1000.0

                import pytz as _pytz
                tz = _pytz.timezone(tz_name)
                from datetime import datetime as _dt, timezone as _tz
                utc_dt = _dt.fromtimestamp(ts, tz=_tz.utc)
                local_dt = utc_dt.astimezone(tz)
                fmt_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")
                local_ts = int(local_dt.timestamp() * 1000)
                return fmt_str, local_ts
            except Exception as e:
                logger.error(f"时区转换失败: {tz_name}, 错误: {e}")
                return None, None

        results = [convert_single_row(ts, tz) for ts, tz in zip(raw_col, df[tz_col])]
        df[out_col_name] = [r[0] for r in results]
        df[col] = [r[1] for r in results]

    return df


def batch_convert_format_date_time(df, time_cols, output_cols):
    """
    将 Unix 时间戳列批量转换为标准时间字符串格式（不带时区转换逻辑）
    """
    for i, col in enumerate(time_cols):
        if col not in df.columns:
            continue

        out_col_name = output_cols[i]
        raw_col = df[col].copy()

        def convert_single_row(ts):
            if pd.isna(ts):
                return None
            try:
                ts = float(ts)
                if ts > 1e11:
                    ts = ts / 1000.0

                from datetime import datetime as _dt, timezone as _tz
                utc_dt = _dt.fromtimestamp(ts, tz=_tz.utc)

                return utc_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.error(f"时间戳转换失败: {ts}, 错误: {e}")
                return None

        # 批量转换
        df[out_col_name] = [convert_single_row(ts) for ts in raw_col]

    return df


def get_phone_brush_user():
    """
    手机刷单的用户
    """
    sql = """
    select DISTINCT sofa_cellphone_number  from bi.`yy_brush_or_not`
    """
    df = my_read_client.get_df_by_sql(sql)

    return df['sofa_cellphone_number'].tolist()

def get_order_brush_user():
    """
    订单刷单的用户
    """
    sql = """
    select DISTINCT sofa_original_order_number from bi.`op_brush_or_not`
    """
    df = my_read_client.get_df_by_sql(sql)
    return df['sofa_original_order_number'].tolist()

def get_shop_info():
    sql =  """
    select lazada_type, qianyi_shop_name, platform, shopee_shop_id, nation from bi.yy_public_join
    where enabled = 1 
    """
    df = my_read_client.get_df_by_sql(sql)

    shop_category_map = df.set_index('qianyi_shop_name').to_dict()['lazada_type']
    shop_platform_map = df.set_index('qianyi_shop_name').to_dict()['platform']
    shop_id_map = df.set_index('qianyi_shop_name').to_dict()['shopee_shop_id']
    shop_nation_map = df.set_index('qianyi_shop_name').to_dict()['nation']
    shop_id_name = df.set_index('shopee_shop_id').to_dict()['qianyi_shop_name']

    return shop_category_map, shop_platform_map, shop_id_map, shop_nation_map, shop_id_name


def brush_detection(df, phone_col, order_col, phone_brush_list, order_brush_list):
    """
    刷单检测逻辑
    """
    phone_brush_set = set(phone_brush_list)
    order_brush_set = set(order_brush_list)

    is_phone_brush = df[phone_col].isin(phone_brush_set)
    is_order_brush = df[order_col].isin(order_brush_set)

    is_brush = is_phone_brush | is_order_brush

    df['brush_or_not'] = np.where(is_brush, "是", "否")
    df['brush_or_not_int'] =  df['brush_or_not'].map({'是': 1, '否': 0}).fillna(0).astype(int)

    return df


def standardize_buyer_id(df, platform_col, email_col, order_no_col, output_col, target_platform='Amazon'):
    """
    向量化生成买家ID
    逻辑：如果是目标平台（默认Amazon），优先用邮箱，没邮箱则用订单号。
    修改点：非目标平台的记录保持原样（或保持NaN），不被覆盖为None。
    """
    is_target_platform = df[platform_col] == target_platform
    email_is_empty = df[email_col].isna() | (df[email_col] == '')

    conditions = [
        is_target_platform & email_is_empty,  # 条件1：是目标平台 且 邮箱为空 -> 用订单号
        is_target_platform & ~email_is_empty  # 条件2：是目标平台 且 邮箱不为空 -> 用邮箱
    ]

    choices = [df[order_no_col],  df[email_col]]

    default_value = df[output_col] if output_col in df.columns else None

    df[output_col] = np.select(conditions, choices, default=default_value)

    return df

def get_split_order_from_qy_db_history(times=1, window_days=30):
    """
    找出拆单不入库的订单,历史数据回滚使用
    """
    st_time = time.time()

    if times == 1:
        sql = """
        SELECT DISTINCT o.parent_id
            FROM gerp.ge_order o
            INNER JOIN gerp.ge_order_sku s
                ON o.id = s.order_id
            WHERE  o.customer_id = 134 AND o.update_time >= DATE(NOW())
              AND o.pay_time IS NOT NULL
              AND (o.tags & 16384) != 0
              AND o.is_deleted = 0
        """
        df = qy_client.get_df_by_sql(sql)

        logger.info(f"【实时千易订单同步】获取拆单不入库的订单耗时：{time.time() - st_time:.2f}秒")
        return df['parent_id'].tolist()
    else:
        sql_template = """
            SELECT 
                   o.parent_id
            FROM gerp.ge_order o
            INNER JOIN gerp.ge_order_sku s
                ON o.id = s.order_id
            WHERE o.pay_time_local >= '{start_time}'
              AND o.pay_time_local < '{end_time}'
              AND o.pay_time IS NOT NULL
              AND (o.tags & 16384) != 0
              AND o.is_deleted = 0
        """

        now = datetime.datetime.now()
        sql_list = []

        for i in range(times):
            start = now - datetime.timedelta(days=(i + 1) * window_days)
            end = now - datetime.timedelta(days=i * window_days)

            sql = sql_template.format(
                start_time=start.strftime('%Y-%m-%d 00:00:00'),
                end_time=end.strftime('%Y-%m-%d 00:00:00')
            )
            sql_list.append(sql)

        all_parent_ids = set()

        max_workers = min(times, 4)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_sql = {
                executor.submit(qy_client.get_df_by_sql, sql): sql
                for sql in sql_list
            }

            for future in as_completed(future_to_sql):
                try:
                    df = future.result()
                    if not df.empty:
                        ids = df['parent_id'].tolist()
                        all_parent_ids.update(ids)
                except Exception as e:
                    sql = future_to_sql[future]
                    logger.error(f"查询出错: {e}")
                    logger.error(f"SQL片段: {sql[:100]}...")

        logger.info(f"【实时千易订单同步】获取拆单不入库的订单耗时, 共 {len(all_parent_ids)} 个唯一parent_id, 耗时: {time.time() - st_time:.2f}秒")
        return list(all_parent_ids)


def convert_local_datetime_to_shanghai(local_dt_str, from_tz_name):
    """将店铺本地时间字符串转为 Asia/Shanghai 时区"""
    if pd.isna(local_dt_str) or pd.isna(from_tz_name):
        return None, None
    try:
        from datetime import datetime as _dt
        import pytz as _pytz
        naive_dt = pd.to_datetime(local_dt_str).to_pydatetime()
        if isinstance(naive_dt, _dt) and naive_dt.tzinfo is not None:
            local_dt = naive_dt
        else:
            local_dt = _pytz.timezone(from_tz_name).localize(naive_dt)
        shanghai_dt = local_dt.astimezone(_pytz.timezone('Asia/Shanghai'))
        return shanghai_dt.strftime("%Y-%m-%d %H:%M:%S"), shanghai_dt.strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"本地时间转 Asia/Shanghai 失败: {local_dt_str}, 时区 {from_tz_name}, 错误: {e}")
        return None, None


def fix_woocommerce_gmv(df):
    """
    计算方式
        PH-woocommerce
        1. shipping fee = total_order_amount - actual_payment_amount（同订单 total_order_amount 相同，只取一份）
        2. 若是多个分摊，则是 SKU1 shipping fee=shipping fee*(SKU1_actual_payment_amount /（SKU1_actual_payment_amount+SKU2_actual_payment_amount）)  -> system_tracking_number有多条记录的 ， 根据金额分摊 shipping_fee
        3. 更新后的actual_payment_amount：=  SKU1_actual_payment_amount + SKU1 shipping fee
    """
    try:
        return _fix_woocommerce_gmv_core(df)
    except Exception as e:
        logger.error(f"【WooCommerce GMV】修正失败，跳过继续执行：{e}")
        return df


def _fix_woocommerce_gmv_core(df):
    df_woo_mask = df["platform"].isin(["WooCommerce"])
    df_woo = df[df_woo_mask].copy()

    if df_woo.empty:
        return df

    for col in ["total_order_amount", "actual_payment_amount", "shipping_fee"]:
        df_woo[col] = pd.to_numeric(df_woo[col], errors="coerce").astype(float)

    woo_fee_decimals = 4
    df_woo["sku_pay_amount"] = df_woo["actual_payment_amount"].astype(float)

    woo_log_cols = ["system_tracking_number", "product_code", "total_order_amount", "actual_payment_amount", "shipping_fee"]
    woo_before = df_woo[woo_log_cols].copy()

    def _fmt_woo_amount(val):
        if pd.isna(val):
            return val
        return f"{float(val):.{woo_fee_decimals}f}"

    def _log_multi_sku_orders(records_df, label, with_order_shipping_fee=False):
        order_cnt = records_df.groupby("system_tracking_number").size()
        multi_order_nos = order_cnt[order_cnt > 1].index.tolist()
        if not multi_order_nos:
            logger.info(f"【WooCommerce GMV】{label} 无多SKU订单")
            return
        logger.info(f"【WooCommerce GMV】{label} 多SKU订单共 {len(multi_order_nos)} 单")
        for order_no in multi_order_nos[:20]:
            order_rows = records_df[records_df["system_tracking_number"] == order_no]
            sku_detail = " | ".join(
                "{product_code}: actual_payment_amount={actual_payment_amount}, shipping_fee={shipping_fee}".format(
                    product_code=r["product_code"],
                    actual_payment_amount=_fmt_woo_amount(r["actual_payment_amount"]),
                    shipping_fee=_fmt_woo_amount(r["shipping_fee"]),
                )
                for r in order_rows.to_dict("records")
            )
            msg = (
                f"【WooCommerce GMV】{label} 订单={order_no}, total_order_amount={_fmt_woo_amount(order_rows['total_order_amount'].iloc[0])}, "
                f"actual_payment_amount合计={_fmt_woo_amount(order_rows['actual_payment_amount'].fillna(0).sum())}"
            )
            if with_order_shipping_fee:
                msg += f", order_shipping_fee={_fmt_woo_amount(order_rows['order_shipping_fee'].iloc[0])}"
            logger.info(msg)
            logger.info(f"  {sku_detail}")
        if len(multi_order_nos) > 20:
            logger.info(f"【WooCommerce GMV】{label} 其余 {len(multi_order_nos) - 20} 单省略")

    _log_multi_sku_orders(woo_before, "计算前")

    order_totals = df_woo.groupby("system_tracking_number").agg(
        total_actual_payment=("sku_pay_amount", lambda s: s.fillna(0).sum()),
        order_total=("total_order_amount", "first"),
    ).reset_index()
    order_totals["order_total"] = order_totals["order_total"].astype(float)
    order_totals["total_actual_payment"] = order_totals["total_actual_payment"].astype(float)

    order_totals["order_shipping_fee"] = (
        order_totals["order_total"].fillna(0) - order_totals["total_actual_payment"]
    ).round(woo_fee_decimals)

    df_woo = df_woo.merge(
        order_totals[["system_tracking_number", "total_actual_payment", "order_shipping_fee"]],
        on="system_tracking_number",
        how="left",
    )

    df_woo["sku_shipping_fee"] = 0.0
    for _, group in df_woo.groupby("system_tracking_number"):
        order_fee = round(float(group["order_shipping_fee"].iloc[0]), woo_fee_decimals)
        total_pay = float(group["sku_pay_amount"].fillna(0).sum())
        idx_list = group.index.tolist()
        if not idx_list:
            continue
        if order_fee == 0 or total_pay == 0:
            continue
        allocated_sum = 0.0
        for i, idx in enumerate(idx_list):
            if i == len(idx_list) - 1:
                sku_fee = round(order_fee - allocated_sum, woo_fee_decimals)
            else:
                pay = float(group.at[idx, "sku_pay_amount"] or 0)
                sku_fee = round(order_fee * pay / total_pay, woo_fee_decimals)
                allocated_sum = round(allocated_sum + sku_fee, woo_fee_decimals)
            df_woo.at[idx, "sku_shipping_fee"] = float(sku_fee)

    df_woo["shipping_fee"] = df_woo["sku_shipping_fee"].astype(float).round(woo_fee_decimals)
    df_woo["actual_payment_amount"] = (df_woo["sku_pay_amount"] + df_woo["sku_shipping_fee"]).astype(float).round(woo_fee_decimals)

    woo_after = df_woo[woo_log_cols + ["order_shipping_fee"]].copy()
    _log_multi_sku_orders(woo_after, "计算后", with_order_shipping_fee=True)

    df_woo.drop(columns=["sku_pay_amount", "total_actual_payment", "order_shipping_fee", "sku_shipping_fee"], inplace=True)

    if "rowid" not in df_woo.columns:
        logger.warning("【WooCommerce GMV】缺少 rowid，回退 index 写回")
        df.loc[df_woo.index, "shipping_fee"] = df_woo["shipping_fee"]
        df.loc[df_woo.index, "actual_payment_amount"] = df_woo["actual_payment_amount"]
    else:
        woo_update = df_woo.set_index("rowid")[["shipping_fee", "actual_payment_amount"]]
        matched = df["rowid"].isin(woo_update.index)
        df.loc[matched, "shipping_fee"] = df.loc[matched, "rowid"].map(woo_update["shipping_fee"])
        df.loc[matched, "actual_payment_amount"] = df.loc[matched, "rowid"].map(woo_update["actual_payment_amount"])

    return df


country_default_map = {
    "TH": "Asia/Bangkok",
    "VN": "Asia/Ho_Chi_Minh",
    "MY": "Asia/Kuala_Lumpur",
    "SG": "Asia/Singapore",
    "PH": "Asia/Manila",
    "ID": "Asia/Jakarta",
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "TW": "Asia/Taipei",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "IT": "Europe/Rome",
    "ES": "Europe/Madrid",
    "GB": "Europe/London",
    "CA": "America/Toronto",
    "US": "America/New_York",
    "EU": "Europe/London",
    "CL": "America/Santiago",
    "BR": "America/Sao_Paulo"
}

def _save_cache(df, cache_file: str):
    """仅保存比对所需的关键字段，减少磁盘占用"""
    cols = ["system_tracking_number", "_time_str", "_update_str"]
    df[cols].to_csv(cache_file, index=False)


def _delete_cache(cache_file: str):
    """删除缓存文件"""
    if os.path.exists(cache_file):
        os.remove(cache_file)
        logger.info(f"【实时千易订单同步】已删除缓存文件: {cache_file}")


def get_changed_records(df, is_delete_cache=0):
    """
    判断是否已经在上一次导入过，不需要再进入
    比较传入的df与上次缓存，返回需要新增或更新的记录
    """
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(os.path.dirname(__file__), f"real_time_erp_order_sync_{today_str}.csv")
    new_cache_df = df[['system_tracking_number', '_time_str', '_update_str']]

    if is_delete_cache:
        _delete_cache(cache_file)

    if not os.path.exists(cache_file):
        logger.info(f"【实时千易订单同步】未找到缓存文件，全量导入。")
        return df, cache_file, new_cache_df

    try:
        cache_df = pd.read_csv(cache_file)
    except Exception as e:
        logger.warning(f"读取缓存文件失败: {e}，全量导入。")
        return df, cache_file, new_cache_df

    if cache_df.empty:
        logger.info(f"【实时千易订单同步】缓存文件为空，全量导入。")
        return df, cache_file, new_cache_df

    cache_df["_time_str"] = cache_df["_time_str"].astype(str)
    cache_df["_update_str"] = cache_df["_update_str"].astype(str)
    cache_keys = set(zip(cache_df["system_tracking_number"], cache_df["_time_str"]))
    current_keys = zip(df["system_tracking_number"], df["_time_str"])
    is_new = ~pd.Series([k in cache_keys for k in current_keys], index=df.index)

    cache_update_map = dict(zip(zip(cache_df["system_tracking_number"], cache_df["_time_str"]), cache_df["_update_str"]))
    cached_update_times = df.apply(lambda row: cache_update_map.get((row["system_tracking_number"], row["_time_str"])), axis=1)
    is_updated = (cached_update_times != df["_update_str"]) & (~is_new)
    result_df = df[is_new | is_updated].reset_index(drop=True)

    new_count = is_new.sum()
    updated_count = is_updated.sum()

    logger.info(f"【实时千易订单同步】处理完成。总计变动: {len(result_df)} (新增: {new_count}, 更新: {updated_count})")

    return result_df, cache_file, new_cache_df


def get_qianyi_tokopedia_order_from_qy_db(is_real_time=True, msg="实时千易订单同步"):
    if is_real_time: gap = 30
    else: gap = 91
    sql = f"""
    select distinct order_id FROM gerp.ge_order_quick_tag 
    where  customer_id=134 and tag='FROM_TOKOPEDIA' and pay_time_local >= current_time - INTERVAL {gap} DAY
    """

    df = qy_client.get_df_by_sql(sql)
    if df is None:
        logger.error(f"【{msg}】获取千易订单数据失败")
        exit(-1)

    tokopedia_order_ids = df['order_id'].unique().tolist()
    logger.info(f"【{msg}】获取到 {len(tokopedia_order_ids)} 条Tokopedia订单")
    return tokopedia_order_ids


def get_real_time_cols_from_qy_db(date_start, end_date, order_number=None):
    start_time = time.time()
    logger.info(f"【实时千易订单同步】开始获取千易订单审单流程")
    if order_number:
        conditon = f""" order_info.order_number = '{order_number}' """
    else:
        conditon = "1=1"

    sql = f"""
        SELECT
            order_info.order_number system_tracking_number,
            MAX(CASE WHEN order_process_log.process_code IN ('Audit_BY_RULE', 'AUDIT_AVAILABLE') THEN order_process_log.update_time END) AS audit_time_qy,
            MAX(CASE WHEN order_process_log.process_code IN ('SEND_WMS_BY_RULE_SUCCESS', 'SEND_WMS_SUCCESS') THEN order_process_log.update_time END) AS send_wms_time,
            MAX(CASE WHEN order_process_log.process_code IN ('TRACK_NUMBER_BY_API') THEN order_process_log.update_time END) AS create_waybill_time,
            MAX(CASE WHEN order_process_log.process_code IN ('WMS_SHIP_SUCCESS', 'WMS_SHIP_MANUAL_SUCCESS') THEN order_process_log.update_time END) AS wms_ship_time,
            MAX(CASE WHEN order_process_log.process_code IN ('SHIP_ONLINE_FEEDBACK_SUCCESS') THEN order_process_log.update_time END) AS send_success_time,
            MAX(CASE WHEN order_process_log.process_code IN ('CLOSE') THEN order_process_log.update_time END) AS order_close_time
        FROM gerp.ge_order order_info 
        LEFT JOIN gerp.ge_business_process order_process_log
            ON order_info.customer_id = order_process_log.customer_id 
            AND order_info.id = order_process_log.business_id 
            AND order_process_log.business_type = 'ORDER'
        WHERE 
            order_info.update_time >= '{date_start}' and {conditon}
        GROUP BY 
            order_info.order_number;
    """
    df = qy_client.get_df_by_sql(sql)
    logger.info(f"【{msg}】获取千易订单审单流程耗时：{time.time() - start_time:.2f}秒")
    return df


def get_real_time_order_from_qy_db(start_date=None, end_date=None, not_ids=None, msg="实时千易订单同步", delete_cache=0, order_number=None, update_date=None):
    """
    千易订单数据数据
    """
    if not not_ids: not_ids = []
    is_real_time = True
    sql_time = _read_sql_time()
    if is_real_time and not start_date and not end_date:
        logger.info(f"【{msg}】当前sql时间: {sql_time}")

    conditons = f"""
                    AND order_info.update_time>='{sql_time}'
                    AND (product.`type` = 'SINGLE' OR product.`type` IS NULL) AND order_sku.is_deleted = 0
                """
    # -- and shop.name in ("TH_Shopline_Simplus","PH_WooCommerce_Simplus","MY_WooCommerce_Simplus","TH_WooCommerce_Simplus")

    if order_number:
        conditons = f"""
                        AND order_info.order_number = '{order_number}'
                    """

    date_start = sql_time

    if update_date:
        logger.info(f"【{msg}】指定更新时间: {update_date}")
        conditons = f"""
                        AND order_info.update_time>='{update_date}'
                        AND (product.`type` = 'SINGLE' OR product.`type` IS NULL) AND order_sku.is_deleted = 0
                    """

    if start_date and end_date:
        conditons = f"""
                    AND order_info.customer_id = 134
                    AND order_info.create_time>= '{start_date}' AND order_info.create_time < '{end_date}' 
                    AND (product.`type` = 'SINGLE' OR product.`type` IS NULL) AND order_sku.is_deleted = 0
                 """
        is_real_time = False
        date_start = start_date

    # 组合品需要排除
    sql = f"""
    select
        concat(order_info.order_number,order_sku.id) rowid,
        order_info.id,
        order_info.order_number system_tracking_number,
        order_info.status order_status,
        order_info.online_status ,
        order_info.shipping_time delivery_time_utc,
        Date(order_info.shipping_time) delivery_time_utc_update,
        warehouse.name warehouse,
        -- 特殊处理 TEMU_AUTO
        CASE WHEN order_info.carrier IN ("TEMU_AUTO") and order_info.carrier_name is not null THEN order_info.carrier_name
        else order_info.carrier end as carrier,
--         concat(buyer.country,'- ', order_info.logistics_code)  shipping_methods,
        ligistic.name shipping_methods,
        order_info.tracking_number shipment_number,
        order_info.tracking_number waybill_number,
        order_info.online_order_id original_order_number,
        shop.name shop,
        shop.time_zone_id time_zone,  -- 店铺时区
--         order_info.pay_time origin_payment_time,
        order_info.pay_time_local payment_time,
        Date(order_info.pay_time_local) payment_time_update,
        order_info.payment_method ,
        order_info.cod_pay_amount amount_of_payment_received,
        order_info.total_amount total_order_amount,
        -- order_info.freight,
--         order_sku.online_item_id online_sku_id,
        order_sku.online_sku_code online_product_code,
        -- order_sku.online_sku_title online_product_name,  -- 太长了
        order_sku.sku product_code,
        product.title product_title,
        order_sku.pay_amount actual_payment_amount,
        order_sku.shipping_price shipping_fee,
        order_sku.total_tax taxes,
        order_sku.total_discount discount_fee,
        order_sku.currency ,
        order_info.buyer_name buyer_id,
        order_info.buyer_name,
        order_info.email buyer_email,
        order_info.phone buyer_cellphone,
        buyer.address1 buyer_add_one,
        buyer.address2 buyer_add_two,
        buyer.city buyer_city,
        buyer.province buyer_province,
        buyer.country buyer_country,
        buyer.post_code buyer_zip_code,
        order_sku.sku_quantity product_units,
        order_info.seller_remarks remarks,
        '否' whether_to_reissue,
        order_info.sales_record_number reference_no,
        order_info.audit_time review_time,
        -- tags &  xxx  = 0 代表 没有这个 标签，>0 就是有这个标签 不在sql中处理
        order_info.tags,
        -- real_create_time_loacl 平台创建订单时间
        CASE WHEN order_info.real_create_time_local IS NOT NULL then order_info.real_create_time_local else order_info.create_time END platform_create_time,
        order_info.create_time order_created_time,
--         unix_timestamp(order_info.pay_time) paytime_ts,
        unix_timestamp(order_info.shipping_time) delivertime_ts,
--         unix_timestamp(order_info.real_create_time) createtime_ts,
        unix_timestamp(order_info.audit_time) reviewtime_ts,
        unix_timestamp(order_info.create_time) o_createtime_ts,
        order_info.update_time,
        order_info.is_deleted
--         shop.id qy_shop_id
    FROM gerp.ge_order_sku order_sku # 订单SKU
    LEFT JOIN gerp.ge_order order_info  # 订单
        ON order_info.id = order_sku.order_id 
    LEFT JOIN gerp.ge_warehouse warehouse # 仓库
        ON warehouse.id = order_info.warehouse_id
    LEFT JOIN gerp.ge_shop shop  # 店铺
        ON shop.id = order_info.shop_id 
    LEFT JOIN gerp.ge_sku product  # SKU
        ON product.id = order_sku.sku_id
    LEFT JOIN gerp.ge_buyer buyer  # 买家信息
        ON buyer.id = order_info.buyer_id 
    LEFT JOIN gerp.ge_logistics ligistic # 物流方式
        ON order_info.logistics_id = ligistic.id
    WHERE 1 = 1  {conditons}
    """

    at_time = time.time()
    def get_qy_db_data(sql_qy):
        start_time = time.time()
        logger.info(f"【{msg}】开始获取千易订单数据")
        df_q = qy_client.get_df_by_sql(sql_qy)
        logger.info(f"【{msg}】获取千易订单数据耗时：{time.time() - start_time:.2f}秒")
        return df_q

    def fetch_all_data():
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_df = executor.submit(get_qy_db_data, sql)
            future_time = executor.submit(get_real_time_cols_from_qy_db, date_start, order_number)

            df = future_df.result()
            df_time = future_time.result()

        return df, df_time

    if is_real_time:
        df, df_time = fetch_all_data()
        df_time = df_time.drop_duplicates(subset='system_tracking_number', keep='last')
        df = df.merge(df_time, on='system_tracking_number', how='left')
    else:
        df = get_qy_db_data(sql)

    if df is None:
        logger.error(f"【{msg}】获取千易订单数据失败")
        exit(-1)
    if is_real_time: _save_sql_time()

    df = df[~df['id'].isin(not_ids)]
    df = df[df['is_deleted'] == 0]
    df.drop(['is_deleted'], axis=1, inplace=True)
    logger.info(f"【{msg}】获取千易订单数据耗时：{time.time() - at_time:.2f}秒")

    at_time = time.time()
    # tag信息
    df['hasRefund'] = (df['tags'] & 8).astype(bool).astype(int)
    df['itemReturned'] = (df['tags'] & 16).astype(bool).astype(int)
    df['locked'] = (df['tags'] & 64).astype(bool).astype(int)
    df['sendFailed'] = (df['tags'] & 128).astype(bool).astype(int)
    df['onlineShipFeedbackFailed'] = (df['tags'] & 512).astype(bool).astype(int)
    df['outOfStock'] = (df['tags'] & 1024).astype(bool).astype(int)
    df['consolidated'] = (df['tags'] & 8192).astype(bool).astype(int)
    df['split'] = (df['tags'] & 16384).astype(bool).astype(int)
    df['sendWms'] = (df['tags'] & 524288).astype(bool).astype(int)
    df['onlineShipFeedbackAlready'] = (df['tags'] & 131072).astype(bool).astype(int)

    df.drop('tags', axis=1, inplace=True)

    shop_category_map, shop_platform_map, shop_id_map, shop_nation_map, shop_id_name = get_shop_info()
    phone_brush_user = get_phone_brush_user()
    order_brush_user = get_order_brush_user()
    special_country_map = build_country_en()

    # 需要匹配的是 带 * 的 空字符串的  国家不是 不在 countries 中的, 优先店铺国家 countries = country_default_map.keys()
    shop_based_country = df['shop'].map(shop_nation_map)
    df['buyer_country'] = shop_based_country.combine_first(df['buyer_country'])
    if special_country_map:
        df['buyer_country'] = df['buyer_country'].replace(special_country_map)

    df = df.dropna(subset=['buyer_country'])

    # 处理时区 根据 time_zone 获取时区 time_zone 示例  Asia/Ho_Chi_Minh Asia/Bangkok
    df['platform'] = df['shop'].map(shop_platform_map).fillna('')

    # 没有时区的，根据国家取一个默认时区
    no_time_zone_mask = df['time_zone'].isna()
    if no_time_zone_mask.any():
        df.loc[no_time_zone_mask, 'time_zone'] = df.loc[no_time_zone_mask, 'buyer_country'].map(country_default_map)
        still_missing_mask = df['time_zone'].isna()

        if still_missing_mask.any():
            missing_tracking_numbers = df.loc[still_missing_mask, 'system_tracking_number'].unique().tolist()
            logger.warning(f"【{msg}】未找到时区的订单 (共{len(missing_tracking_numbers)}单): {missing_tracking_numbers}")

        # note 如果仍为空，则设置为 "Asia/Shanghai"， hard code 待产品确认
        df.loc[df['time_zone'].isna(), 'time_zone'] = 'Asia/Shanghai'

    df['upload_time'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    df['shop_id'] = df['shop'].map(shop_id_map).fillna('')
    df = df[(df['shop_id'] != '') & (df['shop'].isna() == False)]
    shop_time_zone = df['time_zone'].copy()
    eu_temu_mask = df['shop_id'].isin(["235"])

    # 半托管数据的 time_zone 特殊处理为 Asia/Shanghai（与原先一致）
    temu_semi_mask = df['platform'].eq('Temu半托管')
    df.loc[temu_semi_mask, 'time_zone'] = 'Asia/Shanghai'

    # 注意 这里单独处理是因为 order_created_time 是主键 不参与显示， 所以不能更改这个逻辑
    df = batch_convert_format_date_time_zone(df, ['o_createtime_ts'], 'time_zone', ['order_created_time'])

    non_eu_mask = ~eu_temu_mask
    if non_eu_mask.any():
        non_eu_idx = df.index[non_eu_mask]
        non_eu_temp = batch_convert_format_date_time_zone(
            df.loc[non_eu_idx].copy(),
            ['delivertime_ts', 'reviewtime_ts'],
            'time_zone',
            ['delivery_time_utc', 'review_time'],
        )
        df.loc[non_eu_idx, 'delivery_time_utc'] = non_eu_temp['delivery_time_utc']
        df.loc[non_eu_idx, 'review_time'] = non_eu_temp['review_time']

    # EU Temu：delivery_time_utc / review_time 保持千易 SQL 原值（shipping_time / audit_time）

    # EU Temu：payment_time / platform_create_time 转 Asia/Shanghai
    eu_temu_time_cols = ['payment_time', 'platform_create_time']
    if eu_temu_mask.any():
        for idx in df.index[eu_temu_mask]:
            src_tz = shop_time_zone.loc[idx]
            for col in eu_temu_time_cols:
                dst_time, dst_date = convert_local_datetime_to_shanghai(df.at[idx, col], src_tz)
                if dst_time is not None:
                    df.at[idx, col] = dst_time
                if col == 'payment_time' and dst_date is not None:
                    df.at[idx, 'payment_time_update'] = dst_date

    df['delivery_time_utc_update'] = df['delivery_time_utc'].str[:10]
    df.drop(['time_zone', 'reviewtime_ts', 'o_createtime_ts', 'delivertime_ts'], axis=1, inplace=True)

    if is_real_time:
        # 对比数据， 查看是否不需要插入
        df['_time_str'] = df['order_created_time'].astype(str)
        df['_update_str'] = df['upload_time'].astype(str)
        df, cache_file, df_cache = get_changed_records(df, is_delete_cache=delete_cache)
        df.drop(["_time_str", "_update_str"], axis=1, inplace=True)

    # 根据 id 获取 是否 是 tokopedia的订单 shop_id + _Tokopedia
    tokopedia_order_ids = get_qianyi_tokopedia_order_from_qy_db(is_real_time=is_real_time, msg=msg)
    tokopedia_mask = df['id'].isin(tokopedia_order_ids)
    df.loc[tokopedia_mask, 'shop_id'] = df.loc[tokopedia_mask, 'shop_id'] + '_Tokopedia'
    df.loc[tokopedia_mask, 'shop'] = df.loc[tokopedia_mask, 'shop_id'].map(shop_id_name).fillna(df.loc[tokopedia_mask, 'shop'])
    df.drop('id', axis=1, inplace=True)
    df.loc[tokopedia_mask, 'platform'] = 'Tokopedia'

    df['erp_type'] = df['shop'].map(shop_category_map).fillna('有成')
    df.drop(["update_time"], axis=1, inplace=True)

    # 是否刷单 brush_or_not brush_or_not_int 逻辑
    df = brush_detection(df,'buyer_cellphone','original_order_number',phone_brush_user,order_brush_user)

    # note Tokopedia平台的商品费需要均摊 均摊逻辑是否需要？
    # Amazon的订单，需要独立处理 buyer_id
    df = standardize_buyer_id(df, platform_col='platform', email_col='buyer_email', order_no_col='original_order_number', output_col='buyer_id',target_platform='Amazon')
    if df.isnull().values.any():
        df = df.where(pd.notnull(df), None)

    # remarks 字段超长, 需要截取
    mask_long = df['remarks'].notna() & (df['remarks'].str.len() > 255)
    if mask_long.any():
        long_orders = df.loc[mask_long, 'system_tracking_number'].tolist()
        logger.warning(f"【{msg}】发现 {len(long_orders)} 条备注超长订单: {long_orders}, 执行自动截断")
        df.loc[mask_long, 'remarks'] = df.loc[mask_long, 'remarks'].str[:255]

    mask_long = df['carrier'].notna() & (df['carrier'].str.len() > 50)
    if mask_long.any():
        long_orders = df.loc[mask_long, 'system_tracking_number'].tolist()
        logger.warning(f"【{msg}】发现 {len(long_orders)} 条承运商超长订单: {long_orders}, 执行自动截断")
        df.loc[mask_long, 'carrier'] = df.loc[mask_long, 'carrier'].str[:50]

    # 插入数据库
    logger.info(f"【{msg}】清洗数据耗时：{time.time() - at_time:.2f}秒")
    at_time = time.time()

    # 所有国家平台的组合
    nation_platforms = df[['platform', 'buyer_country']].rename(columns={'buyer_country': 'nation'}).drop_duplicates().to_dict('records')

    # 私域WooCommerce GMV & 商品收入均计算错误处理
    df = fix_woocommerce_gmv(df)

    df = df.replace({np.nan: None})

    success = my_client.insert_many_by_executemany(table_name='bi.yy_erp_qianyiapi_history', tmp_df=df, with_id=False)
    logger.info(f"【{msg}】插入数据库耗时：{time.time() - at_time:.2f}秒")

    if is_real_time:
        if success:
            _save_cache(df_cache, cache_file)
            logger.info(f"【{msg}】更新缓存")
        else:
            logger.info(f"【{msg}】插入数据库失败，不更新缓存")

    return nation_platforms


def platform_worker(args):
    platform, nation, days, is_log = args
    pid = os.getpid()
    logger.info(f"[PID {pid}] 开始处理 , 国家:{nation}, 平台:{platform}")
    s = time.time()
    update_order_info_from_qy_db_real_time(days=days, platforms=[platform], nation=nation, is_log=is_log, max_try=2)
    logger.info(f"[PID {pid}] 处理完成 , 国家:{nation}, 平台:{platform},耗时: {time.time() - s:.2f}秒")


if __name__ == "__main__":
    """
    qianyi订单实时同步
    1.当天实时刷新， 只新增或更新需要的记录， 减少耗时, 加入缓存
    2.历史数据回滚， 每隔5天回滚一天 （测试5天为比较好的， 长了sql执行很慢）， 回滚90天
    后续需要执行的命令：订单状态更新、订单物流信息更新
    """
    usage="Usage: %prog [options] "
    parser=optparse.OptionParser(usage,version="%prog 1.0")
    parser.add_option("-r","--real_time", dest="real_time", type="int", default=1, help="是否当天实时刷新")
    parser.add_option("-c","--delete_cache", dest="delete_cache", type="int", default=0, help="是否删除缓存")
    parser.add_option("-s", "--delete_sync", dest="delete_sync", type="int", default=0, help="是否删除上次运行时间")
    parser.add_option("-q", "--delete_sql", dest="delete_sql", type="int", default=0, help="是否删除上次sql时间")
    parser.add_option("-o", "--order_number", dest="order_number", type="str", default=None, help="指定订单号")
    parser.add_option("-u", "--update_date", dest="update_date", type="str", default=None, help="根据指定订单更新时间跟新")
    parser.add_option("-d","--days", dest="days", type="int", default=60, help="需要向前刷新的天数")
    parser.add_option("-g","--gap_days", dest="gap_days", type="int", default=5, help="间隔天数")
    parser.add_option("-l","--log", dest="log", type="int", default=0, help="是否打印日志")
    options, args=parser.parse_args()

    # 当天执行 与 d 天回滚
    t_time = time.time()
    is_log = options.log

    if options.real_time:
        msg = "实时千易订单同步"
        split_ids = get_split_order_from_qy_db_history(times=1)
        if options.delete_sync:_delete_sync_time()
        if options.delete_sql:_delete_sql_time()
        # 存储一个上次运行的时间
        sync_time = _read_sync_time()
        if sync_time:
            logger.info(f"【{msg}】上次运行时间: {sync_time}, 还未运行完毕")
            exit(-1)
        _save_sync_time()
        nation_plats = get_real_time_order_from_qy_db(not_ids=split_ids, msg=msg, delete_cache=options.delete_cache)
        _delete_sync_time()
        logger.info(f"【{msg}】总耗时：{time.time() - t_time:.2f}秒")
    elif options.update_date:
        msg = f"更新指定订单时间"
        today = datetime.datetime.today()
        update_date_obj = datetime.datetime.strptime(options.update_date, "%Y-%m-%d")
        window_days = (today - update_date_obj).days + 3
        split_ids = get_split_order_from_qy_db_history(times=4, window_days=window_days)

        nation_plats = get_real_time_order_from_qy_db(not_ids=split_ids, msg=msg, delete_cache=options.delete_cache, update_date=options.update_date)
        logger.info(f"【{msg}】总耗时：{time.time() - t_time:.2f}秒")
    else:
        msg = f"历史千易订单同步（{options.days}天回滚）"
        split_ids = get_split_order_from_qy_db_history(times=4)

        gap_days = options.gap_days
        total_days = options.days
        end_date_str = time.strftime("%Y-%m-%d", time.localtime())
        end_date_obj = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")

        start_date_obj = end_date_obj - datetime.timedelta(days=total_days)

        logger.info(f"【{msg}】任务启动：从 {end_date_str} 向前回滚 {total_days} 天，分段间隔 {gap_days} 天")

        current_end = end_date_obj
        while current_end > start_date_obj:
            current_start = current_end - datetime.timedelta(days=gap_days)

            if current_start < start_date_obj: current_start = start_date_obj

            if current_start >= current_end: break

            start_str = current_start.strftime("%Y-%m-%d")
            end_str = current_end.strftime("%Y-%m-%d")
            date_msg = msg + str(start_str) + "到" + str(end_str)
            s_time = time.time()
            nation_plats = get_real_time_order_from_qy_db(start_date=start_str, end_date=end_str, not_ids=split_ids, msg=date_msg)
            current_end = current_start

    platform_order = {
        'Shopee': 1, 'Lazada': 2, 'TikTok': 3, 'Tokopedia': 4,
        "Temu半托管": 5, 'TikTok托管': 6, 'Shopline': 7, 'WooCommerce': 8, 'Temu': 9,
        'Amazon': 10, 'AliExpress': 11, 'Others': 12, 'Thisshop': 13, 'Qoo10': 14,
        'Mercado': 15, 'Shopify': 16,
    }

    # 排除 nation为 TH 并且平台 为Lazada的
    def spread_by_nation_and_platform(args):
        """
        按 (nation, platform) 两个维度交错排列
        相同国家 或 相同平台 的任务尽量不相邻
        """
        from collections import defaultdict

        # 按 nation 分组
        nation_buckets = defaultdict(list)
        for arg in args:
            nation_buckets[arg[1]].append(arg)  # arg[1]=nation

        # 每个 nation 内部按 platform 打散
        for nation in nation_buckets:
            nation_buckets[nation].sort(key=lambda x: x[0])  # arg[0]=platform

        # 交错合并：每轮从每个 nation 桶各取一个，nation 桶按剩余数量降序
        result = []
        while any(nation_buckets.values()):
            sorted_buckets = sorted(nation_buckets.values(), key=len, reverse=True)
            for bucket in sorted_buckets:
                if bucket:
                    result.append(bucket.pop(0))
            nation_buckets = {k: v for k, v in nation_buckets.items() if v}

        return result

    EXCLUSIVE_PLATFORMS = {'TikTok', 'Tokopedia'}  # 这些平台不能同时跑

    if options.real_time:
        st_time = time.time()
        nation_plats = [
            item for item in nation_plats
            if not (item['nation'] == 'TH' and item['platform'] == 'Lazada')
        ]

        if nation_plats:
            exclusive_args = [
                (row['platform'], row['nation'], 4, is_log)
                for row in nation_plats
                if row['platform'] in EXCLUSIVE_PLATFORMS
            ]
            normal_args = [
                (row['platform'], row['nation'], 4, is_log)
                for row in nation_plats
                if row['platform'] not in EXCLUSIVE_PLATFORMS
            ]

            # 普通平台：交错排列后统一一个进程池，让调度自然分散
            if normal_args:
                spread_args = spread_by_nation_and_platform(normal_args)
                logger.info(f"【任务分配】普通平台任务顺序: {[(a[0], a[1]) for a in spread_args]}")
                with Pool(processes=4) as pool:
                    pool.map(platform_worker, spread_args)

            # 互斥平台：同样交错后串行，每次只跑1个
            if exclusive_args:
                spread_exclusive = spread_by_nation_and_platform(exclusive_args)
                logger.info(f"【任务分配】互斥平台任务顺序: {[(a[0], a[1]) for a in spread_exclusive]}")
                for arg in spread_exclusive:
                    with Pool(processes=1) as pool:
                        pool.map(platform_worker, [arg])

        th_platforms = [
            item for item in nation_plats
            if item['nation'] == 'TH' and item['platform'] == 'Lazada'
        ]
        if th_platforms:
            update_order_info_from_qy_db_real_time(days=3, platforms=['Lazada'], nation="TH", is_flash=True, is_log=is_log)

        logger.info(f"【历史千易订单同步】订单状态更新完成, 耗时: {time.time() - st_time:.2f}秒")