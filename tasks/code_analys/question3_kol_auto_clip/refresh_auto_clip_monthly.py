# -*- coding: utf-8 -*-
"""
# @Time    : 2026/8/7
# @Author  : Zhu Yaming
# @File    : refresh_auto_clip_monthly.py
# @Description : 按月度刷新历史 Auto_Clip 标签（data_tiktok_video_meta.wb_kol_tag bit 64），完全校正，仅处理官方/营销达人视频
"""
import os, sys, time
import argparse
sys.path.append(os.getcwd().split('apps')[0])
import datetime
from dateutil.relativedelta import relativedelta
from loguru import logger

from conf.settings import settings
from apps.pyscript.helpers.db_helper import YYDB
from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper

read_client = DfToMySqlHelper(host=settings.READ_ONLY_HOST, db="bi", user=settings.USER, password=settings.PASSWORD, port=settings.PORT)


class RefreshAutoClipMonthly(object):

    def __init__(self):
        self.rdbconn, self.rcursor = YYDB.new_db_conn(host=settings.READ_ONLY_HOST)
        self.dbconn, self.cursor = YYDB.new_db_conn()

    def _get_kol_creator_ids(self):
        """获取官方/营销达人 account_id 列表（kol.account_type in (2,3)）"""
        stmt = """
            SELECT DISTINCT plat.account_id
            FROM bi.data_sys_tiktok_obsess_kol kol
            LEFT JOIN bi.data_sys_tiktok_obsess_kol_platform plat ON kol.kol_id = plat.kol_id
            WHERE plat.account_id IS NOT NULL AND kol.account_type IN (2, 3)
        """
        self.rcursor.execute(stmt)
        result = self.rcursor.fetchall()
        return [row['account_id'] for row in result] if result else []

    def _iter_months(self, start_month, end_month):
        """按月遍历 YYYY-MM，返回每月 1 号"""
        cur = datetime.datetime.strptime(start_month, '%Y-%m').date()
        end = datetime.datetime.strptime(end_month, '%Y-%m').date()
        while cur <= end:
            yield cur
            cur = cur + relativedelta(months=1)

    def _batch_update_auto_clip(self, video_ids, set_bit):
        """分批更新 meta 表 Auto_Clip 标签（bit 64），set_bit=True 打标，False 清除"""
        bs = 500
        for i in range(0, len(video_ids), bs):
            batch = video_ids[i:i + bs]
            placeholders = ','.join(['%s'] * len(batch))
            if set_bit:
                stmt = f"""
                    UPDATE bi.data_tiktok_video_meta
                    SET wb_kol_tag = wb_kol_tag | 64
                    WHERE video_id IN ({placeholders})
                """
            else:
                stmt = f"""
                    UPDATE bi.data_tiktok_video_meta
                    SET wb_kol_tag = wb_kol_tag & ~64
                    WHERE video_id IN ({placeholders})
                """
            self.cursor.execute(stmt, tuple(batch))
            self.dbconn.commit()

    def _refresh_month(self, creator_ids, month_start, month_end):
        month_str = month_start.strftime('%Y-%m')
        # Step 1: 查该月官方/营销达人视频，筛出应打 Auto_Clip 的 video_id（keep_ids）与该月全部视频（month_video_ids）
        keep_ids = set()
        month_video_ids = set()
        bs = 500
        for i in range(0, len(creator_ids), bs):
            batch_creator = creator_ids[i:i + bs]
            placeholders = ','.join(['%s'] * len(batch_creator))
            select_sql = f"""
                SELECT video_id, creator_type, product_list, video_name
                FROM bi.data_tiktok_video
                WHERE start_time >= %s AND start_time < %s AND creator_id IN ({placeholders})
            """
            params = [month_start.strftime('%Y-%m-%d'), month_end.strftime('%Y-%m-%d')] + batch_creator
            vdo_df = read_client.get_df_by_sql_params(select_sql, params)
            if vdo_df is None or vdo_df.empty:
                continue
            vdo_df = vdo_df[~vdo_df['video_id'].isin([0, '0'])]
            if vdo_df.empty:
                continue
            month_video_ids.update(vdo_df['video_id'].unique().tolist())
            vdo_df['video_name'] = vdo_df['video_name'].fillna('')
            keep_series = vdo_df.groupby('video_id').apply(lambda x: (
                x['creator_type'].isin(['Official', 'Marketing']).all() and
                x['video_name'].str.len().le(100).all() and  # 视频标题字符长度≤100
                (~x['video_name'].str.contains('#')).all() and  # 视频标题无 "#"
                x['product_list'].isin([[], '[]']).all()  # 商品信息为空（不挂车）
            ))
            keep_ids.update(keep_series[keep_series].index.tolist())

        if not month_video_ids:
            logger.info(f"{month_str}: 无达人视频")
            return

        # Step 2: 查该月视频中 meta 已打 Auto_Clip 标签（bit 64）的 video_id
        tagged_ids = set()
        month_video_list = list(month_video_ids)
        for i in range(0, len(month_video_list), bs):
            batch = month_video_list[i:i + bs]
            placeholders = ','.join(['%s'] * len(batch))
            tag_sql = f"""
                SELECT video_id FROM bi.data_tiktok_video_meta
                WHERE video_id IN ({placeholders}) AND (wb_kol_tag & 64) = 64
            """
            tag_df = read_client.get_df_by_sql_params(tag_sql, batch)
            if tag_df is not None and not tag_df.empty:
                tagged_ids.update(tag_df['video_id'].unique().tolist())

        # Step 3: 完全校正：补打满足条件的，清除不再满足的
        add_ids = list(keep_ids - tagged_ids)
        remove_ids = list(tagged_ids - keep_ids)
        if add_ids:
            self._batch_update_auto_clip(add_ids, set_bit=True)
            if len(add_ids) > 50:
                logger.info(f"{month_str}: 补打 {len(add_ids)} 个 video_id, video_ids: {add_ids[:50]}")
            else:
                logger.info(f"{month_str}: 补打 {len(add_ids)} 个 video_id, video_ids: {add_ids}")
        if remove_ids:
            self._batch_update_auto_clip(remove_ids, set_bit=False)
        logger.info(
            f"{month_str}: 视频{len(month_video_ids)} 满足{len(keep_ids)} 补打{len(add_ids)} 清除{len(remove_ids)}"
        )

    def process(self, start_month, end_month):
        creator_ids = self._get_kol_creator_ids()
        if not creator_ids:
            logger.error("未获取到官方/营销达人")
            return False
        logger.info(f"官方/营销达人数量：{len(creator_ids)}")
        for month_start in self._iter_months(start_month, end_month):
            month_end = month_start + relativedelta(months=1)
            try:
                self._refresh_month(creator_ids, month_start, month_end)
            except Exception as e:
                logger.error(f"刷新 {month_start.strftime('%Y-%m')} 失败：{e}")
        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="按月度刷新历史 Auto_Clip 标签")
    parser.add_argument("--start_month", type=str, help="开始月份 (YYYY-MM)，默认最近12个月")
    parser.add_argument("--end_month", type=str, help="结束月份 (YYYY-MM)，默认当前月")
    args = parser.parse_args()

    today = datetime.datetime.now()
    end_month = args.end_month if args.end_month else today.strftime('%Y-%m')
    start_month = args.start_month if args.start_month else (today - datetime.timedelta(days=365)).strftime('%Y-%m')

    start_time = time.time()
    refresher = RefreshAutoClipMonthly()
    ret = refresher.process(start_month, end_month)
    logger.info(f"总耗时：{time.time() - start_time}秒")
    exit(0 if ret else -1)
