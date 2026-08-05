-- 线下客户：合作方式
ALTER TABLE `internal_app`.`data_sys_offline_customers`
  ADD COLUMN `cooperation_method` SMALLINT NULL COMMENT '合作方式 1批发 2一件代发'
  AFTER `remark`;
