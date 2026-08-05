# -*- coding: utf-8 -*-
"""
分销订单待办兜底同步脚本（每日 cron 执行）。

主路径为 view 内 ``handle_*_realtime`` 实时推送；本脚本补推未同步记录。

在 yy 主仓根目录执行::

    python -m apps.system.distribution_order.scripts.sync_distribution_order_todo
    python -m apps.system.distribution_order.scripts.sync_distribution_order_todo --scene prepay_confirm
    python -m apps.system.distribution_order.scripts.sync_distribution_order_todo --dry-run

crontab 示例（每天 8:00）::

    0 8 * * * cd /path/to/yy && /path/to/venv/bin/python -m apps.system.distribution_order.scripts.sync_distribution_order_todo >> /var/log/yy/distribution_order_todo_sync.log 2>&1

合入主仓后路径：
``apps/system/distribution_order/scripts/sync_distribution_order_todo.py``
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def _run(scenes, dry_run: bool) -> dict:
    from apps.system.distribution_order.scripts.distribution_order_todo_sync import (
        async_distribution_order_todo,
    )

    if dry_run:
        from sqlalchemy import func, select

        from apps.system.distribution_order.distribution_order_workflow_engine import (
            STATUS_ORDER_REVIEW,
            STATUS_PENDING_PAYMENT,
            STATUS_PREPAY,
            STATUS_QUOTE_REVIEW,
        )
        from apps.system.distribution_order.models import DistributionOrder
        from core.db.session import get_async_session

        async def _approval_pending(synced_attr: str):
            synced_col = getattr(DistributionOrder, synced_attr)
            return (
                select(func.count())
                .select_from(DistributionOrder)
                .where(
                    DistributionOrder.is_delete == 0,
                    DistributionOrder.current_step.isnot(None),
                    (synced_col.is_(None)) | (synced_col != DistributionOrder.current_step),
                )
            )

        checks = {
            "quote_approval": (
                _approval_pending("quote_approval_todo_synced_step").where(
                    DistributionOrder.status == STATUS_QUOTE_REVIEW,
                ),
                "报价审核",
            ),
            "order_approval": (
                _approval_pending("order_approval_todo_synced_step").where(
                    DistributionOrder.status == STATUS_ORDER_REVIEW,
                ),
                "订单审核",
            ),
            "prepay_confirm": (
                select(func.count())
                .select_from(DistributionOrder)
                .where(
                    DistributionOrder.status == STATUS_PREPAY,
                    DistributionOrder.prepay_todo_synced == 0,
                    DistributionOrder.is_delete == 0,
                ),
                "确认预付",
            ),
            "payment_confirm": (
                select(func.count())
                .select_from(DistributionOrder)
                .where(
                    DistributionOrder.status == STATUS_PENDING_PAYMENT,
                    DistributionOrder.payment_todo_synced == 0,
                    DistributionOrder.is_delete == 0,
                ),
                "待回款",
            ),
        }
        active = scenes if scenes and "all" not in scenes else list(checks.keys())
        result = {}
        async for session in get_async_session():
            for key in active:
                if key not in checks:
                    continue
                stmt, label = checks[key]
                n = int((await session.execute(stmt)).scalar() or 0)
                result[key] = n
                print("dry-run [%s] 待补推约 %s 单" % (label, n))
            break
        return result

    return await async_distribution_order_todo(scenes=scenes)


def main(argv=None) -> int:
    from apps.system.distribution_order.scripts.distribution_order_todo_sync import SCENES

    parser = argparse.ArgumentParser(
        description="分销订单首页待办兜底同步（补推未同步记录）",
    )
    parser.add_argument(
        "--scene",
        action="append",
        dest="scenes",
        choices=[s for s in SCENES if s != "all"],
        help="指定场景，可多次传入；默认扫全部四类",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅统计待补推数量，不写库、不推 Redis",
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args.scenes, args.dry_run))
        if not args.dry_run:
            parts = ["%s=%s" % (k, v) for k, v in sorted(result.items())]
            print("distribution order todo synced: %s" % ", ".join(parts))
    except ImportError as exc:
        print("导入失败（请在 yy 主仓环境执行）: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
