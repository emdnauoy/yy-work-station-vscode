-- 若已执行过 20260803_batch_dropship.sql（无 cooperation_method），补执行本脚本
ALTER TABLE `internal_app`.`data_distribution_order`
  ADD COLUMN `cooperation_method` SMALLINT NULL COMMENT '合作方式快照 1批发 2一件代发(来自线下客户)' AFTER `settlement_method`;
