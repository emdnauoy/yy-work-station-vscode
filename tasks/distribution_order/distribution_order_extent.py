# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/1
# @Author  : Zhu Yaming
# @File    : distribution_order_extent.py
# @Description : 详情扩展：filter_value 映射 _str、驳回目标、按钮权限
"""
from __future__ import annotations

import asyncio
import datetime
import time as time_module
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from apps.system.reports.view.common_func import get_common_user_dict

from apps.common.service.table_title_desc_mapping import async_get_one_title_mapping
from apps.system.reports.view.common_func import get_common_exchange_rate_dict, get_common_finance_exchange_rate_dict, get_nation_currency_exchange_rate_df, safe_divide_round
from apps.common.service.user import UserService
from apps.system.offline_customer.view.sys_offline_contract_view import (
    change_category_tree,
)
from apps.system.distribution_order.constants import STATUS_BUTTON_LIST, TAG_LABELS
from apps.system.distribution_order.distribution_order_tags import (
    decode_tags,
    refresh_order_tags,
)
from apps.system.distribution_order.distribution_order_workflow_engine import (
    APPROVER_TYPE_LINE_MANAGER,
    should_include_approval_step,
    CHAIN_PRICING,
    OPERATOR_APPROVER,
    OPERATOR_CREATOR,
    STATUS_DRAFT,
    STATUS_ORDER_CREATE,
    STATUS_ORDER_REVIEW,
    STATUS_QUOTE_REVIEW,
    _find_approval_step_by_no,
    _load_approval_steps,
    _load_order,
    _resolve_operator_name,
    get_approval_users,
    get_customer_country,
    line_manager_user_id_for_chain,
    resolve_current_executor_display_name,
    user_can_review_at_step,
)

from apps.system.distribution_order.models import DistributionOrder, DistributionOrderItemDetail, DistributionOrderQuoteDetail, DistributionOrderPrepayment, DistributionOrderBalancePayment, DistributionOrderAdjustment, \
    DistributionOrderSnapshot
from apps.system.distribution_order.translate import translate_text
from apps.system.reports.view.common_func import get_translaiton_dict_from_request


def _translate_list_values(lst: List[Any], col_map: Dict[Any, Any]) -> List[Any]:
    out: List[Any] = []
    for item in lst:
        if isinstance(item, dict):
            continue
        translated = col_map.get(item)
        if translated is not None:
            out.append(translated)
    return out


def recursive_translate_data(data: Any, dict_map: Dict[str, Dict[Any, Any]]) -> None:
    if isinstance(data, dict):
        for key, value in list(data.items()):
            if key in dict_map and value is not None:
                col_map = dict_map[key]
                if isinstance(col_map, dict):
                    if isinstance(value, list):
                        translated_list = _translate_list_values(value, col_map)
                        if translated_list:
                            data["%s_str" % key] = translated_list
                    elif not isinstance(value, dict):
                        translated_value = col_map.get(value)
                        if translated_value is not None:
                            data["%s_str" % key] = translated_value
            if isinstance(value, dict):
                recursive_translate_data(value, dict_map)
            elif isinstance(value, list):
                recursive_translate_data(value, dict_map)
    elif isinstance(data, list):
        for item in data:
            recursive_translate_data(item, dict_map)


_DEFAULT_PATH_LABEL_KEYS = frozenset({"fee_category_id"})
_PATH_LABEL_TRANSLATION_MODULES = ["offline_customer", "common", "msg"]


def get_key_options_from_filter_value(
    filter_value: List[Dict[str, Any]],
    target_keys: Optional[set] = None,
    path_label_keys: Optional[set] = None,
    translate_path_label_keys: Optional[set] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[Any, Any]]:
    """
    从 filter_value 提取 value→label 映射。
    path_label_keys：树形选项拼接祖先 label，如 fee_category_id →「一级/二级/三级」；
    默认 {"fee_category_id"}，传空 set 关闭。
    translate_path_label_keys：拼接前逐段翻译 label，默认与 path_label_keys 中 fee_category_id 一致。
    """

    def _extract_tree_options(
        nodes: List[Dict[str, Any]],
        *,
        ancestors: Optional[List[str]] = None,
        use_path_label: bool = False,
        translate_labels: bool = False,
    ) -> Dict[Any, Any]:
        local_map: Dict[Any, Any] = {}
        prefix = ancestors or []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            value, label = node.get("value"), node.get("label")
            label_text = "" if label is None else str(label).strip()
            if translate_labels and label_text:
                label_text = translate_text(label_text, is_trans, translation_dict) or label_text
            path_parts = prefix + ([label_text] if label_text else [])
            children = node.get("children") or node.get("sub") or node.get("list")
            if value is not None and label is not None:
                if use_path_label and path_parts:
                    local_map[value] = "/".join(path_parts)
                else:
                    local_map[value] = label
            if children:
                local_map.update(
                    _extract_tree_options(
                        children,
                        ancestors=path_parts,
                        use_path_label=use_path_label,
                        translate_labels=translate_labels,
                    )
                )
        return local_map

    path_keys = _DEFAULT_PATH_LABEL_KEYS if path_label_keys is None else path_label_keys
    translate_keys = (
        _DEFAULT_PATH_LABEL_KEYS if translate_path_label_keys is None else translate_path_label_keys
    )
    result: Dict[str, Dict[Any, Any]] = {}
    for item in filter_value or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key:
            continue
        if target_keys and key not in target_keys:
            continue
        options = item.get("options") or item.get("search_list") or []
        if options:
            use_path = key in path_keys
            translate_path = (
                use_path
                and key in translate_keys
                and is_trans
                and translation_dict
            )
            result[key] = _extract_tree_options(
                options,
                use_path_label=use_path,
                translate_labels=bool(translate_path),
            )
    return result


def _download_col_def(
    label: str,
    value: Any,
    join: str = "",
    suffix: Optional[List[str]] = None,
    all_tags: Any = None,
    is_detail: bool = False,
) -> Dict[str, Any]:
    fields = value if isinstance(value, list) else [value]
    return {
        "label": label,
        "value": list(fields),
        "join": join or "",
        "suffix": list(suffix or []),
        "allTags": all_tags,
        "is_detail": is_detail,
    }


# 导出列 label 与 table_key_group 不完全一致时的兜底（含 USD / 原币等）
DOWNLOAD_EXPORT_LABEL_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "WS分销单号": _download_col_def("WS分销单号", "order_sn"),
    "千易单号": _download_col_def(
        "千易单号", ["system_tracking_number", "order_status"], join="/",
    ),
    "运单号": _download_col_def("运单号", "waybill_no"),
    "分销订单状态": _download_col_def("分销订单状态", "status_str"),
    "客户国家": _download_col_def("客户国家", "customer_country"),
    "客户国家进行中": _download_col_def("客户国家进行中", "customer_country"),
    "客户编码": _download_col_def("客户编码", "customer_code"),
    "客户编码进行中": _download_col_def("客户编码进行中", "customer_code"),
    "SKU编码": _download_col_def("SKU编码", "sku", is_detail=True),
    "销售单价": _download_col_def("销售单价", "price_with_vat", is_detail=True),
    "销售数量": _download_col_def("销售数量", "qty", is_detail=True),
    "含税商品金额(原币)": _download_col_def(
        "含税商品金额(原币)", "amount_with_vat", is_detail=True,
    ),
    "含税订单金额(原币)": _download_col_def("含税订单金额(原币)", "order_amount_with_vat"),
    "含税运费收入(原币)": _download_col_def("含税运费收入(原币)", "freight_with_vat"),
    "含税商品金额(USD)": _download_col_def(
        "含税商品金额(USD)", "amount_with_vat_usd", is_detail=True,
    ),
    "含税订单金额(USD)": _download_col_def("含税订单金额(USD)", "order_amount_with_vat_usd"),
    "含税运费收入(USD)": _download_col_def("含税运费收入(USD)", "freight_with_vat_usd"),
    "商品金额": _download_col_def("商品金额", "goods_amount_with_vat"),
    "订单金额": _download_col_def("订单金额", "order_amount_with_vat"),
    "运费收入": _download_col_def("运费收入", "freight_with_vat"),
    "发货方式": _download_col_def("发货方式", "ship_method_str"),
    "发货店铺": _download_col_def("发货店铺", "shop_name"),
    "发货仓库": _download_col_def("发货仓库", "warehouse"),
    "标签": _download_col_def("标签", "tags"),
    "本次运费承担方": _download_col_def("本次运费承担方", "order_delivery_fee_payment_str"),
    "运费支出": _download_col_def("运费支出", "freight_expense_amount"),
    "预付金额": _download_col_def("预付金额", "actual_prepay_amount"),
    "回款金额": _download_col_def("回款金额", "balance_pay_amount"),
    "实收金额": _download_col_def("实收金额", "actual_paid_amount"),
    "实收数量": _download_col_def(
        "实收数量", ["receive_sku_num", "receive_toal_num"], suffix=["种", "件"],
    ),
    "建单数量": _download_col_def(
        "建单数量", ["order_create_sku_num", "order_create_toal_num"], suffix=["种", "件"],
    ),
    "定价数量": _download_col_def(
        "定价数量", ["quote_create_sku_num", "quote_create_toal_num"], suffix=["种", "件"],
    ),
    "销售员": _download_col_def("销售员", "sales_user_name"),
    "当前执行人": _download_col_def("当前执行人", "execute_user_name"),
    "创建时间": _download_col_def("创建时间", "create_time"),
    "实际出库": _download_col_def("实际出库", "actual_ship_date"),
    "实际出库时间": _download_col_def("实际出库时间", "actual_ship_date"),
    "预计回款": _download_col_def("预计回款", "expected_payment_date"),
    "预计回款日期": _download_col_def("预计回款日期", "expected_payment_date"),
    "实际回款": _download_col_def("实际回款", "actual_payment_date"),
    "实际回款日期": _download_col_def("实际回款日期", "actual_payment_date"),
    "备注": _download_col_def("备注", "remark"),
    "批次号": _download_col_def("批次号", "batch_id"),
    "客户侧订单号": _download_col_def("客户侧订单号", "customer_po_no"),
    "创建来源": _download_col_def("创建来源", "create_source_str"),
    "合作方式": _download_col_def("合作方式", "cooperation_method_str"),
}


def _normalize_download_header_label(head: Any) -> str:
    if isinstance(head, str):
        return head.strip()
    if isinstance(head, dict):
        for key in ("label", "value", "name", "title"):
            text = head.get(key)
            if text is not None and str(text).strip():
                return str(text).strip()
    if head is not None:
        return str(head).strip()
    return ""


def flatten_table_key_group(
    table_key_group: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    递归展开 table_key_group，按列 label 建立索引。

    子项 label 为空且分组仅一列时用分组 label；多列分组中无 label 的 tags 列跳过（走 overrides）。
    """
    flat: Dict[str, Dict[str, Any]] = {}
    for group in table_key_group or []:
        if not isinstance(group, dict):
            continue
        group_label = (group.get("label") or "").strip()
        is_detail = group.get("flag") == "detail"
        items = group.get("value") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            sub_label = (item.get("label") or "").strip()
            fields = list(item.get("value") or [])
            if sub_label:
                col_label = sub_label
            elif len(items) == 1:
                col_label = group_label
            elif fields == ["tags"]:
                continue
            elif len(fields) == 1:
                col_label = group_label
            else:
                continue
            if not col_label:
                continue
            col_def = {
                "label": col_label,
                "value": fields,
                "join": item.get("join") or "",
                "suffix": list(item.get("suffix") or []),
                "allTags": item.get("allTags"),
                "is_detail": is_detail,
            }
            flat[col_label] = col_def
            if len(fields) == 1 and isinstance(fields[0], str):
                flat.setdefault(fields[0], col_def)
    return flat


def _lookup_download_column(
    flat_map: Dict[str, Dict[str, Any]], label: str,
) -> Optional[Dict[str, Any]]:
    if not label:
        return None
    if label in flat_map:
        return dict(flat_map[label])
    if label.endswith("进行中"):
        short = label[:-3].strip()
        if short in flat_map:
            return dict(flat_map[short])
        if short in DOWNLOAD_EXPORT_LABEL_OVERRIDES:
            return dict(DOWNLOAD_EXPORT_LABEL_OVERRIDES[short])
    if label in DOWNLOAD_EXPORT_LABEL_OVERRIDES:
        return dict(DOWNLOAD_EXPORT_LABEL_OVERRIDES[label])
    return None


def resolve_download_columns(
    download_headers: List[Any],
    table_key_group: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """按 download_headers（字符串或 {label,value}）在 table_key_group 中匹配列定义。"""
    flat_map = flatten_table_key_group(table_key_group)
    columns: List[Dict[str, Any]] = []
    for head in download_headers or []:
        lab = _normalize_download_header_label(head)
        if not lab:
            continue
        col = _lookup_download_column(flat_map, lab)
        if col:
            col = dict(col)
            col["label"] = lab
            columns.append(col)
    return columns


def _format_download_cell_value(raw: Any) -> str:
    if raw is None or raw == "":
        return ""
    if isinstance(raw, datetime.datetime):
        return raw.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(raw, datetime.date):
        return raw.isoformat()
    if isinstance(raw, list):
        return ", ".join(str(x) for x in raw if x is not None and x != "")
    return str(raw)


def extract_download_column_value(
    row: Dict[str, Any], col_def: Dict[str, Any],
) -> str:
    """按 table_key_group 列定义从行数据取值（含 join / suffix / tags 过滤）。"""
    fields = col_def.get("value") or []
    if not fields:
        return ""

    if len(fields) == 1 and fields[0] == "tags":
        all_tags = col_def.get("allTags")
        tags = row.get("tags") or []
        tags_str = row.get("tags_str") or []
        if all_tags:
            bits = {int(x) for x in all_tags}
            picked = []
            for bit, lbl in zip(tags, tags_str):
                try:
                    if int(bit) in bits:
                        picked.append(str(lbl))
                except (TypeError, ValueError):
                    continue
            return ", ".join(picked)
        return ", ".join(str(x) for x in tags_str)

    join_sep = col_def.get("join") or ""
    suffix_list = col_def.get("suffix") or []
    parts: List[str] = []
    for idx, field in enumerate(fields):
        raw = row.get(field)
        if (raw is None or raw == "") and row.get("%s_str" % field) is not None:
            raw = row.get("%s_str" % field)
        text = _format_download_cell_value(raw)
        if text == "" and not suffix_list:
            continue
        if suffix_list and idx < len(suffix_list):
            text = "%s%s" % (text if text else "0", suffix_list[idx])
        parts.append(text)
    if join_sep:
        return join_sep.join(parts)
    if suffix_list:
        return "".join(parts)
    return " ".join(parts)


def _detail_row_to_dict(detail: Any) -> Dict[str, Any]:
    if detail is None:
        return {}
    if isinstance(detail, dict):
        return dict(detail)
    if hasattr(detail, "to_dict"):
        return detail.to_dict()
    if hasattr(detail, "__table__"):
        return {c.name: getattr(detail, c.name, None) for c in detail.__table__.columns}
    return {}


def _detail_row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _detail_row_set(row: Any, key: str, value: Any) -> None:
    if isinstance(row, dict):
        row[key] = value
    else:
        setattr(row, key, value)


def _enrich_download_amount_usd(
    row: Dict[str, Any], exchange_rate_dict: Optional[Dict[str, Any]],
) -> None:
    if not exchange_rate_dict:
        return
    from decimal import Decimal

    from apps.system.distribution_order.distribution_order_tags import lookup_exchange_rate

    currency = (row.get("currency") or "USD").strip().upper() or "USD"
    rate = lookup_exchange_rate(currency, exchange_rate_dict) or Decimal("1")
    if not rate:
        rate = Decimal("1")
    pairs = (
        ("goods_amount_with_vat", "goods_amount_with_vat_usd"),
        ("order_amount_with_vat", "order_amount_with_vat_usd"),
        ("freight_with_vat", "freight_with_vat_usd"),
        ("amount_with_vat", "amount_with_vat_usd"),
    )
    for src, dst in pairs:
        if dst in row and row.get(dst) is not None:
            continue
        val = row.get(src)
        if val is None:
            continue
        try:
            row[dst] = round(Decimal(str(val)) / Decimal(str(rate)), 2)
        except Exception:
            pass


def build_distribution_order_download_rows(
    t_data: List[Dict[str, Any]],
    columns: List[Dict[str, Any]],
    filter_value: Optional[List[Dict[str, Any]]] = None,
    exchange_rate_dict: Optional[Dict[str, Any]] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """组装导出行；含 detail 列时按 order_details 展开。"""
    if not columns:
        return []
    has_detail_col = any(col.get("is_detail") for col in columns)
    extent_cols = get_key_options_from_filter_value(
        filter_value or [],
        is_trans=is_trans,
        translation_dict=translation_dict,
    )
    extent_cols.pop("tags", None)
    excel_rows: List[Dict[str, str]] = []

    for order in t_data or []:
        base = dict(order)
        details = base.pop("order_details", None) or []
        detail_dicts = [_detail_row_to_dict(d) for d in details]
        _enrich_download_amount_usd(base, exchange_rate_dict)

        if has_detail_col and detail_dicts:
            for detail in detail_dicts:
                line = dict(base)
                line.update(detail)
                _enrich_download_amount_usd(line, exchange_rate_dict)
                recursive_translate_data(line, extent_cols)
                row = {
                    col["label"]: extract_download_column_value(line, col)
                    for col in columns
                }
                excel_rows.append(row)
        else:
            row = {
                col["label"]: extract_download_column_value(base, col)
                for col in columns
            }
            excel_rows.append(row)
    return excel_rows


def patch_download_response_headers(
    resp_headers: Dict[str, str], excel_base_name: str,
) -> Dict[str, str]:
    """修正 Content-Disposition，兼容中文、空格等非 ASCII 文件名。"""
    base = (excel_base_name or "download").strip() or "download"
    full_name = "%s_%s.xlsx" % (time_module.strftime("%Y-%m-%d"), base)
    quoted = quote(full_name)
    # filename= 须 latin-1；中文走 RFC 5987 的 filename*
    ascii_name = "%s_download.xlsx" % time_module.strftime("%Y-%m-%d")
    out = {
        k: v for k, v in resp_headers.items()
        if k.lower() != "content-disposition"
    }
    out["content-disposition"] = (
        "attachment; filename=%s; filename*=UTF-8''%s" % (ascii_name, quoted)
    )
    return out


def _list_table_column(label: str, field: str) -> Dict[str, Any]:
    return {"label": label, "value": [{"label": "", "value": [field]}]}


def _patch_batch_dropship_list_config(table_base_data: Dict[str, Any]) -> None:
    """主仓表头 323 未配列时，补批量建单相关列与筛选项。"""
    table_key_group = list(table_base_data.get("table_key_group") or [])
    flat = flatten_table_key_group(table_key_group)
    extra_cols = [
        ("批次号", "batch_id"),
        ("客户侧订单号", "customer_po_no"),
        ("创建来源", "create_source_str"),
        ("合作方式", "cooperation_method_str"),
    ]
    for label, field in extra_cols:
        if field not in flat and label not in flat:
            table_key_group.append(_list_table_column(label, field))
    table_base_data["table_key_group"] = table_key_group

    filter_value = list(table_base_data.get("filter_value") or [])
    keys = {
        item.get("key") for item in filter_value if isinstance(item, dict)
    }
    if "batch_id" not in keys:
        filter_value.append({"key": "batch_id", "title": "批次号"})
    if "create_source" not in keys:
        filter_value.append({
            "key": "create_source",
            "title": "创建来源",
            "options": [
                {"label": "普通", "value": 0},
                {"label": "一件代发批量", "value": 1},
            ],
        })
    if "cooperation_method" not in keys:
        filter_value.append({
            "key": "cooperation_method",
            "title": "合作方式",
            "options": [
                {"label": "批发", "value": 1},
                {"label": "一件代发", "value": 2},
            ],
        })
    table_base_data["filter_value"] = filter_value


async def get_table_config(
    inter_session: AsyncSession, request: Request, is_list=False
) -> Dict[str, Any]:
    """主表(323)+副表(315)表头配置，合并 filter_value（含 log_display、tags 等）。"""

    main_table_base_data = await async_get_one_title_mapping(inter_session, 323)
    sub_table_base_data = await async_get_one_title_mapping(inter_session, 315)

    main_filter_value = main_table_base_data.get("filter_value", [])
    sub_table_base_data = await change_category_tree(request, sub_table_base_data)
    sub_filter_value = sub_table_base_data.get("filter_value", [])
    main_dict = {item["key"]: item for item in main_filter_value}
    sub_dict = {item["key"]: item for item in sub_filter_value}
    merged_dict = {
        **main_dict,
        **{k: v for k, v in sub_dict.items() if k not in main_dict},
    }
    main_table_base_data["filter_value"] = list(merged_dict.values())
    if is_list:
        for item in main_table_base_data["filter_value"]:
            if item["key"] == "status":
                query = select(
                    DistributionOrder.status,
                    func.count().label('cnt')
                ).group_by(DistributionOrder.status)
                results = (await inter_session.execute(query)).all()
                status_count_map = {row.status: row.cnt for row in results}
                options = item.get("options", [])

                for op in options:
                    value = op.get("value")
                    op["number"] =  status_count_map.get(value, 0)

    _patch_batch_dropship_list_config(main_table_base_data)
    return main_table_base_data


async def _add_exchange_rate(request, table_base_data):
    filter_value = table_base_data.get("filter_value", [])
    exchange_rate_dict = await get_common_finance_exchange_rate_dict(request)

    options = []
    for currency, usd_rate in exchange_rate_dict.items():
        options.append({"label": currency, "value": usd_rate})

    item = {"key": "cny_exchage_rate", "title": "CNY汇率", "options": options}
    filter_value.append(item)
    table_base_data["filter_value"] = filter_value
    return table_base_data


async def _resolve_step_operator_display(
    session: AsyncSession,
    order: DistributionOrder,
    country: str,
    chain_code: int,
    step: Any,
) -> Optional[str]:
    """按环节配置解析待审/驳回展示人：直线上级用 lm_user_id；办事角色查该国+role_id 权限。"""
    if not should_include_approval_step(order, step, chain_code):
        return None
    step_no = int(step.step_no or 0)
    if int(step.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER:
        mgr_id = line_manager_user_id_for_chain(order, chain_code)
        if mgr_id is None:
            return None
        return await _resolve_operator_name(session, mgr_id) or None
    approval_map = await get_approval_users(
        session, country, chain_code, int(step.role_id),
    )
    user_name = (approval_map.get((step_no, country)) or "").strip()
    return user_name or None


async def _get_previous_role_step(
    session: AsyncSession,
    order: DistributionOrder,
    country: str,
    chain_code: int,
    current_step: int,
) -> List[tuple]:
    """当前环节之前各步的审批人（逐步按 approver_type 解析，非统一按 step_no）。"""
    steps_raw = await _load_approval_steps(session, chain_code)
    result: List[tuple] = []
    for step in steps_raw:
        step_no = int(step.step_no or 0)
        if step_no >= int(current_step):
            continue
        role_label = (step.role_name or "").strip() or "直线上级"
        user_name = await _resolve_step_operator_display(
            session, order, country, chain_code, step,
        )
        if not user_name:
            continue
        result.append((user_name, role_label, step_no))
    return result


async def _load_order_payment_extents(
    session: AsyncSession, order_id: int,
) -> Tuple[
    Optional[DistributionOrderPrepayment],
    Optional[DistributionOrderBalancePayment],
    List[DistributionOrderAdjustment],
]:
    """预付/尾款确认（uk_order_id 一单一条）+ 调整单列表。"""
    prepay_res, balance_res, adj_res = await asyncio.gather(
        session.execute(
            select(DistributionOrderPrepayment).where(
                DistributionOrderPrepayment.order_id == order_id,
            )
        ),
        session.execute(
            select(DistributionOrderBalancePayment).where(
                DistributionOrderBalancePayment.order_id == order_id,
            )
        ),
        session.execute(
            select(DistributionOrderAdjustment).where(
                DistributionOrderAdjustment.order_id == order_id,
            ).order_by(
                DistributionOrderAdjustment.seq.asc(),
                DistributionOrderAdjustment._id.asc(),
            )
        ),
    )
    return (
        prepay_res.scalar_one_or_none(),
        balance_res.scalar_one_or_none(),
        adj_res.scalars().all(),
    )


def _attach_payment_extents(
    data: Dict[str, Any],
    prepay_row: Optional[DistributionOrderPrepayment],
    balance_row: Optional[DistributionOrderBalancePayment],
    adjustments: List[DistributionOrderAdjustment],
    *,
    with_amounts: bool = False,
) -> None:
    data["prepay_detail"] = prepay_row or {}
    data["balance_detail"] = balance_row or {}
    data["adjuctment_details"] = adjustments
    if not with_amounts:
        return
    actual_prepay = prepay_row.amount_paid if prepay_row is not None else None
    balance_amount = balance_row.amount_paid if balance_row is not None else None
    data["actual_prepay_amount"] = actual_prepay
    data["balance_pay_amount"] = balance_amount
    paid_parts = []
    if actual_prepay is not None:
        paid_parts.append(actual_prepay)
    if balance_amount is not None:
        paid_parts.append(balance_amount)
    data["actual_paid_amount"] = sum(paid_parts) if paid_parts else None


def _summarize_order_item_details(
    order_details: List[DistributionOrderItemDetail],
) -> Dict[str, int]:
    order_create_sku_num = 0
    order_create_toal_num = 0
    receive_sku_num = 0
    receive_toal_num = 0
    for row in order_details:
        if row.sku:
            order_create_sku_num += 1
        order_create_toal_num += row.qty or 0
        received_qty = row.received_qty
        if received_qty:
            receive_toal_num += received_qty
            receive_sku_num += 1
    return {
        "order_create_sku_num": order_create_sku_num,
        "order_create_toal_num": order_create_toal_num,
        "receive_sku_num": receive_sku_num,
        "receive_toal_num": receive_toal_num,
    }


def _summarize_quote_details(
    quote_details: List[DistributionOrderQuoteDetail],
) -> Dict[str, int]:
    quote_create_sku_num = 0
    quote_create_toal_num = 0
    for row in quote_details:
        if row.sku:
            quote_create_sku_num += 1
        quote_create_toal_num += row.qty or 0
    return {
        "quote_create_sku_num": quote_create_sku_num,
        "quote_create_toal_num": quote_create_toal_num,
    }


def _format_extent_datetime(value: Any) -> Optional[str]:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


async def _creator_display_name(
    session: AsyncSession, create_by: Optional[int],
) -> Optional[str]:
    if create_by is None:
        return None
    if int(create_by) == 0:
        return "System"
    users = await UserService.get_users_by_ids(session, [int(create_by)])
    return users[0].name if users else None


async def _build_reject_to_info(
    session: AsyncSession,
    request: Request,
    *,
    order: DistributionOrder,
    country: str,
    chain_code: int,
    current_step: int,
    create_by: Optional[int],
    submit_by: Optional[int],
    draft_status: int,
    review_status: int,
) -> List[Dict[str, Any]]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    effective_user_id = submit_by if submit_by else create_by
    operator_name = await _creator_display_name(session, effective_user_id)
    if submit_by:
        submitter_label = (
            translation_dict.get("发起人", "发起人") if is_trans else "发起人"
        )
    else:
        submitter_label = (
            translation_dict.get("创建人", "创建人") if is_trans else "创建人"
        )
    reject_to_info: List[Dict[str, Any]] = [
        {
            "role": submitter_label,
            "operator_role": OPERATOR_CREATOR,
            "name": operator_name,
            "to_status": draft_status,
            "to_step_no": None,
        },
    ]
    steps_raw = await _load_approval_steps(session, chain_code)
    cur_cfg = _find_approval_step_by_no(steps_raw, int(current_step or 0))
    # 当前在直线上级环节：仅可驳回到发起人（不按 step_no 硬编码）
    if (
        cur_cfg is not None
        and int(cur_cfg.approver_type or 0) == APPROVER_TYPE_LINE_MANAGER
    ):
        return reject_to_info
    previous_roles = await _get_previous_role_step(
        session, order, country, chain_code, int(current_step),
    )
    for user_name, business_role, step_no in previous_roles:
        role_label = (
            translation_dict.get(business_role, business_role)
            if is_trans else business_role
        )
        reject_to_info.append({
            "role": role_label,
            "operator_role": OPERATOR_APPROVER,
            "name": user_name,
            "to_status": review_status,
            "to_step_no": int(step_no),
        })
    return reject_to_info


def _filter_review_buttons(
    button_list: List[str],
    review_key: str,
    has_permission: bool,
) -> List[str]:
    if has_permission:
        return list(button_list)
    return [b for b in button_list if b != review_key]


def _tag_label_map(filter_value: List[Dict[str, Any]]) -> Dict[Any, Any]:
    """表头 tags 筛选项优先，否则回落 constants.TAG_LABELS。"""
    cols = get_key_options_from_filter_value(filter_value, {"tags"})
    tag_map = cols.get("tags")
    if tag_map:
        return tag_map
    return dict(TAG_LABELS)


async def attach_tags_extent_data(
    session: AsyncSession,
    request: Request,
    data: Dict[str, Any],
    filter_value: List[Dict[str, Any]],
    *,
    order: Optional[DistributionOrder] = None,
    refresh: bool = True,
) -> None:
    """详情扩展：重算位图并填充 tags / tags_str（支持 filter_value 与翻译）。"""
    order_id = int(data.get("_id") or data.get("id") or 0)
    if not order_id:
        data.setdefault("tags", [])
        data.setdefault("tags_str", [])
        return

    if refresh:
        exchange_rate_dict = await get_common_exchange_rate_dict(request)
        mask = await refresh_order_tags(
            session, order_id, order=order,
            exchange_rate_dict=exchange_rate_dict,
        )
        data["tags_bitmask"] = mask
    elif order is not None:
        data["tags_bitmask"] = order.tags_bitmask
    else:
        data.setdefault("tags_bitmask", data.get("tags_bitmask"))

    bits = decode_tags(data.get("tags_bitmask"))
    data["tags"] = bits
    tag_map = _tag_label_map(filter_value)
    labels = []
    for bit in bits:
        label = tag_map.get(bit)
        if label is None:
            label = tag_map.get(int(bit))
        if label is None:
            label = TAG_LABELS.get(int(bit), str(bit))
        labels.append(label)
    data["tags_str"] = labels

    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, ["offline_customer", "common", "msg"],
    )
    if is_trans and labels:
        data["tags_str"] = [
            translation_dict.get(lbl, lbl) for lbl in labels
        ]


async def format_order_extent_data(
    request: Request,
    session: AsyncSession,
    data: Dict[str, Any],
    filter_value: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """对齐合同 _format_contract_extent_data：_str 映射、reject_to_info、按钮列表。"""
    if not data:
        return {}
    # 审批/权限用客户国家；勿写入 data["country"]（快照地址国家，会被污染）
    country = data.get("customer_country") or await get_customer_country(
        session, data.get("offline_customer_id"),
    )
    status = int(data.get("status") or 0)
    button_list = list(STATUS_BUTTON_LIST.get(status, []))
    order_id = int(data.get("_id") or data.get("id") or 0)
    user_id = getattr(getattr(request, "user", None), "id", None)
    order = await _load_order(session, order_id) if order_id else None
    has_approve_permission = False
    review_chain_code: Optional[int] = None
    review_step_no = 0
    if status == STATUS_QUOTE_REVIEW and order is not None:
        review_chain_code = int(order.current_chain_code or CHAIN_PRICING)
        review_step_no = int(order.current_step or data.get("current_step") or 0)
    elif status == STATUS_ORDER_REVIEW and order is not None:
        review_chain_code = int(
            order.current_chain_code or data.get("current_chain_code") or 0,
        ) or None
        review_step_no = int(order.current_step or data.get("current_step") or 0)
    if (
        order is not None
        and user_id is not None
        and country
        and review_chain_code
        and review_step_no > 0
    ):
        has_approve_permission = await user_can_review_at_step(
            session,
            order,
            int(user_id),
            country=country,
            chain_code=review_chain_code,
            current_step=review_step_no,
        )
    data["has_approve_permission"] = has_approve_permission

    sales_uid = data.get("sales_user_id")
    if sales_uid:
        data["sales_user_name"] = await _creator_display_name(session, int(sales_uid))
    else:
        data["sales_user_name"] = None

    owner_staff_id = data.get("owner_staff_id")
    if owner_staff_id is not None:
        data["owner_staff_name"] = await _creator_display_name(session, int(owner_staff_id))
    else:
        data["owner_staff_name"] = None

    if status == STATUS_QUOTE_REVIEW and country and order is not None:
        step_no = int(order.current_step or data.get("current_step") or 0)
        data["reject_to_info"] = await _build_reject_to_info(
            session, request,
            order=order,
            country=country,
            chain_code=CHAIN_PRICING,
            current_step=step_no,
            create_by=data.get("create_by"),
            submit_by=getattr(order, "submit_by", None) or data.get("submit_by"),
            draft_status=STATUS_DRAFT,
            review_status=STATUS_QUOTE_REVIEW,
        )
        button_list = _filter_review_buttons(
            button_list, "quote_review", has_approve_permission,
        )
    elif status == STATUS_ORDER_REVIEW and country and order is not None:
        chain_code = int(
            order.current_chain_code or data.get("current_chain_code") or 0,
        )
        step_no = int(order.current_step or data.get("current_step") or 0)
        if chain_code:
            data["reject_to_info"] = await _build_reject_to_info(
                session, request,
                order=order,
                country=country,
                chain_code=chain_code,
                current_step=step_no,
                create_by=data.get("create_by"),
                submit_by=getattr(order, "submit_by", None) or data.get("submit_by"),
                draft_status=STATUS_ORDER_CREATE,
                review_status=STATUS_ORDER_REVIEW,
            )
        else:
            data.setdefault("reject_to_info", [])
        button_list = _filter_review_buttons(
            button_list, "order_review", has_approve_permission,
        )
    else:
        data.setdefault("reject_to_info", [])

    data["button_list"] = button_list
    await attach_tags_extent_data(
        session, request, data, filter_value, order=order,
    )
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _PATH_LABEL_TRANSLATION_MODULES,
    )
    extent_cols = get_key_options_from_filter_value(
        filter_value, is_trans=is_trans, translation_dict=translation_dict,
    )
    extent_cols.pop("tags", None)
    recursive_translate_data(data, extent_cols)
    if order_id:
        prepay_row, balance_row, adjustments = await _load_order_payment_extents(
            session, order_id,
        )
        _attach_payment_extents(data, prepay_row, balance_row, adjustments)
    else:
        _attach_payment_extents(data, None, None, [])
    return data


async def _extent_list_detail_data(request, data, session, filter_value, shop_dict, order, exchange_nation_date_dict):
    _id = data.get("_id")
    order_details = []
    quote_details = []
    mt_delivery_mode = None
    prepay_row = None
    balance_row = None
    adjustments = []
    user_id = request.user.id

    if _id:
        mt_res, order_details_res, quote_details_res, payment_ext = await asyncio.gather(
            session.execute(
                select(DistributionOrderSnapshot.mt_delivery_mode).where(
                    DistributionOrderSnapshot.order_id == _id,
                )
            ),
            session.execute(
                select(DistributionOrderItemDetail).where(
                    DistributionOrderItemDetail.order_id == _id,
                    DistributionOrderItemDetail.is_delete == 0,
                ).order_by(DistributionOrderItemDetail._id.asc())
            ),
            session.execute(
                select(DistributionOrderQuoteDetail).where(
                    DistributionOrderQuoteDetail.order_id == _id,
                    DistributionOrderQuoteDetail.is_delete == 0,
                ).order_by(DistributionOrderQuoteDetail._id.asc())
            ),
            _load_order_payment_extents(session, _id),
        )
        mt_delivery_mode = mt_res.scalar_one_or_none()
        order_details = order_details_res.scalars().all()
        quote_details = quote_details_res.scalars().all()
        prepay_row, balance_row, adjustments = payment_ext

    sales_uid = data.get("sales_user_id")
    owner_staff_id = data.get("owner_staff_id")
    button_list = data.get("button_list")
    customer_country = data.get("customer_country")
    current_chain_code = data.get("current_chain_code")
    current_step =data.get("current_step")
    status = data.get("status")
    currency = data.get("currency")

    has_approve_permission = False
    if (
        user_id is not None
        and customer_country
        and current_chain_code
        and current_step
    ):
        has_approve_permission = await user_can_review_at_step(
            session,
            order,
            int(user_id),
            country=customer_country,
            chain_code=current_chain_code,
            current_step=current_step,
        )


    button_list = _filter_review_buttons(
        button_list, "order_review", has_approve_permission,
    )
    button_list = _filter_review_buttons(
        button_list, "quote_review", has_approve_permission,
    )

    data["button_list"] = button_list

    if sales_uid and owner_staff_id:
        sales_user_name, owner_staff_name = await asyncio.gather(
            _creator_display_name(session, int(sales_uid)),
            _creator_display_name(session, int(owner_staff_id)),
        )
    elif sales_uid:
        sales_user_name = await _creator_display_name(session, int(sales_uid))
        owner_staff_name = None
    elif owner_staff_id:
        sales_user_name = None
        owner_staff_name = await _creator_display_name(session, int(owner_staff_id))
    else:
        sales_user_name = None
        owner_staff_name = None

    shop_id = data.get("shop_id")
    data["create_time"] = _format_extent_datetime(data.get("create_time"))
    data["update_time"] = _format_extent_datetime(data.get("update_time"))
    _attach_payment_extents(
        data, prepay_row, balance_row, adjustments, with_amounts=True,
    )
    data["sales_user_name"] = sales_user_name
    data["owner_staff_name"] = owner_staff_name
    data["mt_delivery_mode"] = mt_delivery_mode
    data["shop_name"] = shop_dict.get(shop_id) if shop_id else None
    data["order_details"] = order_details
    create_time = data.get("create_time")
    create_date = create_time[:10] if create_time else None

    # 当前执行人：与引擎口径一致；审核中用人名 SQL/上级解析，避免 user_dict 缺人出 Unknow
    execute_user_name = None
    if order is not None and int(status or 0) <= 40:
        user_dict = await get_common_user_dict(request)
        execute_user_name = await resolve_current_executor_display_name(
            session, order, user_dict=user_dict,
        )

    data["execute_user_name"] = execute_user_name

    exchange_rate = exchange_nation_date_dict.get((currency, create_date))
    if exchange_rate is None:
        # 如果没有那么往前找，直到找到
        date_obj = datetime.datetime.strptime(create_date, "%Y-%m-%d")
        yesterday_date = (date_obj - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        exchange_rate = exchange_nation_date_dict.get((customer_country, yesterday_date))

    # 算美刀
    exchange_cols = ['goods_amount_with_vat', 'order_amount_with_vat', 'freight_with_vat','actual_paid_amount', 'actual_prepay_amount', 'balance_pay_amount']
    for col in exchange_cols:
        value_usd = None
        value = data.get(col)
        col_usd = col + "_usd"
        if value == 0: value_usd=0
        if value and exchange_rate:
            value_usd = safe_divide_round(value, exchange_rate)
        data[col_usd] = value_usd

    order_details = data.get("order_details", [])

    order_exchange_cols = ['amount_with_vat', 'order_amount_with_vat']
    for item in order_details:
        item.currency = currency
        for col in order_exchange_cols:
            value_usd = None
            value = _detail_row_value(item, col)
            col_usd = col + "_usd"
            if value == 0:
                value_usd = 0
            if value and exchange_rate:
                value_usd = safe_divide_round(value, exchange_rate)
            _detail_row_set(item, col_usd, value_usd)

    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _PATH_LABEL_TRANSLATION_MODULES,
    )
    extent_cols = get_key_options_from_filter_value(
        filter_value, is_trans=is_trans, translation_dict=translation_dict,
    )
    recursive_translate_data(data, extent_cols)

    data.update(_summarize_order_item_details(order_details))
    data.update(_summarize_quote_details(quote_details))
    return data

