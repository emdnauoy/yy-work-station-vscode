# -* coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : distribution_order_line.py
# @Description : 报价/订单明细 list / save / delete / import
"""
import io
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_async_session

from apps.system.distribution_order.auth import oauth2_scheme
from apps.system.distribution_order.distribution_order_extent import (
    get_table_config,
)
from apps.system.distribution_order.distribution_order_line_import_service import (
    assert_import_file_name, build_line_import_template,
    build_template_content_disposition, parse_line_details_from_excel,
)
from apps.system.distribution_order.distribution_order_line_service import (
    list_line_details, save_line_details, soft_delete_line_details,
)
from apps.system.distribution_order.distribution_order_service import (
    _load_order, build_order_save_data,
)
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.schemas import (
    LineDetailDeleteIn, OrderDetailBatchSaveIn, QuoteDetailBatchSaveIn,
)
from apps.system.distribution_order.translate import (
    get_translaiton_dict_from_request, translate_text,
)
from apps.system.distribution_order.operation_log import (
    LOG_SCOPE_ORDER_DETAIL,
    LOG_SCOPE_QUOTE_DETAIL,
    get_operator_display_name,
    log_distribution_order_create,
    log_distribution_order_update,
)

# 统一走 offline_customer 翻译模块（含 common / msg）
_LINE_TRANS_MODULES = ["offline_customer", "common", "msg"]


async def _line_list(
    order_id: int, kind: str, session: AsyncSession,
) -> Dict[str, Any]:
    if order_id <= 0:
        return {"code": 40000, "msg": "order_id 无效", "data": {}}
    try:
        rows = await list_line_details(session, order_id, kind)
    except DistributionOrderError as exc:
        return {"code": 40000, "msg": exc.msg, "data": {}}
    except Exception as e:
        logger.error(f"明细列表失败：{e}")
        return {"code": 40000, "msg": "明细列表失败", "data": {}}
    return {"code": 200, "msg": "获取数据成功", "data": {"t_data": rows}}


async def distribution_order_quote_details_list(
    request: Request,
    order_id: int,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_list(order_id, "quote", inter_session)


async def distribution_order_order_details_list(
    request: Request,
    order_id: int,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_list(order_id, "order", inter_session)


async def _line_save(
    request: Request,
    body: Any,
    kind: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _LINE_TRANS_MODULES,
    )
    username = get_operator_display_name(request)
    try:
        table_base_data = await get_table_config(session, request)
        filter_value = table_base_data.get("filter_value") or []
        await save_line_details(
            session, body.order_id, kind, body.lines,
            filter_value=filter_value,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
        new_lines = await list_line_details(session, body.order_id, kind)
        scope_key = LOG_SCOPE_QUOTE_DETAIL if kind == "quote" else LOG_SCOPE_ORDER_DETAIL
        await log_distribution_order_create(
            session, username=username, order_id=body.order_id,
            snapshot=new_lines, scope=scope_key,
        )
        order = await _load_order(session, body.order_id)
        await session.commit()
    except DistributionOrderError as exc:
        await session.rollback()
        msg = translate_text(exc.msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    except Exception as e:
        await session.rollback()
        logger.error(f"明细保存失败：{e}")
        msg = translate_text("保存失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("保存成功", is_trans, translation_dict)
    return {
        "code": 200,
        "msg": msg,
        "data": build_order_save_data(int(body.order_id), order.order_sn),
    }


async def distribution_order_quote_details_save(
    request: Request,
    body: QuoteDetailBatchSaveIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_save(request, body, "quote", inter_session)


async def distribution_order_order_details_save(
    request: Request,
    body: OrderDetailBatchSaveIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_save(request, body, "order", inter_session)


async def _line_delete(
    request: Request,
    body: LineDetailDeleteIn,
    kind: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _LINE_TRANS_MODULES,
    )
    username = get_operator_display_name(request)
    try:
        await soft_delete_line_details(
            session, body.order_id, kind, body.detail_ids,
        )
        new_lines = await list_line_details(session, body.order_id, kind)
        scope_key = LOG_SCOPE_QUOTE_DETAIL if kind == "quote" else LOG_SCOPE_ORDER_DETAIL
        await log_distribution_order_create(
            session, username=username, order_id=body.order_id,
            snapshot=new_lines, scope=scope_key,
        )
        await session.commit()
    except DistributionOrderError as exc:
        await session.rollback()
        msg = translate_text(exc.msg, is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    except Exception as e:
        await session.rollback()
        logger.error(f"明细删除失败：{e}")
        msg = translate_text("删除失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("删除成功", is_trans, translation_dict)
    return {"code": 200, "msg": msg, "data": {}}


async def distribution_order_quote_details_delete(
    request: Request,
    body: LineDetailDeleteIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_delete(request, body, "quote", inter_session)


async def distribution_order_order_details_delete(
    request: Request,
    body: LineDetailDeleteIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_delete(request, body, "order", inter_session)


def _line_import_template_response(
    kind: str,
    history_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    is_trans: bool = False,
    translation_dict=None,
) -> StreamingResponse:
    content, display_name, ascii_name = build_line_import_template(
        kind,
        history_rows=history_rows,
        is_trans=is_trans,
        translation_dict=translation_dict,
    )
    headers = {
        "Content-Disposition": build_template_content_disposition(
            display_name, ascii_name,
        ),
    }
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


async def distribution_order_quote_details_template(
    request: Request,
    order_id: Optional[int] = None,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    """报价明细导入模板：传 order_id 时回填已有明细，不传则空模板。"""
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _LINE_TRANS_MODULES,
    )
    history_rows: Optional[List[Dict[str, Any]]] = None
    if order_id is not None and int(order_id) > 0:
        try:
            history_rows = await list_line_details(inter_session, int(order_id), "quote")
        except DistributionOrderError as exc:
            msg = translate_text(exc.msg, is_trans, translation_dict)
            return {"code": 40000, "msg": msg, "data": {}}
        except Exception as e:
            logger.error(f"报价模板下载失败：{e}")
            msg = translate_text("操作失败", is_trans, translation_dict)
            return {"code": 40000, "msg": msg, "data": {}}
    return _line_import_template_response(
        "quote",
        history_rows=history_rows,
        is_trans=is_trans,
        translation_dict=translation_dict,
    )


async def distribution_order_order_details_template(
    request: Request,
    order_id: Optional[int] = None,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
):
    """订单明细导入模板：传 order_id 时回填已有明细，不传则空模板。"""
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _LINE_TRANS_MODULES,
    )
    history_rows: Optional[List[Dict[str, Any]]] = None
    if order_id is not None and int(order_id) > 0:
        try:
            history_rows = await list_line_details(inter_session, int(order_id), "order")
        except DistributionOrderError as exc:
            msg = translate_text(exc.msg, is_trans, translation_dict)
            return {"code": 40000, "msg": msg, "data": {}}
        except Exception as e:
            logger.error(f"订单明细模板下载失败：{e}")
            msg = translate_text("操作失败", is_trans, translation_dict)
            return {"code": 40000, "msg": msg, "data": {}}
    return _line_import_template_response(
        "order",
        history_rows=history_rows,
        is_trans=is_trans,
        translation_dict=translation_dict,
    )


async def _line_import(
    request: Request,
    *,
    kind: str,
    file: UploadFile,
    quote_skus: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _LINE_TRANS_MODULES,
    )
    try:
        assert_import_file_name(
            file.filename or "",
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
        content = await file.read()
        lines = await parse_line_details_from_excel(
            session,
            kind=kind,
            content=content,
            quote_skus_raw=quote_skus if kind == "order" else None,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
    except DistributionOrderError as exc:
        return {"code": 40000, "msg": exc.msg, "data": {}}
    except Exception as e:
        logger.error(f"明细导入解析失败：{e}")
        msg = translate_text("解析失败", is_trans, translation_dict)
        return {"code": 40000, "msg": msg, "data": {}}
    msg = translate_text("解析成功", is_trans, translation_dict)
    detail_key = "quote_details" if kind == "quote" else "order_details"
    return {
        "code": 200,
        "msg": msg,
        "data": {
            detail_key: lines,
            "imported_count": len(lines),
        },
    }


async def distribution_order_quote_details_import(
    request: Request,
    file: UploadFile = File(...),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_import(
        request,
        kind="quote",
        file=file,
        quote_skus="[]",
        session=inter_session,
    )


async def distribution_order_order_details_import(
    request: Request,
    quote_skus: str = Form("[]", description="报价单全部 SKU，JSON 数组字符串"),
    file: UploadFile = File(...),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    return await _line_import(
        request,
        kind="order",
        file=file,
        quote_skus=quote_skus,
        session=inter_session,
    )
