-- 快照表字段去前缀重命名（与 models.py DistributionOrderSnapshot 对齐）
-- 执行前请备份；若表尚未建可跳过，直接跑 schema.sql

ALTER TABLE `internal_app`.`data_distribution_order_snapshot`
  CHANGE COLUMN `contact_name` `name` VARCHAR(128) NULL COMMENT '联系人姓名快照(主仓 name)',
  CHANGE COLUMN `contact_position` `position` VARCHAR(128) NULL COMMENT '联系人职位快照',
  CHANGE COLUMN `contact_info` `info` VARCHAR(64) NULL COMMENT '联系方式快照',
  CHANGE COLUMN `address_country` `country` VARCHAR(64) NULL COMMENT '地址-国家快照',
  CHANGE COLUMN `address_province` `province` VARCHAR(128) NULL COMMENT '地址-省/州快照',
  CHANGE COLUMN `address_city` `city` VARCHAR(128) NULL COMMENT '地址-城市快照',
  CHANGE COLUMN `address_district` `district` VARCHAR(128) NULL COMMENT '地址-县/区快照',
  CHANGE COLUMN `address_post_code` `post_code` VARCHAR(32) NULL COMMENT '地址-邮编快照',
  CHANGE COLUMN `contract_effective_end` `effective_end` DATE NULL COMMENT '合同生效止',
  CHANGE COLUMN `contract_delivery_fee_payment` `delivery_fee_payment` SMALLINT NULL COMMENT '合同运费承担方编码快照 1=Simplus Pay 2=Customer Pay';

-- 若尚无 mt_delivery_mode 列则追加
-- ALTER TABLE `internal_app`.`data_distribution_order_snapshot`
--   ADD COLUMN `mt_delivery_mode` INT NULL COMMENT '交付方式 1=一次性 2=多批' AFTER `delivery_method`;
