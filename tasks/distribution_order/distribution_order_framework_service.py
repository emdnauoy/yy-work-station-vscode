# -*- coding: utf-8 -*-
"""
# @Time    : 2026/8/3
# @Author  : Zhu Yaming
# @File    : distribution_order_framework_service.py
# @Description : 一件代发框架报价维护
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.system.distribution_order.constants import COOPERATION_METHOD_DROPSHIP
from apps.system.distribution_order.errors import DistributionOrderError
from apps.system.distribution_order.models import (
    DistributionFrameworkQuote,
    DistributionFrameworkQuoteLine,
)
from apps.system.distribution_order.schemas import (
    FrameworkQuoteOut,
    FrameworkQuoteSaveIn,
)
from apps.system.offline_customer.models import OfflineCustomer


async def list_dropship_customers(
    session: AsyncSession,
    *,
    keyword: str = "",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """一件代发客户下拉。"""
    conds = [
        OfflineCustomer.cooperation_method == COOPERATION_METHOD_DROPSHIP,
    ]
    kw = (keyword or "").strip()
    if kw:
        like = "%{}%".format(kw)
        conds.append(
            or_(
                OfflineCustomer.customer_code.like(like),
                OfflineCustomer.customer_short_name.like(like),
            )
        )
    total = int(
        await session.scalar(
            select(func.count(OfflineCustomer._id)).where(*conds)
        ) or 0
    )
    page = max(int(page or 1), 1)
    page_size = max(min(int(page_size or 50), 200), 1)
    rows = (
        await session.execute(
            select(OfflineCustomer)
            .where(*conds)
            .order_by(OfflineCustomer._id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    items = [
        {
            "_id": int(r._id),
            "customer_code": r.customer_code or "",
            "customer_short_name": r.customer_short_name or "",
            "customer_country": r.customer_country,
            "settlement_currency": r.settlement_currency,
            "current_contract_id": r.current_contract_id,
        }
        for r in rows
    ]
    return {
        "t_data": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _assert_dropship_customer(
    session: AsyncSession, customer_id: int,
) -> OfflineCustomer:
    row = (
        await session.execute(
            select(OfflineCustomer).where(OfflineCustomer._id == customer_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise DistributionOrderError(40000, "线下客户不存在")
    if int(getattr(row, "cooperation_method", 0) or 0) != COOPERATION_METHOD_DROPSHIP:
        raise DistributionOrderError(40000, "仅一件代发客户可维护框架报价")
    return row


async def get_framework_quote(
    session: AsyncSession, offline_customer_id: int,
) -> Optional[Dict[str, Any]]:
    head = (
        await session.execute(
            select(DistributionFrameworkQuote).where(
                DistributionFrameworkQuote.offline_customer_id == offline_customer_id,
                DistributionFrameworkQuote.is_delete == 0,
            )
        )
    ).scalar_one_or_none()
    if not head:
        return None
    lines = (
        await session.execute(
            select(DistributionFrameworkQuoteLine).where(
                DistributionFrameworkQuoteLine.framework_quote_id == head._id,
                DistributionFrameworkQuoteLine.is_delete == 0,
            ).order_by(DistributionFrameworkQuoteLine._id.asc())
        )
    ).scalars().all()
    data = FrameworkQuoteOut.from_orm(head).dict(by_alias=True)
    data["lines"] = [
        {
            "_id": int(ln._id),
            "sku": ln.sku or "",
            "price_with_vat": ln.price_with_vat,
        }
        for ln in lines
    ]
    return data


async def load_framework_sku_set(
    session: AsyncSession, offline_customer_id: int,
) -> Set[str]:
    head = (
        await session.execute(
            select(DistributionFrameworkQuote).where(
                DistributionFrameworkQuote.offline_customer_id == offline_customer_id,
                DistributionFrameworkQuote.is_delete == 0,
            )
        )
    ).scalar_one_or_none()
    if not head:
        return set()
    rows = (
        await session.execute(
            select(DistributionFrameworkQuoteLine.sku).where(
                DistributionFrameworkQuoteLine.framework_quote_id == head._id,
                DistributionFrameworkQuoteLine.is_delete == 0,
            )
        )
    ).scalars().all()
    return {str(s or "").strip() for s in rows if str(s or "").strip()}


async def save_framework_quote(
    session: AsyncSession,
    body: FrameworkQuoteSaveIn,
    *,
    operator_id: Optional[int] = None,
) -> Dict[str, Any]:
    await _assert_dropship_customer(session, int(body.offline_customer_id))
    lines = body.lines or []
    alive_skus: List[str] = []
    for ln in lines:
        if int(getattr(ln, "is_delete", 0) or 0) != 0:
            continue
        sku = (ln.sku or "").strip()
        if not sku:
            raise DistributionOrderError(40000, "框架报价 SKU 不能为空")
        alive_skus.append(sku)
    if len(alive_skus) != len(set(alive_skus)):
        raise DistributionOrderError(40000, "框架报价 SKU 不可重复")

    head = (
        await session.execute(
            select(DistributionFrameworkQuote).where(
                DistributionFrameworkQuote.offline_customer_id
                == int(body.offline_customer_id),
                DistributionFrameworkQuote.is_delete == 0,
            )
        )
    ).scalar_one_or_none()
    if head is None:
        head = DistributionFrameworkQuote(
            offline_customer_id=int(body.offline_customer_id),
            create_by=operator_id,
            update_by=operator_id,
        )
        session.add(head)
        await session.flush()
    head.currency = body.currency
    head.remark = body.remark
    head.update_by = operator_id

    # 全量替换：软删旧行后重建
    old_lines = (
        await session.execute(
            select(DistributionFrameworkQuoteLine).where(
                DistributionFrameworkQuoteLine.framework_quote_id == head._id,
                DistributionFrameworkQuoteLine.is_delete == 0,
            )
        )
    ).scalars().all()
    for old in old_lines:
        old.is_delete = 1
    await session.flush()

    for ln in lines:
        if int(getattr(ln, "is_delete", 0) or 0) != 0:
            continue
        sku = (ln.sku or "").strip()
        session.add(
            DistributionFrameworkQuoteLine(
                framework_quote_id=int(head._id),
                sku=sku,
                price_with_vat=ln.price_with_vat,
                is_delete=0,
            )
        )
    await session.flush()
    data = await get_framework_quote(session, int(body.offline_customer_id))
    return data or {}
