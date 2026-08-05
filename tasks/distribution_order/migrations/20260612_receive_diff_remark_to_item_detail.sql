-- 实收差异原因：主单 → 订单明细行
ALTER TABLE `internal_app`.`data_distribution_order_item_detail`
  ADD COLUMN `receive_diff_remark` VARCHAR(800) NULL COMMENT '实收差异原因' AFTER `received_qty`;

ALTER TABLE `internal_app`.`data_distribution_order`
  DROP COLUMN `receive_diff_remark`;
