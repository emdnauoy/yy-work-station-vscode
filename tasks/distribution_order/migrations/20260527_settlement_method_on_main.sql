-- settlement_method 从快照表迁到主表（与 models.py / schema.sql 对齐）
-- 在已建库环境执行；新建库直接跑 schema.sql 可跳过本文件

USE `internal_app`;

-- 1) 主表增加 settlement_method（若已存在会报错，可忽略或先查 information_schema）
ALTER TABLE `data_distribution_order`
  ADD COLUMN `settlement_method` SMALLINT NULL
    COMMENT '结算方式编码快照 1=带款提货 2=账期(列表筛选)'
    AFTER `prepayment_ratio`;

ALTER TABLE `data_distribution_order`
  ADD KEY `idx_settlement_method` (`settlement_method`);

-- 2) 若快照表仍有 settlement_method，可先迁数据再删列（按需执行）
-- UPDATE `data_distribution_order` o
-- INNER JOIN `data_distribution_order_snapshot` s ON s.order_id = o._id
-- SET o.settlement_method = s.settlement_method
-- WHERE o.settlement_method IS NULL AND s.settlement_method IS NOT NULL;

-- ALTER TABLE `data_distribution_order_snapshot`
--   DROP COLUMN `settlement_method`;
