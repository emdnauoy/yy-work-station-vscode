
import os, sys, time, copy
import argparse
sys.path.append(os.getcwd().split('apps')[0])
import datetime
import numpy as np
import ast
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from loguru import logger
import traceback
import hashlib
import pandas as pd
from sqlalchemy.orm import sessionmaker
import sqlalchemy.dialects.mysql as mysql
from sqlalchemy.inspection import inspect
from urllib.parse import quote_plus as urlquote

from conf.settings import settings
from apps.pyscript.helpers.db_helper import YYDB
from apps.common.service.customer_request_conf import key_value_columns,com_rename_dict,get_work_order_id,get_online_product_code
from apps.common.service.tiktik_obsess_conf import *
from apps.common.service.bitmap_tag_system import WbKolTag
from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper

# USER = 'yaoyao_auto_dev'
# PASSWORD = 'qwedcvfrt1234@'
# HOST = settings.EXTERNAL_READONLY_HOST
# WHOST = settings.EXTERNAL_HOST
read_client = DfToMySqlHelper(host=settings.READ_ONLY_HOST, db="bi", user=settings.USER, password=settings.PASSWORD, port=settings.PORT)
write_client = DfToMySqlHelper(host=settings.HOST, db="bi", user=settings.USER, password=settings.PASSWORD, port=settings.PORT)
# read_client = DfToMySqlHelper(host=HOST, db="bi", user=USER, password=PASSWORD, port=settings.PORT)


class UpdateTikTokVideoKolData(object):

    def __init__(self):
        self.rdbconn, self.rcursor = YYDB.new_db_conn(host=settings.READ_ONLY_HOST)
        self.dbconn, self.cursor = YYDB.new_db_conn()
        # self.rdbconn, self.rcursor = YYDB.new_db_conn(host=HOST, user=USER, password=PASSWORD, is_pringboard=True)
        # self.dbconn, self.cursor = YYDB.new_db_conn(host=WHOST, user=USER, password=PASSWORD, is_pringboard=True)
        self.columns = ['shop_id','video_id','budget','budget_usd','currency','kol_type','kol_level','wb_kol','wb_kol_tag']


    def _get_type_config(self,need_cols= ['kol_grade','kol_type']):
        stmt =  "select filter_value from internal_app.data_sys_table_title_desc_mapping where menu_id=69"
        self.rcursor.execute(stmt)
        filter_value_list = self.rcursor.fetchall()
        filter_value = ast.literal_eval(filter_value_list[0]['filter_value'])

        need_conf_dict = {ncol:{} for ncol in need_cols}
        for item in filter_value:
            if item['key'] in need_cols:
                for data_dict in item['search_list']:
                    need_conf_dict[item['key']].update({data_dict['value']:data_dict['label']})
        return need_conf_dict

    def _get_tiktok_obsess_data(self):
        stmt = """SELECT
                      TP.plan_id,
                      TP.shop_id,
                      TP.tiktok_video_id AS video_id,
                      TP.cash budget,
                      TP.currency,
                      TP.cash_usd budget_usd,
                      TK.kol_type,
                      TM.kol_grade AS kol_level
                  FROM
                          (select * from bi.data_sys_tiktok_obsess_plan where tiktok_video_id is not NULL and channel='TikTok' and status in (7)) TP
                              LEFT JOIN bi.data_sys_tiktok_obsess_kol TK ON TP.kol_id = TK.kol_id
                              LEFT JOIN bi.data_sys_tiktok_obsess_kol_platform TM on TP.kol_id = TM.kol_id and TP.channel=TM.platform"""
        self.rcursor.execute(stmt)
        result = self.rcursor.fetchall()
        video_dicts = {}
        for row in result:
            key = (row['shop_id'],row['video_id'])
            if key not in video_dicts:
                video_dicts[key] = {rk:rv for rk,rv in row.items() if rk in self.columns}
            else:
                video_dicts[key]['budget_usd'] += row['budget_usd']
                video_dicts[key]['budget'] += row['budget']

        # 计算ROI的坑位费，等于budget_usd
        for video_id,video_dict in video_dicts.items():
            video_dict['roi_pit_location_fee'] = video_dict['budget_usd']
            video_dict['wb_kol'] = 'Yes'

        meta_video_dicts = {}
        testa = {}
        if len(video_dicts)>0:
            stmt = "select video_id,shop_id,product_list,video_publish_time,wb_kol_tag from bi.data_tiktok_video_meta where video_id in ({})".format(','.join([f"'{video_id[1]}'" for video_id in video_dicts.keys()]))
            self.rcursor.execute(stmt)
            meta_video_ids = self.rcursor.fetchall()
            meta_video_dicts = {(meta_video['shop_id'],meta_video['video_id']):meta_video for meta_video in meta_video_ids}
            testa = {meta_video['video_id']:meta_video for meta_video in meta_video_ids}

        # 去掉不存在meta表的数据
        end_video_dicts = {}
        col_type_dicts = self._get_type_config()
        for video_key,video_dict in video_dicts.items():
            if video_key in meta_video_dicts:
                video_dict['kol_type'] = col_type_dicts['kol_type'].get(video_dict['kol_type'],'')
                video_dict['kol_level'] = col_type_dicts['kol_grade'].get(video_dict['kol_level'],'')

                # todo WB逻辑是BD的逻辑，WB需要修改逻辑
                video_dict['wb_kol_tag'] = WbKolTag.add_tag(bitmap=meta_video_dicts[video_key].pop('wb_kol_tag'),tag_id=WbKolTag.get_by_name('BD').value)

                video_dict.update(meta_video_dicts[video_key])
                end_video_dicts[video_key] = video_dict
            elif video_key not in meta_video_dicts and video_key[1] in testa:
                print(f'{video_key} video_meta is not exist')

        return end_video_dicts

    def _get_creator_ids(self):
        stmt = """
               SELECT DISTINCT TM.account_id
               FROM bi.data_sys_tiktok_obsess_kol TK
                        LEFT JOIN bi.data_sys_tiktok_obsess_kol_platform TM ON TK.kol_id = TM.kol_id
               WHERE TK.status = 4 AND TM.account_id IS NOT NULL \
               """
        self.rcursor.execute(stmt)
        result = self.rcursor.fetchall()

        return [row['account_id'] for row in result] if result else []

    def _get_canceled_creator_ids(self):
        stmt = """
               SELECT DISTINCT TM.account_id
               FROM bi.data_sys_tiktok_obsess_kol TK
                        LEFT JOIN bi.data_sys_tiktok_obsess_kol_platform TM ON TK.kol_id = TM.kol_id
               WHERE TK.status = 5 AND TM.account_id IS NOT NULL \
               """
        self.rcursor.execute(stmt)
        result = self.rcursor.fetchall()

        return [row['account_id'] for row in result] if result else []


    def _cancel_video_meta_ai_tag(self):
        """
        取消所有的AI标签
        """
        cancel_sql = """
                     UPDATE bi.data_tiktok_video_meta
                     SET wb_kol_tag = wb_kol_tag & ~8
                     WHERE wb_kol_tag >= 8; \
                     """
        self.cursor.execute(cancel_sql)
        affect_row = self.cursor.rowcount
        self.dbconn.commit()
        logger.info(f"取消所有data_tiktok_video_meta AI标签名， 成功{affect_row}")
        # cancel_sql = """
        #     UPDATE bi.data_tiktok_video_obsess_details
        #     SET wb_kol_tag = wb_kol_tag & ~8
        #     WHERE wb_kol_tag >= 8;
        # """
        # self.cursor.execute(cancel_sql)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        # logger.info(f"取消所有data_tiktok_video_obsess_details AI标签名， 成功{affect_row}")
        # cancel_sql = """
        #     UPDATE bi.data_tiktok_video_obsess_details_month
        #     SET wb_kol_tag = wb_kol_tag & ~8
        #     WHERE wb_kol_tag >= 8;
        # """
        # self.cursor.execute(cancel_sql)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        # logger.info(f"取消所有data_tiktok_video_obsess_details_month AI标签名， 成功{affect_row}")
        #
        # cancel_sql = """
        #     UPDATE bi.data_tiktok_video_obsess_overview_month
        #     SET wb_kol_tag = wb_kol_tag & ~8
        #     WHERE wb_kol_tag >= 8;
        # """
        # self.cursor.execute(cancel_sql)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        # logger.info(f"data_tiktok_video_obsess_overview_month AI标签名， 成功{affect_row}")
        #
        # cancel_sql = """
        #     UPDATE bi.data_tiktok_video_obsess_overview
        #     SET wb_kol_tag = wb_kol_tag & ~8
        #     WHERE wb_kol_tag >= 8;
        # """
        # self.cursor.execute(cancel_sql)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        #
        # logger.info(f"data_tiktok_video_obsess_overview AI标签名， 成功{affect_row}")


    def _add_ai_tag_to_video_meta_by_kol(self):
        stmt = """
               SELECT kp.account_id, wb_kol_tag
               FROM bi.data_sys_tiktok_obsess_kol kol
                        LEFT JOIN bi.data_sys_tiktok_obsess_kol_platform kp ON kol.kol_id = kp.kol_id
               WHERE (kol.`wb_kol_tag` & 8) = 8 AND kp.account_id is NOT null AND kol.status = 4 \
               """
        self.rcursor.execute(stmt)
        result = self.rcursor.fetchall()
        creator_ids = [row['account_id'] for row in result] if result else []

        creator_ids_str = ",".join(['%s'] * len(creator_ids))

        update_stmt = f"""
            UPDATE bi.data_tiktok_video_meta 
            SET wb_kol_tag = wb_kol_tag | 8 
            WHERE creator_id IN ({creator_ids_str});
        """
        self.cursor.execute(update_stmt, creator_ids)
        affect_row = self.cursor.rowcount
        self.dbconn.commit()
        logger.info(f"根据kol标签达人修改data_tiktok_video_meta记录， 成功{affect_row}")

        # update_stmt = f"""
        #     UPDATE bi.data_tiktok_video_obsess_details
        #     SET wb_kol_tag = wb_kol_tag | 8
        #     WHERE creator_id IN ({creator_ids_str});
        # """
        # self.cursor.execute(update_stmt, creator_ids)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        # logger.info(f"根据kol标签达人修改data_tiktok_video_obsess_details记录， 成功{affect_row}")
        #
        # update_stmt = f"""
        #     UPDATE bi.data_tiktok_video_obsess_details_month
        #     SET wb_kol_tag = wb_kol_tag | 8
        #     WHERE creator_id IN ({creator_ids_str});
        # """
        # self.cursor.execute(update_stmt, creator_ids)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        # logger.info(f"根据kol标签达人修改记录， 成功{affect_row}")
        #
        # update_stmt = f"""
        #     UPDATE bi.data_tiktok_video_obsess_overview
        #     SET wb_kol_tag = wb_kol_tag | 8
        #     WHERE creator_id IN ({creator_ids_str});
        # """
        # self.cursor.execute(update_stmt, creator_ids)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        # logger.info(f"根据kol标签达人修改data_tiktok_video_obsess_overview记录， 成功{affect_row}")
        #
        # update_stmt = f"""
        #     UPDATE bi.data_tiktok_video_obsess_overview_month
        #     SET wb_kol_tag = wb_kol_tag | 8
        #     WHERE creator_id IN ({creator_ids_str});
        # """
        # self.cursor.execute(update_stmt, creator_ids)
        # affect_row = self.cursor.rowcount
        # self.dbconn.commit()
        # logger.info(f"根据kol标签达人修改data_tiktok_video_obsess_overview_month记录， 成功{affect_row}")


    def _add_ai_tag_to_video_meta_by_video_name(self):
        """
        根据video_name更新AI标签
        """
        stmt = """
               UPDATE bi.data_tiktok_video_meta
               SET wb_kol_tag = wb_kol_tag | 8
               WHERE video_name LIKE "%[AI]%" OR video_name LIKE "%【AI】%"; \
               """
        self.cursor.execute(stmt)
        affect_row = self.cursor.rowcount
        self.dbconn.commit()

        logger.info(f"根据名称修改记录， 成功{affect_row}")


    def _add_ai_tag_to_video_obsess_details_by_file(self):
        df = pd.read_excel("TT短视频-历史自营短视频需要打上AI标签的list.xlsx")
        vdo_list = df["视频ID"].unique().tolist()

        vdo_list_str = ",".join(['%s'] * len(vdo_list))

        update_stmt = f"""
            UPDATE bi.data_tiktok_video_meta 
            SET wb_kol_tag = wb_kol_tag | 8 
            WHERE video_id IN ({vdo_list_str});
        """
        self.cursor.execute(update_stmt, vdo_list)
        affect_row = self.cursor.rowcount
        self.dbconn.commit()
        logger.info(f"根据文件修改data_tiktok_video_meta记录， 成功{affect_row}")


    def _update_tiktok_meta_AI_tag(self):
        """更新meta表中AI标签"""
        self._cancel_video_meta_ai_tag()
        self._add_ai_tag_to_video_meta_by_kol()
        self._add_ai_tag_to_video_meta_by_video_name()
        self._add_ai_tag_to_video_obsess_details_by_file()

        return


    def _update_tiktok_meta(self,video_dicts):
        # update_col = ','.join([f'{col}=%s' for col in self.columns[1:]]+['roi_pit_location_fee=%s'])
        # len_data = len(video_dicts)
        # # 更新坑位费
        # for idx,update in enumerate(video_dicts):
        #     logger.info(f'{len_data} \ {idx}')
        #     update_tup = tuple([update[col] for col in self.columns[1:]]+[update['roi_pit_location_fee']]+[update['video_id']])
        #     # 为每个更新构建 SQL 语句
        #     sql = "UPDATE bi.data_tiktok_video_meta SET "+update_col+" WHERE video_id=%s"
        #     self.cursor.execute(sql, update_tup)
        # self.dbconn.commit()

        video_list = list(video_dicts.values())
        # for video_data in video_list:
        #     video_data['product_list'] = ''
        #     video_data['video_publish_time'] = '1970-01-01 12:00:00'

        if len(video_list)>0:
            update_col = ','.join([f'{col}' for col in self.columns]+['roi_pit_location_fee','product_list','video_publish_time'])
            update_col_s = ','.join([f'%({col})s' for col in self.columns]+['%(roi_pit_location_fee)s','%(product_list)s','%(video_publish_time)s'])
            update_col_e = ','.join([f'{col}=VALUES({col})' for col in self.columns[1:]]+['roi_pit_location_fee=VALUES(roi_pit_location_fee)'])
            sql = " INSERT INTO bi.data_tiktok_video_meta ("+update_col+")  VALUES ("+update_col_s+")  ON DUPLICATE KEY UPDATE "+update_col_e
            self.cursor.executemany(sql, video_list)
            self.dbconn.commit()

        # 更新meta表的花费
        if len(video_dicts)>0:
            video_ids = ','.join([f"'{video_id[1]}'" for video_id in video_dicts.keys()])
            spend_usd_str = '+'.join(spend_cols_conf)
            stmt = "update bi.data_tiktok_video_meta set spend_usd = "+spend_usd_str+" where video_id in("+video_ids +")"
            self.cursor.execute(stmt)
            self.dbconn.commit()

        creator_ids = self._get_creator_ids()
        canceled_creator_ids = self._get_canceled_creator_ids()
        if creator_ids:
            creator_ids_str = ",".join(['%s']*len(creator_ids))
            canceled_creator_ids_str = ",".join(['%s']*len(canceled_creator_ids))

            # query = f"""
            #     SELECT shop_id, video_id, creator_id
            #     FROM bi.data_tiktok_video_meta
            #     WHERE creator_id IN ({creator_ids_str}) AND (wb_kol_tag & 1) = 0
            # """
            # self.rcursor.execute(query)
            # result = self.rcursor.fetchall()
            logger.info("更新wb_kol_tag")
            update_query = f"""
                    UPDATE bi.data_tiktok_video_meta 
                    SET wb_kol_tag = wb_kol_tag | 1 
                    WHERE creator_id IN ({creator_ids_str}) AND (wb_kol_tag & 1) = 0;
                """

            self.cursor.execute(update_query,creator_ids)
            self.dbconn.commit()
            logger.info("取消wb_kol_tag标签")
            update_query = f"""
                UPDATE bi.data_tiktok_video_meta 
                SET wb_kol_tag = wb_kol_tag & ~1 
                WHERE creator_id IN ({canceled_creator_ids_str}) AND (wb_kol_tag & 1) = 1;
                """

            self.cursor.execute(update_query,canceled_creator_ids)
            self.dbconn.commit()


    def _update_tiktok_start_date_to_plan(self):
        logger.info('更新obsess_plan表的start_date')
        stmt = """select tiktok_video_id from bi.data_sys_tiktok_obsess_plan where tiktok_start_date is null"""
        self.rcursor.execute(stmt)
        video_ids = [vdata['tiktok_video_id'] for vdata in self.rcursor.fetchall()]
        video_id_count = len(video_ids)
        bs = 100
        for i in range(0, video_id_count, bs):
            logger.info(f'更新obsess_plan表的start_date进度：{video_id_count} \ {i}')
            cur_video_ids = video_ids[i:i + bs]
            cur_video_ids_str = ','.join([f"'{video_id}'" for video_id in cur_video_ids])

            stmt = f"""SELECT shop_id, video_id, start_time AS start_date
                    FROM (
                        SELECT shop_id, 
                            video_id, 
                            start_time,
                            ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY start_time) AS rn
                        FROM bi.data_tiktok_video
                        WHERE video_id IN ({cur_video_ids_str})
                    ) t
                    WHERE rn = 1"""
            self.rcursor.execute(stmt)
            video_datas = self.rcursor.fetchall()

            video_dicts = {}
            for video_data in video_datas:
                key = (video_data['shop_id'],video_data['video_id'])
                if key not in video_dicts:
                    video_dicts[key] = tuple((video_data['start_date'],video_data['video_id'],video_data['shop_id']))

            update_data = list(video_dicts.values())

            if len(update_data)>0:
                sttm = """update bi.data_sys_tiktok_obsess_plan set tiktok_start_date=%s where tiktok_video_id=%s and shop_id=%s"""
                self.cursor.executemany(sttm, update_data)
                self.dbconn.commit()


    def _update_tiktok_video_auto_clip(self, start_date, end_date):
        # 获取需要更新的种草类型
        sql = """
              SELECT kol.name, plat.account_id,
                     CASE WHEN kol.account_type = 2 THEN 'Official' WHEN kol.account_type = 3 THEN 'Marketing' ELSE 'OTHER' END AS account_type
              FROM bi.data_sys_tiktok_obsess_kol kol
                       LEFT JOIN bi.data_sys_tiktok_obsess_kol_platform plat ON  kol.kol_id = plat.kol_id
              WHERE  plat.account_id is not null and kol.account_type in (2, 3) \
              """

        kol_df = read_client.get_df_by_sql(sql)

        for _, row in kol_df.iterrows():
            try:
                creator_id = row['account_id']
                name = row['name']
                logger.info(f"开始处理创作者：{name}({creator_id})")
                select_sql = f"""
                             SELECT video_id, creator_type, product_list, video_name
                             FROM bi.data_tiktok_video 
                             WHERE start_time <= "{start_date}" and start_time >= "{end_date}" and creator_id = '{creator_id}'
                             """
                vdo_df = read_client.get_df_by_sql(select_sql)
                logger.info(f"查询data_tiktok_video记录：{len(vdo_df)}条")
                if isinstance(vdo_df,pd.DataFrame):
                    if vdo_df.empty:
                        continue
                else:
                    if not vdo_df:
                        continue

                vdo_df['video_name'] = vdo_df['video_name'].fillna('')
                vdo_df = vdo_df[~vdo_df['video_id'].isin([0, '0'])]
                # Step 1: 在全量数据上判断每个 video_id 是否不挂车、标题长度≤100、无"#"
                affiliate_video_ids = (
                    vdo_df.groupby('video_id')
                    .apply(lambda x: (
                            x['video_name'].str.len().le(100).all() and  # 视频标题字符长度≤100
                            (~x['video_name'].str.contains('#')).all() and  # 视频标题无 "#"
                            x['product_list'].isin([[], '[]']).all()  # 新增：所有的 product_list 都是 空
                    ))
                )
                affiliate_video_ids = set(affiliate_video_ids[affiliate_video_ids].index)

                # Step 2: 过滤出满足两个条件的行
                mask = (
                        vdo_df['video_id'].isin(affiliate_video_ids) &
                        vdo_df['creator_type'].isin(['Official', 'Marketing'])
                )
                video_ids = vdo_df[mask]['video_id'].unique().tolist()

                if not video_ids:
                    logger.info(f"creator_id={creator_id} 没有需要更新的 video_id")
                    continue

                placeholders = ','.join(['%s'] * len(video_ids))
                update_sql = f"""
                    UPDATE bi.data_tiktok_video_meta
                    SET wb_kol_tag = wb_kol_tag | 64
                    WHERE video_id IN ({placeholders}) AND (wb_kol_tag & 64) = 0
                """
                self.cursor.execute(update_sql, tuple(video_ids))
                self.dbconn.commit()
                if len(video_ids)>10:
                    logger.info(f"creator_id={creator_id} 更新了 {len(video_ids)} 个 video_id, video_ids: {video_ids[:10]}")
                else:
                    logger.info(f"creator_id={creator_id} 更新了 {len(video_ids)} 个 video_id, video_ids: {video_ids}")
            except Exception as e:
                logger.error(e)


    def _match_kol_platform_account_by_name(self):
        sql = """
              SELECT
                  _id,
                  REPLACE(account, ' (account does not exist)', '') AS creator_handle
              FROM `data_sys_tiktok_obsess_kol_platform`
              WHERE account LIKE '%(account does not exist)%' \
              """

        vdo_df = read_client.get_df_by_sql(sql)
        creators = vdo_df["creator_handle"].unique().tolist()

        creator_str = ','.join(['%s'] * len(creators))

        sql = f"""
         SELECT distinct creator_id account_id, creator_handle FROM bi.data_tiktok_video
         WHERE creator_handle IN ({creator_str})
        """
        creator_df = read_client.get_df_by_sql_params(sql, creators)

        kol_df = vdo_df.merge(creator_df, on='creator_handle', how='left')

        unknown_kol_df = kol_df[kol_df["account_id"].isna()]
        unknown_creators = unknown_kol_df["creator_handle"].unique().tolist()

        live_creator_df = pd.DataFrame()  # 初始化一个空 DataFrame
        if unknown_creators:
            unknown_creator_str = ','.join(['%s'] * len(unknown_creators))
            live_sql = f"""
                SELECT distinct creator_id AS account_id, creator_handle 
                FROM bi.data_tiktok_live
                WHERE creator_handle IN ({unknown_creator_str})
            """

            live_creator_df = read_client.get_df_by_sql_params(live_sql, unknown_creators)

            if not live_creator_df.empty:
                kol_df = kol_df.merge(live_creator_df, on='creator_handle', how='left', suffixes=('_video', '_live'))
                kol_df['account_id'] = kol_df['account_id_video'].combine_first(kol_df['account_id_live'])
                kol_df.drop(columns=['account_id_video', 'account_id_live'], inplace=True)
        kol_df = kol_df.dropna(subset=['account_id', 'creator_handle'])
        kol_df.rename(columns={'creator_handle': 'account'}, inplace=True)
        write_client.insert_many_by_executemany(table_name="bi.data_sys_tiktok_obsess_kol_platform", tmp_df=kol_df, with_id=True)

    def process(self, start_date, end_date):
        try:
            video_dicts = self._get_tiktok_obsess_data()
            self._update_tiktok_meta(video_dicts)

            self._update_tiktok_start_date_to_plan()
            self._update_tiktok_meta_AI_tag()
            self._update_tiktok_video_auto_clip(start_date, end_date)
            self._match_kol_platform_account_by_name()
            return True
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(tb)
            return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="更新 data_tiktok_kol_obsess_analysis creator_type 和 video_publish_date")
    parser.add_argument("--start_date", type=str, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, help="结束日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    update_tiktok_kol = UpdateTikTokVideoKolData()
    start_date = args.start_date
    end_date = args.end_date
    if not start_date:
        start_date = datetime.datetime.now()
        end_date = start_date - datetime.timedelta(days=30)
        start_date = start_date.strftime("%Y-%m-%d")
        end_date = end_date.strftime("%Y-%m-%d")

    ret = update_tiktok_kol.process(start_date, end_date)

    exit(0 if ret else -1)
