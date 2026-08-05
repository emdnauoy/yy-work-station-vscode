# -* coding: utf-8 -*-
"""
批量刷新分销订单 tags_bitmask。

在 yy 主仓根目录执行（需已配置 DB 与 apps 包路径）::

    python -m apps.system.distribution_order.scripts.refresh_distribution_order_tags --all
    python -m apps.system.distribution_order.scripts.refresh_distribution_order_tags --order-id 1001
    python -m apps.system.distribution_order.scripts.refresh_distribution_order_tags --all --dry-run

合入主仓后文件路径：
``apps/system/distribution_order/scripts/refresh_distribution_order_tags.py``
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def _run(order_ids, dry_run: bool) -> int:
    from sqlalchemy import select

    from core.db.session import get_async_session
    from apps.system.distribution_order.distribution_order_tags import (
        refresh_order_tags,
        refresh_order_tags_batch,
    )
    from apps.system.distribution_order.models import DistributionOrder

    async for session in get_async_session():
        if order_ids:
            ids = order_ids
        else:
            ids = [
                int(r[0])
                for r in (
                    await session.execute(
                        select(DistributionOrder._id).where(
                            DistributionOrder.is_deleted == 0,
                        )
                    )
                ).all()
            ]
        if dry_run:
            print("dry-run: would refresh %s order(s)" % len(ids))
            return 0
        if order_ids and len(order_ids) == 1:
            await refresh_order_tags(session, order_ids[0])
            n = 1
        else:
            n = await refresh_order_tags_batch(session, order_ids or None)
        await session.commit()
        print("refreshed tags_bitmask for %s order(s)" % n)
        return n
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="刷新分销订单 tags_bitmask")
    parser.add_argument(
        "--order-id", type=int, action="append", dest="order_ids",
        help="指定订单 _id，可多次传入",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="刷新全部未删订单（未指定 --order-id 时默认 --all）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅统计数量，不写库",
    )
    args = parser.parse_args(argv)
    if not args.order_ids and not args.all:
        parser.error("请指定 --order-id 或 --all")
    try:
        asyncio.run(_run(args.order_ids, args.dry_run))
    except ImportError as exc:
        print(
            "导入失败（请在 yy 主仓环境执行）: %s" % exc,
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
