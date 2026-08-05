# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/2
# @Author  : Zhu Yaming
# @File    : distribution_order_log.py
# @Description : 分销订单操作日志查询
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import Depends, Request
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.model.yy_log import Log
from core.db.session import get_async_session

from apps.system.distribution_order.auth import oauth2_scheme
from apps.system.distribution_order.constants import TAG_LABELS
from apps.system.distribution_order.distribution_order_extent import (
    get_key_options_from_filter_value,
    get_table_config,
)
from apps.system.distribution_order.distribution_order_workflow_engine import (
    ACTION_ORDER_REJECT,
    ACTION_QUOTE_REJECT,
    ACTION_STR,
    STATUS_STR,
    _resolve_operator_name,
)
from apps.system.distribution_order.models import DistributionOrderStatusLog
from apps.system.distribution_order.log_parse import parse_distribution_order_log_title
from apps.system.distribution_order.operation_log import (
    DISTRIBUTION_ORDER_LOG_IGNORE_KEYS,
    DISTRIBUTION_ORDER_LOG_REFER_TABLE,
    get_log_field_label_map,
)
from apps.system.distribution_order.translate import (
    get_translaiton_dict_from_request,
    translate_text,
)


def _status_log_title(
    *,
    operator_name: str,
    action_code_str: str,
    from_status_str: str,
    to_status_str: str,
    remark: Optional[str],
    remark_name: str,
    is_trans: bool,
    translation_dict: Dict[str, Any],
) -> str:
    if is_trans:
        action_code_str = translate_text(action_code_str, is_trans, translation_dict)
        from_status_str = translate_text(from_status_str, is_trans, translation_dict)
        to_status_str = translate_text(to_status_str, is_trans, translation_dict)
        field_label = translate_text("状态", is_trans, translation_dict)
        remark_name = translate_text(remark_name, is_trans, translation_dict)
    else:
        field_label = "状态"
    remark_str = ""
    if remark:
        remark_str = " ,%s: %s" % (remark_name, remark)
    return (
        "%s %s 【 %s: %s → %s%s 】"
        % (operator_name, action_code_str, field_label, from_status_str, to_status_str, remark_str)
    )


async def get_distribution_order_logs(
    request: Request,
    order_id: Optional[int] = None,
    record_table: str = DISTRIBUTION_ORDER_LOG_REFER_TABLE,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    """获分销订单日志；order_id 为主单 _id。"""
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "common_filters", "msg"],
    )
    if not order_id:
        msg = translate_text("order_id 不能为空", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    if not record_table:
        msg = translate_text("参数错误", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}

    try:
        table_base_data = await get_table_config(inter_session, request)
        filter_value = table_base_data.get("filter_value") or []
        extent_cols = get_key_options_from_filter_value(
            filter_value, is_trans=is_trans, translation_dict=translation_dict,
        )
        schemas = get_log_field_label_map(filter_value)
        key_value_dict = dict(extent_cols)
        key_value_dict.pop("log_display", None)
        if "tags" not in key_value_dict:
            key_value_dict["tags"] = dict(TAG_LABELS)

        remark_info: List[Dict[str, str]] = []

        log_rows = (
            await inter_session.execute(
                select(Log)
                .where(
                    Log.refer_id == int(order_id),
                    Log.refer_table == record_table,
                )
                .order_by(desc(Log._id))
            )
        ).scalars().all()

        ignore_keys = set(DISTRIBUTION_ORDER_LOG_IGNORE_KEYS)
        for record in log_rows:
            try:
                o_details = json.loads(record.operation_details or "{}")
            except (TypeError, ValueError):
                logger.warning("分销订单日志 JSON 解析失败 order_id=%s", order_id)
                continue
            title = parse_distribution_order_log_title(
                o_details,
                schemas,
                user_name=record.user or "",
                op_type=record.type or "",
                ignore_keys=ignore_keys,
                request=request,
                key_value_dict=key_value_dict,
                is_trans=is_trans,
                translation_dict=translation_dict,
            )
            remark_info.append({
                "time": record.create_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
            })

        status_logs = (
            await inter_session.execute(
                select(DistributionOrderStatusLog)
                .where(DistributionOrderStatusLog.order_id == int(order_id))
                .order_by(
                    DistributionOrderStatusLog.create_time,
                    DistributionOrderStatusLog._id,
                )
            )
        ).scalars().all()

        for log in status_logs:
            operator_name = await _resolve_operator_name(inter_session, log.operator_id)
            if not operator_name:
                operator_name = "System"
            from_status_str = STATUS_STR.get(log.from_status, str(log.from_status or ""))
            to_status_str = STATUS_STR.get(log.to_status, str(log.to_status))
            action_code_str = ACTION_STR.get(log.action_code, str(log.action_code or ""))
            remark_name = "备注"
            if int(log.action_code or 0) in (ACTION_QUOTE_REJECT, ACTION_ORDER_REJECT):
                remark_name = "驳回原因"
            title = _status_log_title(
                operator_name=operator_name,
                action_code_str=action_code_str,
                from_status_str=from_status_str,
                to_status_str=to_status_str,
                remark=(log.remark or "").strip() or None,
                remark_name=remark_name,
                is_trans=is_trans,
                translation_dict=translation_dict,
            )
            remark_info.append({
                "time": log.create_time.strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
            })

        remark_info.sort(key=lambda x: x["time"], reverse=True)
        msg = translate_text("获取数据成功", is_trans, translation_dict)
        if not remark_info:
            msg = translate_text("暂无日志数据", is_trans, translation_dict)
        return {"code": 200, "msg": msg, "data": {"remark_info": remark_info}}
    except Exception as e:
        logger.error("分销订单日志查询失败 order_id=%s: %s", order_id, e)
        msg = translate_text("获取数据失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
