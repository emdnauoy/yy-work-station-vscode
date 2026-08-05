# -* coding: utf-8 -*-
"""
# @Time    : 2026/6/2
# @Author  : Zhu Yaming
# @File    : test_qianyi_create_sales_order.py
# @Description : 千易 CREATE_SALES_ORDER 联调脚本（使用下方测试凭证）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import types
import uuid

# 任务目录 standalone 运行：py -3 scripts/test_qianyi_create_sales_order.py
_TASK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

# 联调凭证（环境变量 QIANYI_ERP_APP_ID / QIANYI_ERP_APP_SECRET 可覆盖）
APP_ID = "1768892099208-134"
APP_SECRET = "5f66f296ade9c6b0cecb6225b17b7b5e"

_HOST_MAP = {
    "test": "gerp-test1.800best.com",
    "cn": "www.qianyierp.com",
    "asia": "asia.qianyierp.com",
}


def _bootstrap_package() -> None:
    """standalone 运行时注册 apps.system.distribution_order 别名。"""
    def _ensure(name: str) -> types.ModuleType:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
        return sys.modules[name]

    root = _ensure("apps")
    sys_pkg = _ensure("apps.system")
    setattr(root, "system", sys_pkg)
    pkg = _ensure("apps.system.distribution_order")
    setattr(sys_pkg, "distribution_order", pkg)

    for mod_name, filename in (
        ("errors", "errors.py"),
        ("qianyi_erp_client", "qianyi_erp_client.py"),
    ):
        full_path = "apps.system.distribution_order.%s" % mod_name
        spec = importlib.util.spec_from_file_location(
            full_path, os.path.join(_TASK_ROOT, filename),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_path] = mod
        spec.loader.exec_module(mod)
        setattr(pkg, mod_name, mod)


_bootstrap_package()

from apps.system.distribution_order.errors import QianyiErpError
from apps.system.distribution_order.qianyi_erp_client import (
    QianyiErpClient, QianyiErpConfig, dumps_biz_param, generate_sign,
)


def _build_config(env: str) -> QianyiErpConfig:
    host = (os.getenv("QIANYI_ERP_HOST") or _HOST_MAP.get(env, _HOST_MAP["cn"])).strip()
    return QianyiErpConfig(
        app_id=(os.getenv("QIANYI_ERP_APP_ID") or APP_ID).strip(),
        app_secret=(os.getenv("QIANYI_ERP_APP_SECRET") or APP_SECRET).strip(),
        host=host,
    )


def _sample_biz_param(online_order_number: str, shop: str) -> dict:
    """与 订单下发接口.md curl 示例对齐的最小可测参数。"""
    return {
        "trackingNumber": online_order_number,
        "shop": shop,
        "onlineOrderNumber": online_order_number,
        "paymentMethod": "COD",
        "codPayAmount": 100000,
        "currency": "IDR",
        "buyerMessage": "buyer-remark",
        "sellerRemarks": "test",
        "logisticsSelected": "YT-THZXR",
        "payTime": "2024-05-20 15:40:30+08:00",
        "buyer": {
            "buyerId": "Riza Budi 2",
            "receiverName": "Riza Budi 2",
            "phone": "0857101739512",
            "email": "apriyadhi@kanmogroup.com",
            "country": "ID",
            "province": "DKI Jakarta",
            "city": "Kota Jakarta Selatan",
            "postCode": "12940",
            "address1": "Plaza 89 Rasuna Said",
            "address2": "",
        },
        "skuList": [{"sku": "DP001", "payAmount": 0, "quantity": 1}],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="千易 CREATE_SALES_ORDER 联调")
    parser.add_argument(
        "--env", choices=("test", "cn", "asia"), default="cn",
        help="环境：当前凭证在 cn 可用；test 会报 APP_NOT_EXIST",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印请求体，不发 HTTP")
    parser.add_argument("--shop", default=os.getenv("QIANYI_ERP_SHOP", ""), help="千易店铺名（必填）")
    parser.add_argument(
        "--online-order-number",
        default=os.getenv("QIANYI_ERP_TEST_ORDER_SN", ""),
        help="线上单号（幂等键；默认自动生成）",
    )
    args = parser.parse_args()

    shop = (args.shop or "").strip()
    if not shop:
        raise SystemExit("请通过 --shop 或 QIANYI_ERP_SHOP 指定已授权的千易店铺名")

    online_sn = (args.online_order_number or "").strip() or "WS-TEST-%s" % uuid.uuid4().hex[:12].upper()
    biz_param = _sample_biz_param(online_sn, shop)
    biz_param_str = dumps_biz_param(biz_param)
    config = _build_config(args.env)

    if args.dry_run:
        ts = int(time.time() * 1000)
        sign = generate_sign(config.app_id, biz_param_str, "CREATE_SALES_ORDER", ts, config.app_secret)
        print(json.dumps({
            "env": args.env,
            "url": "%s/salesOrder" % config.base_url,
            "appId": config.app_id,
            "serviceType": "CREATE_SALES_ORDER",
            "timestamp": ts,
            "sign": sign,
            "bizParam": biz_param,
        }, ensure_ascii=False, indent=2))
        return

    try:
        client = QianyiErpClient(config)
        result = client.create_sales_order(biz_param)
    except QianyiErpError as exc:
        raise SystemExit("千易调用失败 [%s]: %s" % (exc.code, exc.msg)) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print("\n环境:", args.env, config.host)
    print("线上单号:", result.get("online_order_number"))
    print("千易单号:", result.get("order_number"))


if __name__ == "__main__":
    main()
