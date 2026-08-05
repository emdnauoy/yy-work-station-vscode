-- 软删字段统一命名：is_deleted → is_delete
ALTER TABLE `internal_app`.`data_distribution_order`
  CHANGE COLUMN `is_deleted` `is_delete` TINYINT NOT NULL DEFAULT 0
  COMMENT '软删 0=正常 1=已删(仅service写,前端删传_id)';

ALTER TABLE `internal_app`.`data_distribution_order_quote_detail`
  CHANGE COLUMN `is_deleted` `is_delete` TINYINT NOT NULL DEFAULT 0
  COMMENT '软删 0=正常 1=已删(删行传_id)';

ALTER TABLE `internal_app`.`data_distribution_order_item_detail`
  CHANGE COLUMN `is_deleted` `is_delete` TINYINT NOT NULL DEFAULT 0
  COMMENT '软删 0=正常 1=已删(删行传_id)';
