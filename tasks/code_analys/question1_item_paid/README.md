# Question 1: Shopee item_paid 重复扣减

## 问题

gross.py 的 `fetch_order_detail()` 计算 Shopee 的 `item_paid` 时，重复扣减了卖家折扣。

## 原因

Shopee API 的 `discounted_price`（即 DB `item_paid`）已经是卖家折扣后的价格，代码又减了一次 `seller_voucher` 和 `platform_subsidy`。

```
代码：item_paid = discounted_price - seller_voucher - platform_subsidy
正确：item_paid = discounted_price
```

## 影响

每行 item_paid 少算约 2.42 亿（IDR），经 `/10000` 换算后 paid_price 偏低约 72,690。

## 修复

Shopee 的 `item_paid` 直接用 `discounted_price`，不减任何券。券金额只记录，不参与实付计算。
