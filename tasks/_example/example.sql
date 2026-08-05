-- internal_app.data_example_record
-- MySQL 8.0；InnoDB / utf8mb4 / utf8mb4_unicode_ci
--
-- 草稿支持：业务字段默认 NULL，无 DEFAULT 字面值，
--           让"用户没填"与"用户主动填空值"在 DB 层可区分。
--           不需要草稿的任务把对应列改回 NOT NULL + DEFAULT。
CREATE TABLE IF NOT EXISTS `internal_app`.`data_example_record` (
  `_id`                  BIGINT       NOT NULL AUTO_INCREMENT                                       COMMENT '主键ID',
  `offline_customer_id`  BIGINT       NULL                                                          COMMENT '关联客户的id；草稿可空',
  `status`               SMALLINT     NULL                                                          COMMENT '状态 1=正常 2=禁用；NULL=草稿',
  `remark`               VARCHAR(500) NULL                                                          COMMENT '备注；草稿可空',
  `create_time`          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP                            COMMENT '创建时间',
  `update_time`          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `create_by`            BIGINT       NULL                                                          COMMENT '创建人id',
  `update_by`            BIGINT       NULL                                                          COMMENT '更新人id',
  PRIMARY KEY (`_id`),
  KEY `idx_offline_customer_id` (`offline_customer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='示例业务表（支持草稿）';
