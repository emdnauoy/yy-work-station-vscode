# -*- coding: utf-8 -*-
"""千易 skuList 同 SKU 合并逻辑单测（无需 DB）。"""
from __future__ import annotations

import importlib.util
import sys
import types
from decimal import Decimal
from types import SimpleNamespace


def _load_builder():
    root = __file__.replace("\\", "/").rsplit("/scripts/", 1)[0]
    if root not in sys.path:
        sys.path.insert(0, root)
    apps = types.ModuleType("apps")
    sys.modules["apps"] = apps
    sys.modules["apps.system"] = types.ModuleType("apps.system")
    sys.modules["apps.system.distribution_order"] = types.ModuleType("apps.system.distribution_order")
    err = types.ModuleType("apps.system.distribution_order.errors")

    class QianyiErpError(Exception):
        def __init__(self, code, msg):
            self.code, self.msg = code, msg
            super().__init__(msg)

    err.QianyiErpError = QianyiErpError
    sys.modules["apps.system.distribution_order.errors"] = err
    models = types.ModuleType("apps.system.distribution_order.models")
    models.DistributionOrder = object
    models.DistributionOrderItemDetail = object
    models.DistributionOrderSnapshot = object
    sys.modules["apps.system.distribution_order.models"] = models

    path = root + "/qianyi_erp_order_builder.py"
    spec = importlib.util.spec_from_file_location("qb", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _line(sku, qty, price, amount, freight=None, dispatched=0, is_delete=0):
    return SimpleNamespace(
        sku=sku, qty=qty, price_with_vat=price, amount_with_vat=amount,
        freight_with_vat=freight, dispatched_qty=dispatched, is_delete=is_delete,
    )


def _sum_field(rows, key):
    return sum(Decimal(str(r[key])) for r in rows)


def test_same_sku_different_price_merge():
    qb = _load_builder()
    lines = [
        _line("SKU-A", 2, 10, Decimal("20.00"), Decimal("3.00")),
        _line("SKU-A", 3, 12, Decimal("36.00"), Decimal("7.00")),
        _line("SKU-B", 1, 5, Decimal("5.00"), Decimal("2.00")),
    ]
    sku_list, pool = qb._build_sku_list(lines, Decimal("12"))
    assert len(sku_list) == 2
    a = next(x for x in sku_list if x["sku"] == "SKU-A")
    assert a["quantity"] == 5
    assert Decimal(str(a["paymentPrice"])) == Decimal("11.2")  # 56/5
    assert _sum_field(sku_list, "shippingPrice") == pool
    assert pool == Decimal("12")
    goods_a = Decimal(str(a["payAmount"])) - Decimal(str(a["shippingPrice"]))
    assert goods_a == Decimal("56")


def test_full_dispatch_freight_matches_order():
    qb = _load_builder()
    lines = [
        _line("X", 4, 25, Decimal("100.00"), Decimal("40.00")),
        _line("Y", 1, 50, Decimal("50.00"), Decimal("10.00")),
    ]
    sku_list, pool = qb._build_sku_list(lines, Decimal("50"))
    assert pool == Decimal("50")
    assert _sum_field(sku_list, "shippingPrice") == Decimal("50")


def test_customer_pay_freight_zero():
    qb = _load_builder()
    lines = [_line("A", 1, 10, Decimal("10"), Decimal("0"))]
    sku_list, pool = qb._build_sku_list(lines, Decimal("0"))
    assert pool == Decimal("0")
    assert sku_list[0]["shippingPrice"] == 0.0


def test_partial_dispatch_proportional():
    qb = _load_builder()
    lines = [_line("A", 10, 10, Decimal("100.00"), Decimal("10.00"), dispatched=4)]
    sku_list, pool = qb._build_sku_list(lines, Decimal("10"))
    assert sku_list[0]["quantity"] == 6
    assert Decimal(str(sku_list[0]["payAmount"])) - Decimal(str(sku_list[0]["shippingPrice"])) == Decimal("60")
    assert pool == Decimal("6")  # 10 * 6/10


def test_empty_sku_rejected():
    qb = _load_builder()
    try:
        qb._build_sku_list([_line("", 1, 1, Decimal("1"), Decimal("0"))], Decimal("0"))
        assert False, "should raise"
    except qb.QianyiErpError as exc:
        assert "SKU" in exc.msg


def test_biz_freight_matches_sku_shipping():
    qb = _load_builder()
    order = SimpleNamespace(
        order_sn="B2BTEST001",
        customer_code="C001",
        customer_country="US",
        currency="USD",
        order_delivery_fee_payment=1,
        freight_with_vat=Decimal("12.00"),
        expected_ship_date=None,
        ship_remark="",
        ship_guide_attachments=None,
        ship_method=None,
        create_time=None,
    )
    snap = SimpleNamespace(
        name="Test", country="US", address="addr", contact_info="",
        province="", city="", district="", post_code="",
    )
    lines = [
        _line("SKU-A", 2, 10, Decimal("20"), Decimal("3")),
        _line("SKU-A", 3, 12, Decimal("36"), Decimal("7")),
    ]
    biz = qb.build_create_sales_order_biz_param(
        order, snap, lines, shop_name="TestShop",
    )
    ship_sum = sum(Decimal(str(x["shippingPrice"])) for x in biz["skuList"])
    assert Decimal(str(biz["freight"])) == ship_sum


def main():
    test_same_sku_different_price_merge()
    test_full_dispatch_freight_matches_order()
    test_customer_pay_freight_zero()
    test_partial_dispatch_proportional()
    test_empty_sku_rejected()
    test_biz_freight_matches_sku_shipping()
    print("all qianyi sku merge tests passed")


if __name__ == "__main__":
    main()
