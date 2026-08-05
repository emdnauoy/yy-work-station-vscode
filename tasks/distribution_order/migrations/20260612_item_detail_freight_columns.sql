-- 订单明细行：运费分摊字段（提交审核时按主单运费占比写入）
ALTER TABLE `internal_app`.`data_distribution_order_item_detail`
  ADD COLUMN `freight_with_vat` DECIMAL(18, 2) NULL COMMENT '含增值税运费收入(提交审核分摊)' AFTER `amount_without_vat`,
  ADD COLUMN `freight_without_vat` DECIMAL(18, 2) NULL COMMENT '不含增值税运费收入(提交审核分摊)' AFTER `freight_with_vat`,
  ADD COLUMN `order_amount_with_vat` DECIMAL(18, 2) NULL COMMENT '含增值税订单总额 amount_with_vat+freight_with_vat' AFTER `freight_without_vat`,
  ADD COLUMN `order_amount_without_vat` DECIMAL(18, 2) NULL COMMENT '不含增值税订单总额 amount_without_vat+freight_without_vat' AFTER `order_amount_with_vat`;
