-- 一件代发批量建单：主表扩列 + 框架报价表
ALTER TABLE `internal_app`.`data_distribution_order`
  ADD COLUMN `batch_id` VARCHAR(64) NULL COMMENT '批量建单批次号；普通单 NULL' AFTER `remark`,
  ADD COLUMN `customer_po_no` VARCHAR(128) NULL COMMENT '客户侧订单号' AFTER `batch_id`,
  ADD COLUMN `create_source` SMALLINT NOT NULL DEFAULT 0 COMMENT '创建来源 0普通 1一件代发批量' AFTER `customer_po_no`,
  ADD COLUMN `cooperation_method` SMALLINT NULL COMMENT '合作方式快照 1批发 2一件代发(来自线下客户)' AFTER `settlement_method`;

ALTER TABLE `internal_app`.`data_distribution_order`
  ADD INDEX `idx_batch_id` (`batch_id`);

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_framework_quote` (
  `_id`                 BIGINT         NOT NULL AUTO_INCREMENT COMMENT '主键',
  `offline_customer_id` BIGINT         NOT NULL                COMMENT '线下客户 data_sys_offline_customers._id',
  `currency`            VARCHAR(8)     NULL                    COMMENT '币种',
  `remark`              VARCHAR(800)   NULL                    COMMENT '备注',
  `is_delete`           TINYINT        NOT NULL DEFAULT 0      COMMENT '软删 0正常 1已删',
  `create_time`         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time`         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `create_by`           INT            NULL                    COMMENT '创建人',
  `update_by`           INT            NULL                    COMMENT '更新人',
  PRIMARY KEY (`_id`),
  KEY `idx_offline_customer_id` (`offline_customer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='分销一件代发框架报价头';

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_framework_quote_line` (
  `_id`                 BIGINT         NOT NULL AUTO_INCREMENT COMMENT '主键',
  `framework_quote_id`  BIGINT         NOT NULL                COMMENT '框架头 data_distribution_framework_quote._id',
  `sku`                 VARCHAR(64)    NOT NULL DEFAULT ''     COMMENT 'SKU编码',
  `price_with_vat`      DECIMAL(18, 4) NULL                    COMMENT '含增值税单价(价目参考)',
  `is_delete`           TINYINT        NOT NULL DEFAULT 0      COMMENT '软删 0正常 1已删',
  `create_time`         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time`         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`_id`),
  KEY `idx_framework_quote_id` (`framework_quote_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='分销一件代发框架报价明细';
