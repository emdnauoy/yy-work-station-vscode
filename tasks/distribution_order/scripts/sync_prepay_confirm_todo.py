# -*- coding: utf-8 -*-
"""
确认预付待办同步（兼容入口，已合并至 sync_distribution_order_todo）。

推荐::

    python -m apps.system.distribution_order.scripts.sync_distribution_order_todo
    python -m apps.system.distribution_order.scripts.sync_distribution_order_todo --scene prepay_confirm
"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    try:
        from apps.system.distribution_order.scripts.sync_distribution_order_todo import (
            main as sync_main,
        )
    except ImportError as exc:
        print("导入失败（请在 yy 主仓环境执行）: %s" % exc, file=sys.stderr)
        return 1
    extra = list(argv or [])
    if "--scene" not in extra:
        extra = ["--scene", "prepay_confirm"] + extra
    return sync_main(extra)


if __name__ == "__main__":
    sys.exit(main())
