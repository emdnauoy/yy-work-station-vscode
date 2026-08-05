# -*- coding: utf-8 -*-
"""
# @Time    : 2026/6/4
# @Author  : Zhu Yaming
# @File    : log_parse.py
# @Description : 通用结构化 diff/快照 日志 title 解析（递归 dict/list/old-new）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from apps.system.distribution_order.operation_log import (
    DISTRIBUTION_ORDER_LOG_IGNORE_KEYS,
    normalize_log_payload,
)

try:
    from apps.system.reports.view.common_func import get_translaiton_dict_from_request
except ImportError:
    def get_translaiton_dict_from_request(request, modules):
        return False, {}

ValueFormatter = Callable[[str, Any], Any]

@dataclass
class LogParseOptions:
    """扁平 field_key→展示名；递归处理 dict / list[dict] / {old,new}。"""
    field_labels: Dict[Any, str] = field(default_factory=dict)
    field_label_fallback: Dict[str, str] = field(default_factory=dict)
    key_value_dict: Dict[str, Any] = field(default_factory=dict)
    ignore_keys: Set[str] = field(default_factory=lambda: set(DISTRIBUTION_ORDER_LOG_IGNORE_KEYS))
    arrow: str = " → "
    pair_sep: str = ", "
    list_item_sep: str = "; "
    part_sep: str = "; "
    unknown_field: str = "key"  # key | skip
    list_id_key: str = "_id"
    translate_modules: Optional[List[str]] = None
    value_formatters: Dict[str, ValueFormatter] = field(default_factory=dict)
    is_trans: Optional[bool] = None
    translation_dict: Optional[Dict[Any, Any]] = None


def _is_change_node(val: Any) -> bool:
    return isinstance(val, dict) and "old" in val and "new" in val


def _is_row_change_node(val: Any) -> bool:
    if not _is_change_node(val):
        return False
    old_v, new_v = val.get("old"), val.get("new")
    return isinstance(old_v, dict) or isinstance(new_v, dict)


def _is_scalar_change_node(val: Any) -> bool:
    return _is_change_node(val) and not _is_row_change_node(val)


def _is_list_of_dicts(val: Any) -> bool:
    return isinstance(val, list) and bool(val) and all(isinstance(x, dict) for x in val)


def _is_indexed_row_diff(val: Any) -> bool:
    """deep_diff 列表明细：{"46": {"sku": {old,new}}} 或 {"46": {old,new}}。"""
    if not isinstance(val, dict) or not val:
        return False
    if _is_change_node(val):
        return False
    return all(isinstance(v, dict) for v in val.values())


def _is_create_op(op_type: str) -> bool:
    t = (op_type or "").strip().lower()
    return t in ("创建", "create", "新建", "新增")


def _translate_tree(data: Dict[str, Any], td: Dict[Any, Any]) -> None:
    for k, v in list(data.items()):
        if isinstance(v, dict):
            _translate_tree(v, td)
        elif isinstance(v, str):
            data[k] = td.get(v, v)


class StructuredDiffLogParser:
    """递归解析 operation_details，不绑定具体业务模块名。"""

    def __init__(self, options: Optional[LogParseOptions] = None):
        self.opt = options or LogParseOptions()
        self._labels: Dict[Any, str] = {}
        self._td: Dict[Any, Any] = {}
        self._is_trans = False

    def _prepare(self, request: Any = None) -> None:
        labels = dict(self.opt.field_labels)
        for fk, lb in self.opt.field_label_fallback.items():
            labels.setdefault(fk, lb)
        self._labels = labels
        if self.opt.is_trans is not None and self.opt.translation_dict is not None:
            self._is_trans = bool(self.opt.is_trans)
            self._td = dict(self.opt.translation_dict)
        elif request is not None:
            modules = self.opt.translate_modules or [
                "offline_customer", "common", "common_filters", "msg",
            ]
            self._is_trans, self._td = get_translaiton_dict_from_request(request, modules)
        else:
            self._is_trans = False
            self._td = {}
        if self._is_trans and self._td:
            self._labels = {k: self._td.get(v, v) for k, v in labels.items()}
            kvd = dict(self.opt.key_value_dict)
            for v in kvd.values():
                if isinstance(v, dict):
                    _translate_tree(v, self._td)
            self.opt.key_value_dict = kvd

    def _apply_translation_to_text(self, text: str) -> str:
        """兜底：对拼好的 title 按字典最长匹配替换中文短语（含字段名、标签名）。"""
        if not self._is_trans or not self._td:
            return text
        keys = sorted(
            (k for k in self._td if isinstance(k, str) and k),
            key=len,
            reverse=True,
        )
        out = text
        for cn in keys:
            out = out.replace(cn, self._td[cn])
        return out

    def _t(self, text: str) -> str:
        if not self._is_trans or not self._td:
            return text
        return self._td.get(text, text)

    def _label(self, field_key: Any) -> str:
        fk = str(field_key)
        lb = self._labels.get(field_key, self._labels.get(fk))
        if lb is not None:
            return self._t(str(lb))
        fb = self.opt.field_label_fallback.get(fk)
        if fb:
            return self._t(fb)
        if self.opt.unknown_field == "skip":
            return ""
        if self.opt.unknown_field == "key":
            return fk
        return self._t("%s%s" % (self.opt.unknown_field, fk))

    def _map_scalar(self, field_key: str, val: Any) -> Any:
        if field_key in self.opt.value_formatters:
            return self.opt.value_formatters[field_key](field_key, val)
        if field_key in self.opt.key_value_dict and not isinstance(val, (dict, list)):
            kv = self.opt.key_value_dict[field_key]
            if isinstance(kv, dict):
                return kv.get(val, val)
        if isinstance(val, list) and not _is_list_of_dicts(val):
            return "[%s]" % self.opt.pair_sep.join(
                self._t(str(x)) if isinstance(x, str) else str(x) for x in val
            )
        return val

    def _serialize(self, val: Any) -> str:
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False, default=str)
        return str(val)

    def _format_change(self, field_key: str, old: Any, new: Any) -> str:
        ov = self._map_scalar(field_key, old)
        nv = self._map_scalar(field_key, new)
        return "%s%s%s" % (self._serialize(ov), self.opt.arrow, self._serialize(nv))

    def _format_scalar(self, field_key: str, val: Any) -> str:
        return self._serialize(self._map_scalar(field_key, val))

    def _emit_object_pairs(
        self, obj: Dict[str, Any], parent_field_key: str = "",
    ) -> List[str]:
        """单个 dict（行/嵌套对象）：字段递归展开。"""
        if _is_scalar_change_node(obj):
            lb = self._label(parent_field_key) if parent_field_key else ""
            line = self._format_change(parent_field_key, obj.get("old"), obj.get("new"))
            return ["%s: %s" % (lb, line)] if lb else [line]
        skip = self.opt.ignore_keys
        pairs: List[str] = []
        if _is_row_change_node(obj):
            old_row = obj.get("old") if isinstance(obj.get("old"), dict) else {}
            new_row = obj.get("new") if isinstance(obj.get("new"), dict) else {}
            rid = obj.get(self.opt.list_id_key) or new_row.get(self.opt.list_id_key) or old_row.get(
                self.opt.list_id_key,
            )
            if rid not in (None, "") and self.opt.list_id_key not in skip:
                lb = self._label(self.opt.list_id_key)
                if lb:
                    pairs.append("%s: %s" % (lb, rid))
            for fk in set(old_row.keys()) | set(new_row.keys()):
                if fk in skip:
                    continue
                ov, nv = old_row.get(fk), new_row.get(fk)
                if ov == nv:
                    continue
                lb = self._label(fk)
                if not lb:
                    continue
                pairs.extend(self._emit_field(fk, ov, nv_override=nv, force_change=True))
            return pairs
        for fk, fv in obj.items():
            if fk in skip:
                continue
            pairs.extend(self._emit_field(fk, fv))
        return pairs

    def _emit_field(
        self,
        field_key: str,
        val: Any,
        *,
        nv_override: Any = None,
        force_change: bool = False,
    ) -> List[str]:
        lb = self._label(field_key)
        if not lb:
            return []
        if force_change and nv_override is not None:
            return ["%s: %s" % (lb, self._format_change(field_key, val, nv_override))]
        if _is_change_node(val):
            return ["%s: %s" % (lb, self._format_change(field_key, val.get("old"), val.get("new")))]
        if _is_row_change_node(val):
            inner = self.opt.pair_sep.join(self._emit_object_pairs(val))
            return ["%s: %s" % (lb, inner)] if inner else []
        if _is_list_of_dicts(val):
            return self._emit_list_block(lb, field_key, val)
        if _is_indexed_row_diff(val):
            return self._emit_indexed_block(lb, field_key, val)
        if isinstance(val, dict):
            nested = self._emit_dict_children(val)
            if not nested:
                return []
            inner = self.opt.pair_sep.join(nested)
            return ["%s[%s]" % (lb, inner)]
        if isinstance(val, list):
            return ["%s: %s" % (lb, self._format_scalar(field_key, val))]
        return ["%s: %s" % (lb, self._format_scalar(field_key, val))]

    def _emit_dict_children(self, node: Dict[str, Any]) -> List[str]:
        parts: List[str] = []
        for k, v in node.items():
            if k in self.opt.ignore_keys:
                continue
            parts.extend(self._emit_field(k, v))
        return parts

    def _emit_list_block(self, block_label: str, field_key: str, rows: List[Dict[str, Any]]) -> List[str]:
        segments: List[str] = []
        for row in rows:
            if _is_scalar_change_node(row):
                inner = self._format_change(field_key, row.get("old"), row.get("new"))
            else:
                inner = self.opt.pair_sep.join(self._emit_object_pairs(row, parent_field_key=field_key))
            if inner:
                segments.append(inner)
        if not segments:
            return []
        body = self.opt.list_item_sep.join(segments)
        return ["%s[%s]" % (block_label, body)]

    def _emit_indexed_block(self, block_label: str, field_key: str, indexed: Dict[str, Any]) -> List[str]:
        segments: List[str] = []
        for rid, change in indexed.items():
            row: Dict[str, Any] = {self.opt.list_id_key: int(rid) if str(rid).isdigit() else rid}
            if _is_change_node(change):
                row["old"] = change.get("old")
                row["new"] = change.get("new")
                inner = self.opt.pair_sep.join(self._emit_object_pairs(row))
            elif isinstance(change, dict):
                row.update(change)
                inner = self.opt.pair_sep.join(self._emit_object_pairs(row))
            else:
                inner = self._format_scalar(field_key, change)
            if inner:
                segments.append(inner)
        if not segments:
            return []
        body = self.opt.list_item_sep.join(segments)
        return ["%s[%s]" % (block_label, body)]

    def _emit_root(self, node: Dict[str, Any]) -> List[str]:
        parts: List[str] = []
        for key, val in node.items():
            if key in self.opt.ignore_keys:
                continue
            parts.extend(self._emit_field(key, val))
        return parts

    def parse_title(
        self,
        o_details: Any,
        *,
        user_name: str = "",
        op_type: str = "",
        request: Any = None,
    ) -> str:
        self._prepare(request)
        raw = normalize_log_payload(o_details) if isinstance(o_details, dict) else {}
        parts = self._emit_root(raw) if raw else []
        body = self.opt.part_sep.join(parts)
        if body:
            body += "."
        op = self._t((op_type or "").strip() or ("新建" if _is_create_op(op_type) else "更新"))
        if body:
            title = "%s %s 【%s】" % (user_name, op, body)
        else:
            title = "%s %s 【】" % (user_name, op)
        return self._apply_translation_to_text(title)


# 兼容旧名
DistributionOrderLogParseOptions = LogParseOptions
DistributionOrderLogParser = StructuredDiffLogParser


def parse_structured_log_title(
    o_details: Any,
    field_labels: Optional[Dict[Any, str]] = None,
    *,
    user_name: str = "",
    op_type: str = "",
    ignore_keys: Optional[Set[str]] = None,
    request: Any = None,
    key_value_dict: Optional[Dict[str, Any]] = None,
    is_trans: Optional[bool] = None,
    translation_dict: Optional[Dict[Any, Any]] = None,
    options: Optional[LogParseOptions] = None,
) -> str:
    opt = options or LogParseOptions()
    if field_labels:
        opt.field_labels = field_labels
    if ignore_keys is not None:
        opt.ignore_keys = set(ignore_keys)
    if key_value_dict:
        opt.key_value_dict = key_value_dict
    if is_trans is not None:
        opt.is_trans = is_trans
    if translation_dict is not None:
        opt.translation_dict = translation_dict
    return StructuredDiffLogParser(opt).parse_title(
        o_details, user_name=user_name, op_type=op_type, request=request,
    )


def parse_distribution_order_log_title(
    o_details: Any,
    field_labels: Optional[Dict[Any, str]] = None,
    **kwargs: Any,
) -> str:
    return parse_structured_log_title(o_details, field_labels, **kwargs)


def build_distribution_order_log_title(
    o_details: Any,
    field_labels: Optional[Dict[Any, str]] = None,
    **kwargs: Any,
) -> str:
    return parse_structured_log_title(o_details, field_labels, **kwargs)
