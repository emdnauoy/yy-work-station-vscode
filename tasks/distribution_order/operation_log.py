# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/29
# @Author  : Zhu Yaming
# @File    : operation_log.py
# @Description : 分销下单操作日志（主表 diff 直写；order_detail/quote_detail 为数组）
"""
import datetime
import json
import os
from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Union

from fastapi import Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.service.yy_log import log_async_create
from apps.system.offline_customer.change_diff import deep_diff, deep_diff_create

DISTRIBUTION_ORDER_LOG_REFER_TYPE = "分销下单"
DISTRIBUTION_ORDER_LOG_REFER_TABLE = "data_distribution_order"

LOG_SCOPE_QUOTE_DETAIL = "quote_detail"
LOG_SCOPE_ORDER_DETAIL = "order_detail"
LOG_SCOPE_PREPAY_CONFIRM = "prepay_confirm"
LOG_SCOPE_RECEIVE_CONFIRM = "receive_confirm"
LOG_SCOPE_PAYMENT_CONFIRM = "payment_confirm"
LOG_SCOPE_SPLIT_ORDER = "split_order"
LOG_SCOPE_DISPATCH = "dispatch"
LOG_SCOPE_ADJUSTMENT = "adjustment"

_DETAIL_MODULE_KEYS = frozenset({
    LOG_SCOPE_ORDER_DETAIL, LOG_SCOPE_QUOTE_DETAIL, LOG_SCOPE_ADJUSTMENT,
})

_LOG_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_DATE_FMT = "%Y-%m-%d"

DISTRIBUTION_ORDER_LOG_IGNORE_KEYS: Set[str] = {
    "_id",
    "tags",
    "contract_no",
    "create_time",
    "update_time",
    "created_by",
    "updated_by",
    "create_by",
    "update_by",
    "button_list",
    "status",
    "status_str",
    "current_step",
    "current_chain_code",
    "tags_bitmask",
    "quote_approval_flow",
    "order_approval_flow",
    "deleted_quote_detail_ids",
    "deleted_order_detail_ids",
    "submit_by",
    "quote_lm_user_id",
    "order_lm_user_id",
    "is_delete"
}

LOG_DISPLAY_CONFIG_KEY = "log_display"
_LOG_DISPLAY_JSON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "log_display.json",
)


def _flat_options_to_label_map(options: List[Any]) -> Dict[Any, str]:
    result: Dict[Any, str] = {}
    for item in options or []:
        if not isinstance(item, dict):
            continue
        value, label = item.get("value"), item.get("label")
        if value is not None and label is not None:
            result[value] = label
        children = item.get("children") or item.get("sub") or item.get("list")
        if children:
            result.update(_flat_options_to_label_map(children))
    return result


@lru_cache(maxsize=1)
def _log_field_labels_from_file() -> Dict[Any, str]:
    """合入主仓前：读任务目录 log_display.json；与表头 filter_value.log_display 同源。"""
    try:
        with open(_LOG_DISPLAY_JSON_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (IOError, OSError, ValueError):
        return {}
    options = data.get("options") or data.get("search_list") or []
    return _flat_options_to_label_map(options)


def get_log_field_label_map(
    filter_value: Optional[List[Dict[str, Any]]] = None,
) -> Dict[Any, str]:
    """字段 value→label：log_display.json 打底，表头 log_display 覆盖。"""
    merged = dict(_log_field_labels_from_file())
    if filter_value:
        from apps.system.distribution_order.distribution_order_extent import (
            get_key_options_from_filter_value,
        )
        cols = get_key_options_from_filter_value(
            filter_value, {LOG_DISPLAY_CONFIG_KEY},
        )
        label_map = cols.get(LOG_DISPLAY_CONFIG_KEY)
        if isinstance(label_map, dict):
            merged.update(label_map)
    return merged


def get_log_field_label(
    field_key: str,
    filter_value: Optional[List[Dict[str, Any]]] = None,
) -> str:
    return get_log_field_label_map(filter_value).get(field_key, field_key)


def _normalize_log_scalar(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, datetime.datetime):
        return obj.strftime(_LOG_DATETIME_FMT)
    if isinstance(obj, datetime.date):
        return obj.strftime(_LOG_DATE_FMT)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def to_log_dict(data: Any) -> Any:
    return _to_log_value(data)


def _to_log_value(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, BaseModel):
        return _to_log_value(data.dict(by_alias=True))
    if isinstance(data, dict):
        return {k: _to_log_value(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_to_log_value(item) for item in data]
    return _normalize_log_scalar(data)


# 操作日志 title 展示解析见 log_parse.parse_distribution_order_log_title


def normalize_log_payload(data: Any) -> Dict[str, Any]:
    """quote_details/order_details → quote_detail/order_detail；去掉 lines 包装。"""
    raw = to_log_dict(data)
    if not isinstance(raw, dict):
        return {}
    out = dict(raw)
    if "quote_details" in out and LOG_SCOPE_QUOTE_DETAIL not in out:
        out[LOG_SCOPE_QUOTE_DETAIL] = out.pop("quote_details")
    if "order_details" in out and LOG_SCOPE_ORDER_DETAIL not in out:
        out[LOG_SCOPE_ORDER_DETAIL] = out.pop("order_details")
    for key in _DETAIL_MODULE_KEYS:
        val = out.get(key)
        if isinstance(val, dict) and list(val.keys()) == ["lines"]:
            out[key] = val["lines"]
    return out


def _module_create_value(
    snapshot: Union[Dict[str, Any], List[Any]],
    keys: Set[str],
) -> Any:
    snap = to_log_dict(snapshot)
    if isinstance(snap, list):
        return snap
    return deep_diff_create(snap, ignore_keys=keys) or {}


def _list_diff_to_array(diff: Any) -> Any:
    """deep_diff 列表明细为 {id: change}，转为 [{_id, ...change}] 列表。"""
    if not isinstance(diff, dict):
        return diff
    if "old" in diff and "new" in diff:
        return diff
    if not diff:
        return diff
    if not all(isinstance(v, dict) for v in diff.values()):
        return diff
    items = []
    for rid, change in diff.items():
        row = {"_id": int(rid) if str(rid).isdigit() else rid}
        if isinstance(change, dict):
            if set(change.keys()) <= {"old", "new"}:
                row["old"] = change.get("old")
                row["new"] = change.get("new")
            else:
                for k, v in change.items():
                    row[k] = v
        items.append(row)
    return items


def _build_combined_update_diff(
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
    keys: Set[str],
) -> Dict[str, Any]:
    old_p = normalize_log_payload(old_data)
    new_p = normalize_log_payload(new_data)
    old_main = {k: v for k, v in old_p.items() if k not in _DETAIL_MODULE_KEYS}
    new_main = {k: v for k, v in new_p.items() if k not in _DETAIL_MODULE_KEYS}
    payload: Dict[str, Any] = {}
    main_diff = deep_diff(
        old_data=old_main, new_data=new_main, ignore_keys=keys,
    )
    if main_diff:
        payload.update(main_diff)
    for mod_key in _DETAIL_MODULE_KEYS:
        old_mod = old_p.get(mod_key)
        new_mod = new_p.get(mod_key)
        if old_mod is None and new_mod is None:
            continue
        mod_diff = deep_diff(
            old_data=old_mod if isinstance(old_mod, list) else [],
            new_data=new_mod if isinstance(new_mod, list) else [],
            ignore_keys=keys,
        )
        if mod_diff:
            payload[mod_key] = _list_diff_to_array(mod_diff)
    return payload


def log_json_default(obj: Any) -> Any:
    if obj is None:
        return None
    return _normalize_log_scalar(obj)


def log_json_serializer(obj: Any) -> Any:
    if obj is None:
        return "None"
    return _normalize_log_scalar(obj)


def _format_operation_details(
    scope: Optional[str], payload: Dict[str, Any],
) -> Dict[str, Any]:
    if scope:
        return {scope: payload}
    return payload


def get_operator_display_name(request: Request) -> str:
    u = getattr(request, "user", None)
    if u is None:
        return ""
    return (
        getattr(u, "display_name", None)
        or getattr(u, "username", None)
        or str(getattr(u, "id", "") or "")
    )


async def log_distribution_order_create_with_modules(
    session: AsyncSession,
    *,
    username: str,
    order_id: int,
    main_snapshot: Dict[str, Any],
    modules: Optional[Dict[str, Union[Dict[str, Any], List[Any]]]] = None,
    ignore_keys: Optional[Set[str]] = None,
) -> None:
    keys = ignore_keys if ignore_keys is not None else DISTRIBUTION_ORDER_LOG_IGNORE_KEYS
    main = normalize_log_payload(main_snapshot)
    payload = deep_diff_create(main, ignore_keys=keys) or {}
    for scope, snapshot in (modules or {}).items():
        inner = _module_create_value(snapshot, keys)
        if inner:
            payload[scope] = inner
    operation_details = json.dumps(
        payload, ensure_ascii=False, default=log_json_default,
    )
    await log_async_create(
        username=username,
        types="新建",
        operation_details=operation_details,
        session=session,
        refer_type=DISTRIBUTION_ORDER_LOG_REFER_TYPE,
        refer_table=DISTRIBUTION_ORDER_LOG_REFER_TABLE,
        refer_id=order_id,
    )


async def log_distribution_order_create(
    session: AsyncSession,
    *,
    username: str,
    order_id: int,
    snapshot: Union[Dict[str, Any], List[Any]],
    scope: Optional[str] = None,
    ignore_keys: Optional[Set[str]] = None,
) -> None:
    keys = ignore_keys if ignore_keys is not None else DISTRIBUTION_ORDER_LOG_IGNORE_KEYS
    if isinstance(snapshot, list):
        inner = to_log_dict(snapshot) or []
    else:
        inner = deep_diff_create(normalize_log_payload(snapshot), ignore_keys=keys) or {}
    operation_details = json.dumps(
        _format_operation_details(scope, inner),
        ensure_ascii=False,
        default=log_json_default,
    )
    await log_async_create(
        username=username,
        types="新建",
        operation_details=operation_details,
        session=session,
        refer_type=DISTRIBUTION_ORDER_LOG_REFER_TYPE,
        refer_table=DISTRIBUTION_ORDER_LOG_REFER_TABLE,
        refer_id=order_id,
    )


async def log_distribution_order_update(
    session: AsyncSession,
    *,
    username: str,
    order_id: int,
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
    scope: Optional[str] = None,
    ignore_keys: Optional[Set[str]] = None,
) -> None:
    keys = ignore_keys if ignore_keys is not None else DISTRIBUTION_ORDER_LOG_IGNORE_KEYS
    if scope:
        clean_logs = deep_diff(
            old_data=normalize_log_payload(old_data),
            new_data=normalize_log_payload(new_data),
            ignore_keys=keys,
        )
    else:
        clean_logs = _build_combined_update_diff(old_data, new_data, keys)
    if not clean_logs:
        return
    operation_details = json.dumps(
        _format_operation_details(scope, clean_logs),
        ensure_ascii=False,
        default=log_json_serializer,
    )
    await log_async_create(
        username=username,
        types="更新",
        operation_details=operation_details,
        session=session,
        refer_type=DISTRIBUTION_ORDER_LOG_REFER_TYPE,
        refer_table=DISTRIBUTION_ORDER_LOG_REFER_TABLE,
        refer_id=order_id,
    )


def build_distribution_order_log_title(*args: Any, **kwargs: Any) -> str:
    """兼容旧 import 路径；实现已迁至 log_parse。"""
    from apps.system.distribution_order.log_parse import (
        build_distribution_order_log_title as _impl,
    )
    return _impl(*args, **kwargs)
