# -*- coding: utf-8 -*-
"""
# @Time    : 2026/7/22
# @Author  : Zhu Yaming
# @File    : distribution_order_line_import_service.py
# @Description : 报价/订单明细 Excel 模板与批量导入
"""
from __future__ import annotations

import ast
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.model.product import DataProductSku
from apps.system.distribution_order.distribution_order_line_service import line_kind_config
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.translate import translate_text

_KIND_QUOTE = "quote"
_KIND_ORDER = "order"

# 模板表头以中文为 canonical，导出时按请求语言 translate_text
QUOTE_TEMPLATE_HEADERS: Tuple[str, ...] = ("SKU编码", "含增值税单价")
ORDER_TEMPLATE_HEADERS: Tuple[str, ...] = ("SKU编码", "含增值税单价", "数量")

_EXCEL_EXTENSIONS = ("xlsm", "xlsx", "xls")
_MAX_IMPORT_ROWS = 3000

# 字段 → 可识别表头（中文 + 别名）；导入时额外接受当前语言译文
_FIELD_CN_LABELS: Dict[str, Tuple[str, ...]] = {
    "sku": ("SKU编码", "SKU", "sku"),
    "price_with_vat": ("含增值税单价", "含增值税报价"),
    "qty": ("数量", "销售数量"),
}


def _import_msg(
    key: str,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> str:
    """导入校验文案：先翻译模板，再 format 占位符。"""
    td = translation_dict or {}
    text = translate_text(key, is_trans, td) or key
    if kwargs:
        return text.format(**kwargs)
    return text


def _import_more_suffix(
    total: int, limit: int, is_trans: bool, translation_dict: Optional[Dict[str, Any]],
) -> str:
    if total <= limit:
        return ""
    more = _import_msg("等", is_trans, translation_dict)
    return (" " + more) if more else ""


def _import_template_filenames(
    kind: str,
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """
    导入模板文件名：(展示名, latin-1 兼容的 ASCII 备用名)。
    展示名走 translate_text；译文可能含空格，须配合 build_template_content_disposition
    用 filename* 百分号编码，避免 Content-Disposition 在空格处截断。
    """
    ts = datetime.now().strftime("%Y%m%d%H%M")
    td = translation_dict or {}
    if kind == _KIND_QUOTE:
        name_cn = "报价单导出模板"
        ascii_name = "quote_export_template_%s.xlsx" % ts
    elif kind == _KIND_ORDER:
        name_cn = "订单明细导出模板"
        ascii_name = "order_detail_export_template_%s.xlsx" % ts
    else:
        raise DistributionOrderError(40000, "明细类型无效")
    # 多语言：翻译后规整空白（含 NBSP），避免头尾空格或连续空格导致显示异常
    name_base = translate_text(name_cn, is_trans, td) or name_cn
    name_base = " ".join(str(name_base).replace("\u00a0", " ").split())
    if not name_base:
        name_base = name_cn
    display_name = "%s%s.xlsx" % (name_base, ts)
    return display_name, ascii_name


def build_template_content_disposition(
    display_name: str, ascii_fallback: Optional[str] = None,
) -> str:
    """
    生成 Content-Disposition。
    - filename*：RFC 5987，放翻译后的完整文件名（空格→%20，防截断）
    - filename：latin-1 备用；译文若已是 ASCII 则用译文（去空格），否则用 ascii_fallback
      （避免仅识别 filename 的客户端一直看到固定英文、表现为「没有多语言」）
    """
    from urllib.parse import quote

    name = (display_name or "import_template.xlsx").replace("\u00a0", " ").strip()
    name = " ".join(name.split()) or "import_template.xlsx"
    fallback = (ascii_fallback or "import_template.xlsx").strip() or "import_template.xlsx"
    fallback = "".join(
        ("_" if c.isspace() else c) for c in fallback if ord(c) < 128
    ) or "import_template.xlsx"
    if all(ord(c) < 128 for c in name):
        # 英文等 ASCII 译文：filename 也走译文，语言切换时文件名会变
        ascii_name = "".join("_" if c.isspace() else c for c in name) or fallback
    else:
        ascii_name = fallback
    quoted = quote(name, safe="")
    return 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_name, quoted)


def _template_data_row(kind: str, row: Dict[str, Any]) -> List[Any]:
    """按模板表头从明细行提取写入值。"""
    sku = str(row.get("sku") or "").strip()
    price = row.get("price_with_vat")
    if kind == _KIND_QUOTE:
        return [sku, price]
    return [sku, price, row.get("qty")]


def build_line_import_template(
    kind: str,
    history_rows: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, str, str]:
    """
    生成导入模板 xlsx，返回 (内容, 展示文件名, ASCII 备用文件名)。
    history_rows：可选，写入已填写的历史明细（如报价单已有行）。
    表头 / sheet 名 / 文件名按请求语言翻译。
    """
    td = translation_dict or {}
    if kind == _KIND_QUOTE:
        cn_headers = QUOTE_TEMPLATE_HEADERS
        sheet_cn = "报价明细"
    elif kind == _KIND_ORDER:
        cn_headers = ORDER_TEMPLATE_HEADERS
        sheet_cn = "订单明细"
    else:
        raise DistributionOrderError(40000, "明细类型无效")
    headers = tuple(translate_text(h, is_trans, td) or h for h in cn_headers)
    sheet_title = (translate_text(sheet_cn, is_trans, td) or sheet_cn)[:31] or sheet_cn
    display_name, ascii_name = _import_template_filenames(
        kind, is_trans=is_trans, translation_dict=td,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(list(headers))
    for row in history_rows or []:
        if not isinstance(row, dict):
            continue
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        ws.append(_template_data_row(kind, row))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue(), display_name, ascii_name


def _normalize_header(name: Any) -> str:
    return str(name or "").strip()


def _build_header_field_map(
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """中文表头 + 别名 + 当前语言译文（小写）→ 内部字段。"""
    mapped: Dict[str, str] = {}
    td = translation_dict or {}
    for field, labels in _FIELD_CN_LABELS.items():
        for label in labels:
            text = _normalize_header(label)
            if not text:
                continue
            mapped[text.lower()] = field
            if is_trans and td:
                translated = _normalize_header(translate_text(text, True, td) or "")
                if translated:
                    mapped[translated.lower()] = field
    return mapped


def _map_excel_columns(
    columns: Sequence[Any],
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Excel 列名 → 内部字段名（同时识别中文与译文表头）。"""
    header_field_map = _build_header_field_map(is_trans, translation_dict)
    mapped: Dict[str, str] = {}
    for col in columns:
        key = _normalize_header(col)
        if not key:
            continue
        field = header_field_map.get(key.lower())
        if field:
            mapped[key] = field
    return mapped


def _required_fields(kind: str) -> Tuple[str, ...]:
    if kind == _KIND_QUOTE:
        return ("sku", "price_with_vat")
    return ("sku", "price_with_vat", "qty")


def _parse_excel_rows(
    content: bytes,
    kind: str,
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise DistributionOrderError(
            40000,
            _import_msg(
                "文件解析失败：{reason}", is_trans, translation_dict, reason=str(exc),
            ),
        ) from exc

    if df is None or df.empty:
        raise DistributionOrderError(
            40000, _import_msg("该文件无数据", is_trans, translation_dict),
        )

    if int(df.shape[0]) > _MAX_IMPORT_ROWS:
        raise DistributionOrderError(
            40000,
            _import_msg(
                "上传数据过多，单次最多上传{max}条",
                is_trans, translation_dict, max=_MAX_IMPORT_ROWS,
            ),
        )

    col_map = _map_excel_columns(
        df.columns, is_trans=is_trans, translation_dict=translation_dict,
    )
    if not col_map:
        raise DistributionOrderError(
            40000,
            _import_msg("表头无效，请使用模板下载的表头", is_trans, translation_dict),
        )

    rename = {src: dst for src, dst in col_map.items()}
    df = df.rename(columns=rename)

    required = _required_fields(kind)
    missing = [f for f in required if f not in df.columns]
    if missing:
        raise DistributionOrderError(
            40000,
            _import_msg("缺少必填列，请使用模板下载的表头", is_trans, translation_dict),
        )

    rows: List[Dict[str, Any]] = []
    for idx, rec in enumerate(df.to_dict("records"), start=2):
        sku = str(rec.get("sku") or "").strip()
        if not sku or sku.lower() in ("nan", "none"):
            continue
        price_raw = rec.get("price_with_vat")
        if price_raw is None or (isinstance(price_raw, float) and pd.isna(price_raw)):
            raise DistributionOrderError(
                40000,
                _import_msg(
                    "第{row}行含增值税单价不能为空", is_trans, translation_dict, row=idx,
                ),
            )
        try:
            price_with_vat = Decimal(str(price_raw).strip())
        except (InvalidOperation, ValueError):
            raise DistributionOrderError(
                40000,
                _import_msg(
                    "第{row}行含增值税单价格式无效", is_trans, translation_dict, row=idx,
                ),
            )

        row: Dict[str, Any] = {
            "sku": sku,
            "price_with_vat": price_with_vat,
            "_excel_row": idx,
        }
        if kind == _KIND_ORDER:
            qty_raw = rec.get("qty")
            if qty_raw is None or (isinstance(qty_raw, float) and pd.isna(qty_raw)):
                raise DistributionOrderError(
                    40000,
                    _import_msg(
                        "第{row}行数量不能为空", is_trans, translation_dict, row=idx,
                    ),
                )
            try:
                qty = int(float(qty_raw))
            except (TypeError, ValueError):
                raise DistributionOrderError(
                    40000,
                    _import_msg(
                        "第{row}行数量格式无效", is_trans, translation_dict, row=idx,
                    ),
                )
            if qty <= 0:
                raise DistributionOrderError(
                    40000,
                    _import_msg(
                        "第{row}行数量必须大于0", is_trans, translation_dict, row=idx,
                    ),
                )
            row["qty"] = qty
        rows.append(row)

    if not rows:
        raise DistributionOrderError(
            40000, _import_msg("该文件无有效数据行", is_trans, translation_dict),
        )
    return rows


def _check_duplicate_skus(
    rows: List[Dict[str, Any]],
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    seen: Dict[str, int] = {}
    dup_rows: List[int] = []
    for row in rows:
        sku = str(row.get("sku") or "").strip().upper()
        excel_row = int(row.get("_excel_row") or 0)
        if sku in seen:
            dup_rows.append(excel_row)
        else:
            seen[sku] = excel_row
    if dup_rows:
        display = dup_rows[:5]
        raise DistributionOrderError(
            40000,
            _import_msg(
                "文件中存在重复SKU，请检查第{rows}行{more}",
                is_trans,
                translation_dict,
                rows=", ".join(str(i) for i in display),
                more=_import_more_suffix(len(dup_rows), 5, is_trans, translation_dict),
            ),
        )


async def _fetch_valid_product_skus(
    session: AsyncSession, skus: Sequence[str],
) -> Set[str]:
    """按导入 SKU 批量查询 data_product_sku 中已启用记录。"""
    codes = list({str(s or "").strip() for s in skus if str(s or "").strip()})
    if not codes:
        return set()
    rows = (
        await session.execute(
            select(DataProductSku.sku).where(
                DataProductSku.sku.in_(codes),
                DataProductSku.sku_status == "1",
            ),
        )
    ).scalars().all()
    return {str(sku).strip().upper() for sku in rows if sku}


def parse_quote_skus_param(
    raw: Optional[str],
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    """解析前端传入的报价单 SKU 列表（JSON 数组字符串）。"""
    text_val = (raw or "").strip()
    if not text_val:
        return set()
    try:
        parsed = ast.literal_eval(text_val)
    except (SyntaxError, ValueError):
        raise DistributionOrderError(
            40000,
            _import_msg("quote_skus 格式无效，须为 JSON 数组字符串", is_trans, translation_dict),
        )
    if not isinstance(parsed, list):
        raise DistributionOrderError(
            40000, _import_msg("quote_skus 须为数组", is_trans, translation_dict),
        )
    out: Set[str] = set()
    for item in parsed:
        sku = str(item or "").strip()
        if sku:
            out.add(sku.upper())
    return out


def _validate_quote_skus_in_product(
    rows: List[Dict[str, Any]],
    valid_skus: Set[str],
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    invalid: List[str] = []
    for row in rows:
        sku = str(row.get("sku") or "").strip()
        if sku.upper() not in valid_skus:
            invalid.append(sku)
    if invalid:
        display = invalid[:5]
        raise DistributionOrderError(
            40000,
            _import_msg(
                "以下SKU不存在或未启用：{skus}{more}",
                is_trans,
                translation_dict,
                skus=", ".join(display),
                more=_import_more_suffix(len(invalid), 5, is_trans, translation_dict),
            ),
        )


def _validate_order_skus_in_quote(
    rows: List[Dict[str, Any]],
    quote_skus: Set[str],
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    if not quote_skus:
        raise DistributionOrderError(
            40000, _import_msg("quote_skus 不能为空", is_trans, translation_dict),
        )
    invalid: List[str] = []
    for row in rows:
        sku = str(row.get("sku") or "").strip()
        if sku.upper() not in quote_skus:
            invalid.append(sku)
    if invalid:
        display = invalid[:5]
        raise DistributionOrderError(
            40000,
            _import_msg(
                "以下SKU不在报价单中：{skus}{more}",
                is_trans,
                translation_dict,
                skus=", ".join(display),
                more=_import_more_suffix(len(invalid), 5, is_trans, translation_dict),
            ),
        )


def _rows_to_line_dicts(
    rows: List[Dict[str, Any]], kind: str,
) -> List[Dict[str, Any]]:
    """转为前端可回传 save 接口的 lines 结构（无 _id 表示新增）。"""
    lines: List[Dict[str, Any]] = []
    for row in rows:
        item: Dict[str, Any] = {
            "sku": row["sku"],
            "price_with_vat": row["price_with_vat"],
        }
        if kind == _KIND_ORDER:
            item["qty"] = row["qty"]
        lines.append(item)
    return lines


def assert_import_file_name(
    filename: str,
    *,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> None:
    name = (filename or "").lower()
    if not any(name.endswith("." + ext) for ext in _EXCEL_EXTENSIONS):
        raise DistributionOrderError(
            40000,
            _import_msg("仅支持 Excel 文件（xls/xlsx/xlsm）", is_trans, translation_dict),
        )


async def parse_line_details_from_excel(
    session: AsyncSession,
    *,
    kind: str,
    content: bytes,
    quote_skus_raw: Optional[str] = None,
    is_trans: bool = False,
    translation_dict: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """解析并校验 Excel，返回 lines（不落库，由前端合并后调 save）。"""
    line_kind_config(kind)
    rows = _parse_excel_rows(
        content, kind, is_trans=is_trans, translation_dict=translation_dict,
    )
    # 报价明细：文件内 SKU 不可重复；订单明细允许相同 SKU
    if kind == _KIND_QUOTE:
        _check_duplicate_skus(rows, is_trans=is_trans, translation_dict=translation_dict)

    if kind == _KIND_QUOTE:
        import_skus = [str(row.get("sku") or "").strip() for row in rows]
        valid_skus = await _fetch_valid_product_skus(session, import_skus)
        _validate_quote_skus_in_product(
            rows, valid_skus, is_trans=is_trans, translation_dict=translation_dict,
        )
    else:
        quote_skus = parse_quote_skus_param(
            quote_skus_raw, is_trans=is_trans, translation_dict=translation_dict,
        )
        _validate_order_skus_in_quote(
            rows, quote_skus, is_trans=is_trans, translation_dict=translation_dict,
        )

    return _rows_to_line_dicts(rows, kind)
