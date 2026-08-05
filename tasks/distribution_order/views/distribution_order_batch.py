# -*- coding: utf-8 -*-
"""
# @Time    : 2026/8/3
# @Author  : Zhu Yaming
# @File    : distribution_order_batch.py
# @Description : 框架报价 / 一件代发批量建单 / 批量审核 / 批量下发
"""
import io
from typing import Any, Dict

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_async_session

from apps.system.distribution_order.auth import oauth2_scheme
from apps.system.distribution_order.distribution_order_batch_service import (
    batch_approve_orders,
    batch_dispatch_orders,
    build_batch_import_template,
    parse_batch_dropship_orders,
    submit_batch_dropship_orders,
)
from apps.system.distribution_order.distribution_order_framework_service import (
    get_framework_quote,
    list_dropship_customers,
    save_framework_quote,
)
from apps.system.distribution_order.distribution_order_line_import_service import (
    assert_import_file_name,
    build_template_content_disposition,
)
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.operation_log import get_operator_display_name
from apps.system.distribution_order.schemas import (
    BatchApproveIn,
    BatchDispatchIn,
    BatchSubmitIn,
    FrameworkQuoteSaveIn,
)
from apps.system.distribution_order.translate import (
    get_translaiton_dict_from_request,
    translate_text,
)
from apps.system.reports.view.common_func import (
    get_common_exchange_rate_dict,
    get_common_shop_dict,
)

_TRANS_MODULES = ["offline_customer", "common", "msg"]


async def distribution_order_dropship_customers(
    request: Request,
    keyword: str = "",
    page: int = 1,
    page_size: int = 50,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    try:
        data = await list_dropship_customers(
            inter_session, keyword=keyword, page=page, page_size=page_size,
        )
    except Exception as e:
        logger.error(f"一件代发客户下拉失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    return {
        "code": 200,
        "msg": translate_text("操作成功", is_trans, translation_dict),
        "data": data,
    }


async def distribution_order_framework_quote_get(
    request: Request,
    offline_customer_id: int,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    try:
        data = await get_framework_quote(inter_session, offline_customer_id)
    except DistributionOrderError as exc:
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        logger.error(f"框架报价查询失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    return {
        "code": 200,
        "msg": translate_text("操作成功", is_trans, translation_dict),
        "data": data or {},
    }


async def distribution_order_framework_quote_save(
    request: Request,
    body: FrameworkQuoteSaveIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    operator_id = getattr(getattr(request, "user", None), "id", None)
    try:
        data = await save_framework_quote(
            inter_session, body, operator_id=operator_id,
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"框架报价保存失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    return {
        "code": 200,
        "msg": translate_text("操作成功", is_trans, translation_dict),
        "data": data,
    }


async def distribution_order_batch_template(
    request: Request,
    token: str = Depends(oauth2_scheme),
):
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    content, display_name, ascii_name = build_batch_import_template(
        is_trans=is_trans, translation_dict=translation_dict,
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


async def distribution_order_batch_parse(
    request: Request,
    offline_customer_id: int = Form(...),
    file: UploadFile = File(...),
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    """上传 Excel：仅解析校验，不落库。"""
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    try:
        assert_import_file_name(file.filename or "")
        content = await file.read()
        if not content:
            raise DistributionOrderError(40000, "上传文件为空")
        data = await parse_batch_dropship_orders(
            inter_session,
            offline_customer_id=int(offline_customer_id),
            file_content=content,
            is_trans=is_trans,
            translation_dict=translation_dict,
        )
    except DistributionOrderError as exc:
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        logger.error(f"一件代发批量解析失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    return {
        "code": 200,
        "msg": translate_text("解析成功", is_trans, translation_dict),
        "data": data,
    }


async def distribution_order_batch_submit(
    request: Request,
    body: BatchSubmitIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    """前端补齐红线价/库存后：落库并提交订单审核。"""
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    operator_id = getattr(getattr(request, "user", None), "id", None)
    try:
        if not body.sales_user_id:
            raise DistributionOrderError(40000, "请选择本单销售员")
        if not (body.shop_id or "").strip():
            raise DistributionOrderError(40000, "请选择出库店铺")
        exchange_rate_dict = await get_common_exchange_rate_dict(request)
        data = await submit_batch_dropship_orders(
            inter_session,
            body,
            operator_id=operator_id,
            exchange_rate_dict=exchange_rate_dict,
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"一件代发批量提交审核失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    return {
        "code": 200,
        "msg": translate_text("操作成功", is_trans, translation_dict),
        "data": data,
    }


async def distribution_order_batch_approve(
    request: Request,
    body: BatchApproveIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    operator_id = getattr(getattr(request, "user", None), "id", None)
    try:
        data = await batch_approve_orders(
            inter_session, body, operator_id=operator_id,
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"批量审核失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    # 翻译 failed.msg
    for item in data.get("failed") or []:
        if item.get("msg"):
            item["msg"] = translate_text(item["msg"], is_trans, translation_dict)
    return {
        "code": 200,
        "msg": translate_text("操作成功", is_trans, translation_dict),
        "data": data,
    }


async def distribution_order_batch_dispatch(
    request: Request,
    body: BatchDispatchIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    is_trans, translation_dict = get_translaiton_dict_from_request(
        request, _TRANS_MODULES,
    )
    operator_id = getattr(getattr(request, "user", None), "id", None)
    username = get_operator_display_name(request)
    try:
        shop_dict = await get_common_shop_dict(request)
        data = await batch_dispatch_orders(
            inter_session, body,
            operator_id=operator_id,
            operator_name=username,
            shop_dict=shop_dict,
        )
        await inter_session.commit()
    except DistributionOrderError as exc:
        await inter_session.rollback()
        return {
            "code": 40000,
            "msg": translate_text(exc.msg, is_trans, translation_dict),
            "data": {},
        }
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"批量下发失败：{e}")
        return {
            "code": 40000,
            "msg": translate_text("操作失败", is_trans, translation_dict),
            "data": {},
        }
    for key in ("failed", "skipped"):
        for item in data.get(key) or []:
            if item.get("msg"):
                item["msg"] = translate_text(
                    item["msg"], is_trans, translation_dict,
                )
    return {
        "code": 200,
        "msg": translate_text("操作成功", is_trans, translation_dict),
        "data": data,
    }
