# -* coding: utf-8 -*-
"""
# @Time    : 2026/5/9
# @Author  : Zhu Yaming
# @File    : change_diff.py
# @Description : 为了编辑时对比数据记录
"""
from decimal import Decimal
import json
from typing import Any, Callable, Dict, List, Optional, Set, Union, Tuple
from apps.system.reports.view.common_func import get_translaiton_dict_from_request

NormalizerFn = Callable[[str, Any], Any]


def deep_diff_create(
    new_data: Any,
    *,
    path: str = "",
    ignore_keys: Optional[Set[str]] = None,
    ignore_paths: Optional[Set[str]] = None,
    normalizer: Optional[NormalizerFn] = None,
    list_id_key: str = "_id",
) -> Dict[str, Any]:
    """
    创建场景：从 new_data 生成一份可写入日志的快照（去掉审计/主键等默认忽略项）。

    与 deep_diff 使用相同的 ignore_keys / ignore_paths / normalizer / list_id_key
    约定；返回结构为「纯字段树」，叶子为原始值，无 {"old","new"} 包装，
    可直接交给 parse_diff_log(..., op_type='创建')。

    顶层须为 dict；否则返回 {}。值为 None 的字段不写入快照。
    """
    ignore_keys = ignore_keys or {"contract_no", "_id", "create_time", "update_time", "created_by", "updated_by", "create_by", "update_by"}
    ignore_paths = ignore_paths or set()

    def _norm(key: str, val: Any) -> Any:
        return normalizer(key, val) if normalizer else val

    def _snapshot_list(items: List[Any], cur_path: str) -> List[Any]:
        out: List[Any] = []
        if not items:
            return out
        first = items[0]
        if (
            list_id_key
            and isinstance(first, dict)
            and list_id_key in first
        ):
            for item in items:
                if not isinstance(item, dict):
                    continue
                rid = item[list_id_key]
                child_path = f"{cur_path}[{rid}]" if cur_path else f"[{rid}]"
                if child_path in ignore_paths:
                    continue
                snapped = _snapshot(item, child_path)
                if snapped is not None:
                    out.append(snapped)
            return out

        for i, item in enumerate(items):
            child_path = f"{cur_path}[{i}]" if cur_path else f"[{i}]"
            if child_path in ignore_paths:
                continue
            snapped = _snapshot(item, child_path)
            if snapped is not None:
                out.append(snapped)
        return out

    def _snapshot(node: Any, cur_path: str) -> Any:
        if node is None:
            return None
        if isinstance(node, dict):
            out: Dict[str, Any] = {}
            for k, v in node.items():
                if k in ignore_keys:
                    continue
                child_path = f"{cur_path}.{k}" if cur_path else k
                if child_path in ignore_paths:
                    continue
                nv = _norm(k, v)
                if nv is None:
                    continue
                child = _snapshot(nv, child_path)
                if child is None:
                    continue
                out[k] = child
            return out
        if isinstance(node, list):
            return _snapshot_list(node, cur_path)
        return node

    if not isinstance(new_data, dict):
        return {}
    root = _snapshot(new_data, path)
    return root if isinstance(root, dict) else {}


def deep_diff(
    old_data: Any,
    new_data: Any,
    *,
    path: str = "",
    ignore_keys: Optional[Set[str]] = None,
    ignore_paths: Optional[Set[str]] = None,
    normalizer: Optional[NormalizerFn] = None,
    list_id_key: str = "_id",
) -> Dict[str, Any]:
    ignore_keys  = ignore_keys or {"contract_no", "_id", "create_time", "update_time", "created_by", "updated_by", "create_by", "update_by"}
    ignore_paths = ignore_paths or set()

    def _norm(key: str, val: Any) -> Any:
        return normalizer(key, val) if normalizer else val

    def _recurse(old: Any, new: Any, cur_path: str) -> Any:
        # ── dict ────────────────────────────────────────────────────
        if isinstance(old, dict) and isinstance(new, dict):
            result = {}
            for k in new.keys():                          # ← 以 new 的键为准
                if k in ignore_keys:
                    continue
                child_path = f"{cur_path}.{k}" if cur_path else k
                if child_path in ignore_paths:
                    continue

                new_v = _norm(k, new[k])
                old_v = _norm(k, old.get(k))             # old 没有该键时得到 None

                if k not in old:
                    result[k] = {"old": None, "new": new_v}   # new 新增的字段
                else:
                    child = _recurse(old_v, new_v, child_path)
                    if child is not None:
                        result[k] = child
            return result or None

        # ── list ─────────────────────────────────────────────────────
        if isinstance(old, list) and isinstance(new, list):
            return _diff_list(old, new, cur_path)

        # ── 叶子值 ───────────────────────────────────────────────────
        if old != new:
            return {"old": old, "new": new}
        return None

    def _diff_list(old_list: List, new_list: List, cur_path: str) -> Optional[Dict]:
        combined = old_list + new_list
        use_id_matching = (
            list_id_key
            and combined
            and all(isinstance(item, dict) and list_id_key in item for item in combined)
        )

        if use_id_matching:
            old_map = {item[list_id_key]: item for item in old_list}
            new_map = {item[list_id_key]: item for item in new_list}

            result = {}
            for rid in new_map.keys():                    # ← 同理，以 new 的 id 为准
                child_path = f"{cur_path}[{rid}]"
                if child_path in ignore_paths:
                    continue
                if rid not in old_map:
                    result[str(rid)] = {"old": None, "new": new_map[rid]}
                else:
                    child = _recurse(old_map[rid], new_map[rid], child_path)
                    if child:
                        result[str(rid)] = child

            return result or None

        if old_list != new_list:
            return {"old": old_list, "new": new_list}
        return None

    result = _recurse(old_data, new_data, path)
    return result if isinstance(result, dict) else {}


FieldConfig = Union[str, Dict[str, Any]]
SchemaDict  = Dict[str, FieldConfig]


def _resolve_field(config: FieldConfig) -> Tuple[str, Optional[Dict]]:
    """解析字段配置，返回 (label, value_map)"""
    if isinstance(config, str):
        return config, None
    label     = config.get("label", "")
    value_map = config.get("values")
    return label, value_map


def _display_val(val: Any, value_map: Optional[Dict]) -> Any:
    """把原始值转成展示值"""
    if val is None:
        return None
    if value_map:
        return value_map.get(val, val)   # 找不到映射就原样返回
    return val


def _is_list_diff(val, node, key, parent_schema, list_item_schema) -> bool:
    """判断这个节点是 list diff（子 key 是 id，值是 dict）"""
    if not isinstance(val, dict):
        return False
    if "old" in val or "new" in val:
        return False
    return key in list_item_schema or all(
        isinstance(v, dict) for v in val.values()
    )


def _get_item_tag(item: Any, sub_schema: SchemaDict) -> str:
    """从 list 元素中提取用于展示的标识（优先用 name/title 等字段）"""
    if not isinstance(item, dict):
        return str(item)
    for candidate in ("name", "title", "label", "code"):
        if candidate in item:
            return str(item[candidate])
    # 找 sub_schema 里第一个有值的字段
    for k in sub_schema:
        if k in item:
            return str(item[k])
    return str(next(iter(item.values()), ""))


def _extract_child_schema(key: str, parent_schema: SchemaDict) -> SchemaDict:
    """从父 schema 中提取嵌套 dict 的子 schema"""
    config = parent_schema.get(key)
    if isinstance(config, dict):
        return config.get("fields", {})
    return {}


def translate_tree_data(data, trans_dict):
    """递归遍历字典，翻译所有的 value"""
    for k, v in data.items():
        if isinstance(v, dict):
            translate_tree_data(v, trans_dict)
        elif isinstance(v, str):
            data[k] = trans_dict.get(v, v)


def _is_create_op(op_type: str) -> bool:
    t = (op_type or "").strip().lower()
    return t in ("创建", "create", "新建", "新增")


def parse_diff_log(
    diff: Dict[str, Any],
    schema: Optional[SchemaDict] = None,
    *,
    arrow: str = " → ",
    unknown_label: Optional[str] = None,  # None=用字段名, ""=跳过
    key_value_dict: Optional[Dict[str, Any]] = None,
    ignore_keys: Optional[set] = None,
    user_name: str = "",
    op_type: str = "",
    request: Any = None,
):
    """
    op_type 可能是创建、更新。更新走 deep_diff 形态；创建为扁平字段值，只记录当前值。
    更新示例： {"status": {"old": 1, "new": 2}, "name": {"old": "1", "new": "2"}, ...}
    创建示例： {"status": 1, "name": "a", "info": [{}, ...]}
    """
    result: Dict[str, str] = {}
    schema = schema or {}
    key_value_dict = key_value_dict or {}
    is_trans,translation_dict = get_translaiton_dict_from_request(request, ['message', 'common', 'common_filters'])
    if is_trans:
        for k, v in schema.items():
            schema[k] = translation_dict.get(v, v)

        for k, v in key_value_dict.items():
            if isinstance(v, dict):
                translate_tree_data(v, translation_dict)

    def _render_value(
            val: Any,
            value_map: Optional[Dict],
            schema_node: SchemaDict,
            ignore_keys: Optional[set] = None,
            flat_schema: Optional[SchemaDict] = None,  # ← 新增：顶层扁平 schema 兜底
    ) -> Any:
        ignore_keys = ignore_keys or {}
        flat_schema = flat_schema or {}

        if isinstance(val, list):
            return [
                _render_value(item, value_map, schema_node, ignore_keys, flat_schema)
                for item in val
            ]

        if isinstance(val, dict):
            rendered = {}
            for k, v in val.items():
                if k in ignore_keys:
                    continue
                # 优先查当前层 schema_node，找不到再查顶层扁平 schema
                config = schema_node.get(k) or flat_schema.get(k)
                if config is None:
                    label = _fallback_label(k, "")
                    if label is None:
                        continue
                    child_schema = {}
                    child_value_map = None
                elif isinstance(config, str):
                    # 扁平 schema：值直接是 label 字符串
                    label = config
                    child_schema = {}
                    child_value_map = None
                else:
                    label, child_value_map = _resolve_field(config)
                    child_schema = config.get("fields", {})

                rendered[label] = _render_value(v, child_value_map, child_schema, ignore_keys, flat_schema)
            return rendered

        if value_map:
            return value_map.get(val, val)
        return val

    def _render_list_item(item: Dict, ignore_keys: Optional[set] = None) -> Dict:
        """渲染列表中单个 dict 元素，查 schema + key_value_dict"""
        ignore_keys = ignore_keys or set()
        rendered_item = {}
        for fk, fv in item.items():
            if fk in ignore_keys:
                continue
            fconfig = schema.get(fk)
            if fconfig is None:
                flabel = _fallback_label(fk, "")
                if flabel is None:
                    continue
                # 无 schema 配置，查 key_value_dict
                if fk in key_value_dict:
                    kv = key_value_dict[fk]
                    fv = kv.get(fv, fv) if isinstance(kv, dict) else fv
                rendered_item[flabel] = str(fv) if not isinstance(fv, (dict, list)) else json.dumps(fv, ensure_ascii=False, default=str)
            elif isinstance(fconfig, str):
                # 扁平 schema，值直接是 label 字符串
                if fk in key_value_dict:
                    kv = key_value_dict[fk]
                    fv = kv.get(fv, fv) if isinstance(kv, dict) else fv
                rendered_item[fconfig] = str(fv) if not isinstance(fv, (dict, list)) else json.dumps(fv, ensure_ascii=False, default=str)
            else:
                flabel, fvalue_map = _resolve_field(fconfig)
                # fvalue_map 优先，没有再查 key_value_dict
                if fvalue_map is None and fk in key_value_dict:
                    kv = key_value_dict[fk]
                    fv = kv.get(fv, fv) if isinstance(kv, dict) else fv
                    rendered_item[flabel] = str(fv) if not isinstance(fv, (dict, list)) else json.dumps(fv, ensure_ascii=False, default=str)
                else:
                    rendered_item[flabel] = _format_create_value(fk, fv, fvalue_map)
        return rendered_item

    def _change(dkey, old, new, value_map=None, field_schema=None, ignore_keys=None, flat_schema=None) -> str:
        field_schema = field_schema or {}
        ignore_keys = ignore_keys or set()
        flat_schema = flat_schema or {}

        def _render(val):
            # 列表：每个元素走新建渲染逻辑
            if isinstance(val, list):
                if val and isinstance(val[0], dict):
                    return json.dumps(
                        [_render_list_item(item, ignore_keys) for item in val],
                        ensure_ascii=False, default=str
                    )
                else:
                    return val  # 普通标量列表，直接保留

            # 标量：查 key_value_dict
            if dkey in key_value_dict and not isinstance(val, dict):
                kv = key_value_dict[dkey]
                return kv.get(val, val) if isinstance(kv, dict) else val

            # dict 或其他：走 _render_value
            return _render_value(val, value_map, field_schema, ignore_keys, flat_schema)

        old = _render(old)
        new = _render(new)

        def _serialize(v):
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, default=str)
            return str(v)

        return f"{_serialize(old)}{arrow}{_serialize(new)}"

    def _display(val: Any, value_map: Optional[Dict]) -> Any:
        if val is None or not value_map:
            return val
        return value_map.get(val, val)

    def _fallback_label(key: str, prefix: str) -> Optional[str]:
        """schema 里找不到字段时的兜底 label，返回 None 表示跳过"""
        if unknown_label is None:
            return f"{prefix}{key}"   # 用字段名原值
        if unknown_label == "":
            return None               # 跳过
        return f"{prefix}{unknown_label}{key}"

    def _format_create_value(key: str, val: Any, value_map: Optional[Dict]) -> str:
        disp: Any = _display(val, value_map)
        if key in key_value_dict:
            kv = key_value_dict[key]
            if isinstance(kv, dict):
                disp = kv.get(disp, disp)
        if isinstance(disp, (dict, list)):
            return json.dumps(disp, ensure_ascii=False, default=str)
        return str(disp)

    def _walk_create(node: Dict[str, Any], parent_schema: SchemaDict, prefix: str = "") -> None:
        for key, val in node.items():
            # ① old/new 格式（混入创建数据里的更新格式）
            if isinstance(val, dict) and "old" in val and "new" in val:
                config = parent_schema.get(key)
                if config is None:
                    label = _fallback_label(key, prefix)
                    if label is None:
                        continue
                    result[label] = _change(key, val["old"], val["new"])
                    continue
                label, value_map = _resolve_field(config)
                result[f"{prefix}{label}"] = _change(
                    key,
                    _display(val["old"], value_map),
                    _display(val["new"], value_map),
                )
                continue

            # ② 嵌套 dict：递归向下
            if isinstance(val, dict):
                config = parent_schema.get(key)
                child_schema = config.get("fields", {}) if isinstance(config, dict) else {}
                child_label = _resolve_field(config)[0] if config else key
                _walk_create(val, child_schema, prefix=f"{prefix}{child_label}.")
                continue

            if isinstance(val, list):
                config = parent_schema.get(key)
                if config is None:
                    label = _fallback_label(key, prefix)
                    if label is None:
                        continue
                    value_map = None
                else:
                    label, value_map = _resolve_field(config)

                full_label = f"{prefix}{label}"

                # 列表元素是 dict → 逐条用顶层平铺 schema 渲染
                if val and isinstance(val[0], dict):
                    rendered_items = []
                    for item in val:
                        rendered_item = {}
                        for fk, fv in item.items():
                            # 直接查顶层平铺 schema
                            fconfig = schema.get(fk)  # ← 用顶层 schema
                            if fconfig is None:
                                flabel = _fallback_label(fk, "")
                                if flabel is None:
                                    continue
                                rendered_item[flabel] = _format_create_value(fk, fv, None)
                            elif isinstance(fconfig, str):
                                # 平铺 schema，值直接是 label 字符串
                                rendered_item[fconfig] = _format_create_value(fk, fv, None)
                            else:
                                flabel, fvalue_map = _resolve_field(fconfig)
                                rendered_item[flabel] = _format_create_value(fk, fv, fvalue_map)
                        rendered_items.append(rendered_item)
                    result[full_label] = json.dumps(rendered_items, ensure_ascii=False, default=str)
                else:
                    # 普通列表（字符串、数字等），直接序列化
                    result[full_label] = _format_create_value(key, val, value_map)
                continue

            # ④ 标量
            config = parent_schema.get(key)
            if config is None:
                label = _fallback_label(key, prefix)
                if label is None:
                    continue
                result[label] = _format_create_value(key, val, None)
                continue

            label, value_map = _resolve_field(config)
            result[f"{prefix}{label}"] = _format_create_value(key, val, value_map)

    def _walk(node, parent_schema, prefix="", ignore_keys=None):
        ignore_keys = ignore_keys or set()
        for key, val in node.items():
            if isinstance(val, dict) and "old" in val and "new" in val:
                config = parent_schema.get(key)
                if config is None:
                    label = _fallback_label(key, prefix)
                    if label is None:
                        continue
                    result[label] = _change(key, val["old"], val["new"], ignore_keys=ignore_keys, flat_schema=schema)  # ← 传 schema
                    continue

                label, value_map = _resolve_field(config)
                field_schema = config.get("fields", {}) if isinstance(config, dict) else {}
                result[f"{prefix}{label}"] = _change(
                    key, val["old"], val["new"],
                    value_map=value_map,
                    field_schema=field_schema,
                    ignore_keys=ignore_keys,
                    flat_schema=schema,  # ← 传 schema
                )
            elif isinstance(val, dict):
                config = parent_schema.get(key)
                child_schema = config.get("fields", {}) if isinstance(config, dict) else {}
                child_label = _resolve_field(config)[0] if config else key
                _walk(val, child_schema, prefix=f"{prefix}{child_label}.", ignore_keys=ignore_keys)

    if _is_create_op(op_type):
        _walk_create(diff, schema)
    else:
        _walk(diff, schema, ignore_keys=ignore_keys)

    if is_trans: op_type = translation_dict.get(op_type, op_type)
    content = user_name + " " + op_type + " 【"
    for key, val in result.items():
        content += f"{key}: {str(val)}; "

    if result:
        content = content.rstrip("; ") + "."
    content += "】"
    return content


