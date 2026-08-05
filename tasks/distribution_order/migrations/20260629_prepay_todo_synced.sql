-- 分销订单首页待办同步标记（对齐 audit_center.todo_synced）
-- 见 distribution_order_todo.py、需求文档 §2.2.2 / §2.2.4 / §2.2.5 / §2.2.8

ALTER TABLE `internal_app`.`data_distribution_order`
  ADD COLUMN `quote_approval_todo_synced_step` INT NULL
    COMMENT '报价审核待办已推送的环节序号；NULL=未推送，≠current_step时需重推'
  AFTER `tags_bitmask`,
  ADD COLUMN `order_approval_todo_synced_step` INT NULL
    COMMENT '订单审核待办已推送的环节序号；NULL=未推送，≠current_step时需重推'
  AFTER `quote_approval_todo_synced_step`,
  ADD COLUMN `prepay_todo_synced` TINYINT NOT NULL DEFAULT 0
    COMMENT '确认预付待办是否已推送 0=否 1=是'
  AFTER `order_approval_todo_synced_step`,
  ADD COLUMN `payment_todo_synced` TINYINT NOT NULL DEFAULT 0
    COMMENT '待回款待办是否已推送 0=否 1=是'
  AFTER `prepay_todo_synced`;
