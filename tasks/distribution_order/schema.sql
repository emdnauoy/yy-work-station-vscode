-- =============================================================================
-- 分销订单模块 DDL（整合版）
-- schema: internal_app
-- MySQL 8.0；InnoDB / utf8mb4 / utf8mb4_unicode_ci
-- 表顺序对齐 design.md §4（4.1 → 4.1b → 4.2 → 4.7）
-- 单号：暂用 B2B+国家+日期+随机后缀（service）；日序列表 data_distribution_order_sn_seq 后续再加
-- =============================================================================

-- -----------------------------------------------------------------------------
-- §4.1 data_distribution_order（订单主表）
-- status: 10草稿 20报价审核 30订单创建 40订单审核 50确认预付 60待下发
--         70履约中 80待回款 90已完成 99已作废
--
-- 填写阶段（主表热字段 + §4.1b 扩展快照；行级报价见 §4.2）：
--   第一阶段 status=10/20：基础信息 + 主表客户/预付热字段 + §4.1b 快照 + 报价明细(§4.2)
--   第二阶段 status≥30：销售结算/物流/订单创建主表字段；订单明细见 §4.3
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order` (
  -- ── 第一阶段：基础信息（单号 / 拆单 / 主状态 / 当前审批链 / 当前步）────────────────────────────────────────
  `_id`                         BIGINT         NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `order_sn`                    VARCHAR(48)    NOT NULL                                         COMMENT 'WS分销单号 B2B+国家+日期+随机后缀(暂)；子单含后缀-A',
  `parent_order_id`             BIGINT         NULL                                             COMMENT '拆单父单_id；NULL=主单',
  `status`                      SMALLINT       NOT NULL DEFAULT 10                              COMMENT '主状态 10=草稿 20=报价审核 30=订单创建 40=订单审核 50=确认预付 60=待下发 70=履约中 80=待回款 90=已完成 99=已作废',
  `void_from_status`            SMALLINT       NULL                                             COMMENT '作废前主状态；仅 status=99 时有值',
  `current_chain_code`          SMALLINT       NULL                                             COMMENT '当前审批链 1=定价审批 2=订单审批-标准 3=订单审批-大额；NULL=非审核中',
  `current_step`                INT            NULL                                             COMMENT '当前待审环节序号（对应 approval_config.step_no）；NULL=非审核中',
  `quote_lm_user_id`            INT            NULL                                             COMMENT '报价审核直线上级用户_id(提交报价审核时传入)',
  `order_lm_user_id`            INT            NULL                                             COMMENT '订单审核直线上级用户_id(订单创建保存时传入)',

  -- ── 第一阶段：客户快照 ───────────────────────────────────────────────────────
  `offline_customer_id`         BIGINT         NOT NULL                                         COMMENT '线下客户 data_sys_offline_customers._id',
  `contract_id`                 BIGINT         NULL                                             COMMENT '生效合同 data_sys_offline_contract._id',
  `customer_code`               VARCHAR(128)   NOT NULL DEFAULT ''                              COMMENT '客户编码快照',
  `customer_short_name`         VARCHAR(255)   NOT NULL DEFAULT ''                              COMMENT '客户简称快照',
  `customer_country`            VARCHAR(64)    NULL                                             COMMENT '客户国家快照',
  `customer_type_first`         VARCHAR(128)   NULL                                             COMMENT '客户类型一层快照',
  `customer_type_second`        VARCHAR(128)   NULL                                             COMMENT '客户类型二层快照',
  `is_prepayment`               SMALLINT       NOT NULL DEFAULT 0                               COMMENT '是否预付快照(合同 is_prepayment) 0=无预付 1=预付比例',
  `prepayment_ratio`            DECIMAL(9, 4)  NOT NULL DEFAULT 0.0                             COMMENT '预付比例快照(合同 prepayment_ratio)',
  `settlement_method`           SMALLINT       NULL                                             COMMENT '结算方式编码快照 1=带款提货 2=账期(列表筛选)',

  -- ── 第二阶段起（status≥30 订单创建；须报价审核通过且 §4.2 报价明细已维护）────────────
  -- ── 销售结算 ─────────────────────────────────────────────────────────────────
  `customer_po_attachments`     JSON           NULL                                             COMMENT '客户采购单文件附件',
  `oa_seal_no`                  VARCHAR(64)    NULL                                             COMMENT '用印OA编号',
  `is_tax_free`                 SMALLINT       NOT NULL DEFAULT 0                               COMMENT '是否免税 0否1是',
  `is_ewt`                      SMALLINT       NOT NULL DEFAULT 0                               COMMENT '是否预扣税 0否1是',
  `vat_rate`                    DECIMAL(9, 4)  NULL                                             COMMENT 'VAT税率',
  `ewt_rate`                    DECIMAL(9, 4)  NULL                                             COMMENT '预扣税比例',
  `currency`                    VARCHAR(8)     NULL                                             COMMENT '币种',
  `delivery_fee_payment`        SMALLINT       NULL                                             COMMENT '本次运费承担方 1=Simplus Pay 2=Customer Pay',
  `freight_with_vat`            DECIMAL(18, 2) NULL                                             COMMENT '含增值税运费收入',
  `freight_without_vat`         DECIMAL(18, 2) NULL                                             COMMENT '不含增值税运费收入',
  `goods_amount_with_vat`       DECIMAL(18, 2) NULL                                             COMMENT '含增值税商品总额',
  `goods_amount_without_vat`    DECIMAL(18, 2) NULL                                             COMMENT '不含增值税商品总额',
  `order_amount_with_vat`       DECIMAL(18, 2) NULL                                             COMMENT '含增值税订单总额',
  `order_amount_without_vat`    DECIMAL(18, 2) NULL                                             COMMENT '不含增值税订单总额',
  `vat_amount_total`            DECIMAL(18, 2) NULL                                             COMMENT '订单VAT税额汇总',
  `prepay_amount`               DECIMAL(18, 2) NULL                                             COMMENT '预付款金额',
  `ewt_amount`                  DECIMAL(18, 2) NULL                                             COMMENT '预扣税税额',
  `balance_amount`              DECIMAL(18, 2) NULL                                             COMMENT '尾款金额',
  `adjusted_balance_amount`     DECIMAL(18, 2) NULL                                             COMMENT '最新调整后尾款应收',
  `expected_payment_date`       DATE           NULL                                             COMMENT '预计回款日期',
  `actual_payment_date`         DATE           NULL                                             COMMENT '实际回款日期',

  -- ── 第二阶段：物流履约 ───────────────────────────────────────────────────────
  `ship_method`                 VARCHAR(128)   NULL                                             COMMENT '发货方式',
  `expected_ship_date`          DATE           NULL                                             COMMENT '期望出库日期',
  `actual_ship_date`            DATE           NULL                                             COMMENT '实际出库日期',
  `ship_remark`                 VARCHAR(800)   NULL                                             COMMENT '发货备注',

  -- ── 第二阶段：履约 & 下发 ────────────────────────────────────────────────────
  `shop_id`                     BIGINT         NULL                                             COMMENT '出库店铺id，yy_public_join.shopee_shop_id',
  `sales_user_id`               BIGINT         NULL                                             COMMENT '本单销售员_id',
  `system_tracking_number`      VARCHAR(64)    NULL                                             COMMENT '千易单号（下发成功后写入）',
  `waybill_no`                  VARCHAR(64)    NULL                                             COMMENT '运单号',
  `ship_guide_attachments`      JSON           NULL                                             COMMENT '发货指导文件',

  -- ── 备注（remark 任意状态可填；其余按阶段）──────────────────────────────────────
  `remark`                      TEXT           NULL                                             COMMENT '订单备注',

  -- ── 标签 ────────────────────────────────────────────────────────
  `tags_bitmask`                INT            NULL                                             COMMENT '标签位图缓存 bit0(1)=价偏 bit1(2)=大额 bit2(4)=样品 bit3(8)=缺货 bit4(16)=拆单 bit5(32)=特殊作业 bit6(64)=紧急 bit7(128)=实收差异 bit8(256)=回款超期 bit9(512)=待传水单',

  -- ── 审计 & 软删 ──────────────────────────────────────────────────────────────
  `create_time`                 DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`                 DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `create_by`                   INT            NULL                                             COMMENT '创建人',
  `submit_by`                   INT            NULL                                             COMMENT '提交审核发起人(报价/订单 submit 时写入)',
  `update_by`                   INT            NULL                                             COMMENT '更新人',
  `is_delete`                  TINYINT        NOT NULL DEFAULT 0                               COMMENT '软删 0=正常 1=已删(仅service写,前端删传_id)',
  PRIMARY KEY (`_id`),
  UNIQUE KEY `uk_order_sn` (`order_sn`),
  KEY `idx_offline_customer_id` (`offline_customer_id`),
  KEY `idx_settlement_method` (`settlement_method`),
  KEY `idx_create_time` (`create_time`),
  KEY `idx_sales_user_id` (`sales_user_id`),
  KEY `idx_status_approval` (`status`, `current_chain_code`, `current_step`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单主表';


-- -----------------------------------------------------------------------------
-- §4.1b data_distribution_order_snapshot（客户/联系人/地址/合同扩展快照，与主表 1:1）
-- 主表保留：客户 id/编码/国家/类型、预付、settlement_method（列表筛选）；其余第一阶段展示快照落本表
-- draft/save 与插入主表同事务写入；拆单子单复制父单快照行（业务待定）
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_snapshot` (
  `order_id`                    BIGINT         NOT NULL                                         COMMENT '主单 data_distribution_order._id',
  -- ── 联系人快照 ─────────────────────────────────────────────────────────────
  `name`                        VARCHAR(128)   NULL                                             COMMENT '联系人姓名快照(主仓 name)',
  `position`                    VARCHAR(128)   NULL                                             COMMENT '联系人职位快照',
  `info`                        VARCHAR(64)    NULL                                             COMMENT '联系方式快照',
  `contact_remark`              VARCHAR(1024)  NULL                                             COMMENT '联系人备注快照',
  -- ── 地址快照 ───────────────────────────────────────────────────────────────
  `country`                     VARCHAR(64)    NULL                                             COMMENT '地址-国家快照',
  `province`                    VARCHAR(128)   NULL                                             COMMENT '地址-省/州快照',
  `city`                        VARCHAR(128)   NULL                                             COMMENT '地址-城市快照',
  `district`                    VARCHAR(128)   NULL                                             COMMENT '地址-县/区快照',
  `address`                     VARCHAR(1024)  NULL                                             COMMENT '地址-详细地址快照',
  `post_code`                   VARCHAR(32)    NULL                                             COMMENT '地址-邮编快照',
  `address_remark`              VARCHAR(1024)  NULL                                             COMMENT '地址-备注快照',
  -- ── 合同扩展快照（预付 is_prepayment/prepayment_ratio 在主表）────────────────
  `contract_no`                 VARCHAR(64)    NULL                                             COMMENT '合同编号快照',
  `contract_effective_start`    DATE           NULL                                             COMMENT '合同生效起',
  `effective_end`               DATE           NULL                                             COMMENT '合同生效止',
  `owner_staff_id`              BIGINT         NULL                                             COMMENT '签订负责人用户_id；展示名读时解析',
  `uncond_rebate_ratio`         DECIMAL(9, 4)  NULL                                             COMMENT '无条件返利比例快照',
  `settlement_days`             INT            NULL                                             COMMENT '账期天数快照',
  `settlement_currency`         VARCHAR(12)    NULL                                             COMMENT '结算币种快照(主仓 settlement_currency)',
  `delivery_method`             SMALLINT       NULL                                             COMMENT '配送方式编码快照 1=在指定地点交付 2=在配送中心交付 3=客户自提',
  `mt_delivery_mode`            INT            NULL                                             COMMENT '交付方式 1=一次性 2=多批',
  `carrier`                     VARCHAR(128)   NULL                                             COMMENT '运输物流商快照',
  `delivery_remark`             TEXT           NULL                                             COMMENT '运输配送备注快照',
  `sample_policy`               SMALLINT       NULL                                             COMMENT '样品政策编码快照 1=免费供样 2=折扣供样',
  `sample_discount`             DECIMAL(9, 4)  NULL                                             COMMENT '样品折扣快照',
  `delivery_fee_payment`        SMALLINT       NULL                                             COMMENT '合同运费承担方编码快照 1=Simplus Pay 2=Customer Pay',
  `bank_account_confirmation`   JSON           NULL                                             COMMENT '银行账户JSON快照(合同 bank_account_confirmation)',
  `create_time`                 DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`                 DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单扩展快照(1:1主表)';


-- -----------------------------------------------------------------------------
-- §4.2 data_distribution_order_quote_detail（报价明细表，每 SKU 一行）
-- 【第一阶段配套】与 §4.1 第一阶段主表字段同时维护（status=10/20）
-- 须在本表填完报价行后，方可进入第二阶段主表字段及 §4.3 订单明细；提交报价审核前必填
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_quote_detail` (
  `_id`                   BIGINT         NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `order_id`              BIGINT         NOT NULL                                         COMMENT '主单 data_distribution_order._id',
  `sku`                   VARCHAR(64)    NOT NULL DEFAULT ''                              COMMENT 'SKU编码',
  `price_with_vat`        DECIMAL(18, 4) NULL                                             COMMENT '含增值税报价',
  `price_without_vat`     DECIMAL(18, 4) NULL                                             COMMENT '不含增值税单价快照',
  `qty`                   INT            NULL                                             COMMENT '销售数量',
  `guide_price`           DECIMAL(18, 4) NULL                                             COMMENT '指导价快照',
  `red_line_price`        DECIMAL(18, 4) NULL                                             COMMENT '红线价快照',
  `amount_with_vat`       DECIMAL(18, 2) NULL                                             COMMENT '含增值税行总额',
  `amount_without_vat`    DECIMAL(18, 2) NULL                                             COMMENT '不含增值税行总额',
  `vat_amount`            DECIMAL(18, 2) NULL                                             COMMENT '行VAT税额',
  `stock_on_hand`         INT            NULL                                             COMMENT '在库库存快照',
  `stock_in_transit`      INT            NULL                                             COMMENT '在途库存快照',
  `stock_planned`         INT            NULL                                             COMMENT '计划库存快照',
  `create_time`           DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`           DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_delete`            TINYINT        NOT NULL DEFAULT 0                               COMMENT '软删 0=正常 1=已删(删行传_id)',
  PRIMARY KEY (`_id`),
  KEY `idx_order_alive` (`order_id`, `is_delete`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单报价明细(每SKU报价)';


-- -----------------------------------------------------------------------------
-- §4.3 data_distribution_order_item_detail（订单明细表，每 SKU 一行）
-- 【第二阶段】status≥30 订单创建及之后维护；与 §4.2 报价明细独立录入，不自动复制
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_item_detail` (
  `_id`                      BIGINT         NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `order_id`                 BIGINT         NOT NULL                                         COMMENT '主单 data_distribution_order._id',
  `sku`                      VARCHAR(64)    NOT NULL DEFAULT ''                              COMMENT 'SKU编码',
  `price_with_vat`           DECIMAL(18, 4) NULL                                             COMMENT '含增值税单价',
  `price_without_vat`        DECIMAL(18, 4) NULL                                             COMMENT '不含增值税单价快照',
  `qty`                      INT            NULL                                             COMMENT '销售数量',
  `guide_price`              DECIMAL(18, 4) NULL                                             COMMENT '指导价快照',
  `red_line_price`           DECIMAL(18, 4) NULL                                             COMMENT '红线价快照',
  `amount_with_vat`          DECIMAL(18, 2) NULL                                             COMMENT '含增值税行总额',
  `amount_without_vat`       DECIMAL(18, 2) NULL                                             COMMENT '不含增值税行总额',
  `freight_with_vat`         DECIMAL(18, 2) NULL                                             COMMENT '含增值税运费收入(提交审核分摊)',
  `freight_without_vat`      DECIMAL(18, 2) NULL                                             COMMENT '不含增值税运费收入(提交审核分摊)',
  `order_amount_with_vat`    DECIMAL(18, 2) NULL                                             COMMENT '含增值税订单总额 amount_with_vat+freight_with_vat',
  `order_amount_without_vat` DECIMAL(18, 2) NULL                                             COMMENT '不含增值税订单总额 amount_without_vat+freight_without_vat',
  `vat_amount`               DECIMAL(18, 2) NULL                                             COMMENT '行VAT税额',
  `stock_on_hand`            INT            NULL                                             COMMENT '可用在库库存快照',
  `stock_in_transit`         INT            NULL                                             COMMENT '在途库存快照',
  `stock_planned`            INT            NULL                                             COMMENT '计划库存快照',
  `is_protocol_sample`       SMALLINT       NOT NULL DEFAULT 0                               COMMENT '是否协议样品 0=否 1=是',
  `quote_check_passed`       SMALLINT       NOT NULL DEFAULT 0                               COMMENT '报价校验是否通过 0=未通过 1=已通过',
  `dispatched_qty`           INT            NOT NULL DEFAULT 0                               COMMENT '已拆/已下发累计数量（拆单事务内原子+1）',
  `received_qty`             INT            NULL                                             COMMENT '实收数量',
  `receive_diff_remark`      VARCHAR(800)   NULL                                             COMMENT '实收差异原因',
  `dispatch_stock_on_hand`   INT            NULL                                             COMMENT '下发时在库可用库存快照',
  `create_time`              DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`              DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_delete`               TINYINT        NOT NULL DEFAULT 0                               COMMENT '软删 0=正常 1=已删(删行传_id)',
  PRIMARY KEY (`_id`),
  KEY `idx_order_id` (`order_id`),
  KEY `idx_order_alive` (`order_id`, `is_delete`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单明细(订单创建阶段每SKU)';


-- -----------------------------------------------------------------------------
-- §4.4 data_distribution_order_approval_config（审批链配置）
-- chain_code: 1=定价审批 2=订单审批-标准(<5000USD) 3=订单审批-大额(≥5000USD)
-- approver_type: 1=直线上级(动态) 2=办事角色(role_id)
-- chain=1 与 chain=2/3 环节逻辑不同：定价链为「定价审批人-1/2/3」办事角色逐级；订单链为直线上级+分销主管(+CEO)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_approval_config` (
  `_id`           BIGINT       NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `chain_code`    SMALLINT     NOT NULL                                         COMMENT '审批链 1=定价审批 2=订单审批-标准 3=订单审批-大额',
  `step_no`       INT          NOT NULL                                         COMMENT '环节序号 1..N，同 chain_code 内唯一，从1递增',
  `approver_type` SMALLINT     NOT NULL DEFAULT 2                               COMMENT '审核人类型 1=直线上级(动态解析) 2=办事角色(用role_id)',
  `role_id`       INT          NOT NULL DEFAULT 0                               COMMENT '办事角色ID(business_role.role_id)；approver_type=1时填0',
  `role_name`     VARCHAR(64)  NOT NULL DEFAULT ''                              COMMENT '角色名称（冗余展示用，如"分销主管""CEO"或"直线上级"）',
  `is_active`     SMALLINT     NOT NULL DEFAULT 1                               COMMENT '是否启用 0=停用 1=启用',
  `create_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`_id`),
  UNIQUE KEY `uk_distribution_order_approval_chain_step` (`chain_code`, `step_no`),
  KEY `idx_distribution_order_approval_active` (`is_active`, `chain_code`, `step_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单审批链配置';


-- -----------------------------------------------------------------------------
-- §4.5 data_distribution_order_status_log（主状态迁移日志）
-- action_code / operator_role / trigger_type 见 design.md 附录 A
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_status_log` (
  `_id`                        BIGINT   NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `order_id`                   BIGINT   NOT NULL                                         COMMENT '主单 data_distribution_order._id',
  `from_status`                INT      NULL                                             COMMENT '变更前主状态（10=草稿 20=报价审核 30=订单创建 40=订单审核 50=确认预付 60=待下发 70=履约中 80=待回款 90=已完成 99=已作废）；首条可为NULL',
  `to_status`                  INT      NOT NULL                                         COMMENT '变更后主状态（同 from_status 枚举）',
  `action_code`                INT      NULL                                             COMMENT '业务动作 10=提交报价审核 11=报价通过 12=报价驳回 13=撤回报价 20=提交订单审核 21=订单通过 22=订单驳回 23=撤回订单 30=确认预付 40=下发千易 41=拆单 50=确认实收 60=确认回款 90=作废 91=保存草稿',
  `operator_id`                BIGINT   NULL                                             COMMENT '操作人用户主键；系统触发填0',
  `operator_role`              INT      NULL                                             COMMENT '操作人角色 1=发起人 2=审核人 3=管理员 4=系统',
  `trigger_type`               INT      NOT NULL                                         COMMENT '触发方式 1=人工 2=定时 3=审核链路 4=系统其他',
  `remark`                     TEXT     NULL                                             COMMENT '补充说明（驳回原因、撤回说明等）',
  `from_chain_code`            SMALLINT NULL                                             COMMENT '变更前审批链（1=定价 2=订单标准 3=订单大额）；非审核动作为NULL',
  `to_chain_code`              SMALLINT NULL                                             COMMENT '变更后审批链（1=定价 2=订单标准 3=订单大额）；离开审核态为NULL',
  `from_step`                  INT      NULL                                             COMMENT '变更前环节序号（对应 approval_config.step_no）；非审核动作为NULL',
  `to_step`                    INT      NULL                                             COMMENT '变更后环节序号；终审通过/撤回/离开审核态为NULL',
  `role_name`                  VARCHAR(64) NULL                                          COMMENT '本步办事角色名称快照(approval_config.role_name)；非审核动作为NULL',
  `create_time`                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '状态切换完成时间',
  PRIMARY KEY (`_id`),
  KEY `idx_order_id` (`order_id`),
  KEY `idx_order_id_time` (`order_id`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单主状态每次合法迁移一条';


-- -----------------------------------------------------------------------------
-- §4.6 data_distribution_order_adjustment（手工调整）
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_adjustment` (
  `_id`                    BIGINT         NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `order_id`               BIGINT         NOT NULL                                         COMMENT '订单主键',
  `seq`                    INT            NOT NULL DEFAULT 1                               COMMENT '序号（同 order_id 内递增，UNIQUE(order_id, seq)',
  `adjust_amount`          DECIMAL(18, 2) NOT NULL DEFAULT 0.00                           COMMENT '手工调整金额',
  `fee_category_id`        BIGINT         NULL                                             COMMENT '费用项类目ID',
  `document_attachments`   JSON           NULL                                             COMMENT '单据附件',
  `remark`                 VARCHAR(800)   NULL                                             COMMENT '手工调整备注',
  `adjusted_balance_after` DECIMAL(18, 2) NULL                                             COMMENT '本条后调整后尾款应收',
  `create_time`            DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`            DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `create_by`              INT            NULL                                             COMMENT '创建人',
  PRIMARY KEY (`_id`),
  KEY `idx_order_id` (`order_id`),
  UNIQUE KEY `uk_order_seq` (`order_id`, `seq`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单手工调整';


-- -----------------------------------------------------------------------------
-- §4.7a data_distribution_order_prepayment（预付款确认记录）
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_prepayment` (
  `_id`               BIGINT         NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `order_id`          BIGINT         NOT NULL                                         COMMENT '订单主键 data_distribution_order._id',
  `amount_due`        DECIMAL(18, 2) NULL                                             COMMENT '应付预付款',
  `amount_paid`       DECIMAL(18, 2) NULL                                             COMMENT '实付预付款',
  `payment_date`      DATE           NULL                                             COMMENT '支付日期',
  `diff_remark`       VARCHAR(800)   NULL                                             COMMENT '差异备注（PRD 800字）',
  `attachments`       JSON           NULL                                             COMMENT '水单附件',
  `system_tracking_number` VARCHAR(64) NULL                                             COMMENT '千易单号快照（确认时从主单同步）',
  `create_time`       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `create_by`         INT            NULL                                             COMMENT '确认人_id',
  PRIMARY KEY (`_id`),
  UNIQUE KEY `uk_order_id` (`order_id`),
  KEY `idx_order_id` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单预付款确认记录';


-- -----------------------------------------------------------------------------
-- §4.7b data_distribution_order_balance_payment（回款确认记录）
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `internal_app`.`data_distribution_order_balance_payment` (
  `_id`               BIGINT         NOT NULL AUTO_INCREMENT                          COMMENT '主键',
  `order_id`          BIGINT         NOT NULL                                         COMMENT '订单主键 data_distribution_order._id',
  `amount_due`        DECIMAL(18, 2) NULL                                             COMMENT '应付尾款（含调整后）',
  `amount_paid`       DECIMAL(18, 2) NULL                                             COMMENT '实付尾款',
  `payment_date`      DATE           NULL                                             COMMENT '回款日期',
  `diff_remark`       VARCHAR(800)   NULL                                             COMMENT '差异备注（PRD 800字）',
  `attachments`       JSON           NULL                                             COMMENT '水单附件',
  `system_tracking_number` VARCHAR(64) NULL                                             COMMENT '千易单号快照（确认时从主单同步）',
  `create_time`       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP               COMMENT '创建时间',
  `update_time`       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `create_by`         INT            NULL                                             COMMENT '确认人_id',
  PRIMARY KEY (`_id`),
  UNIQUE KEY `uk_order_id` (`order_id`),
  KEY `idx_order_id` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分销订单尾款确认记录';


-- -----------------------------------------------------------------------------
-- 初始数据：审批链配置（role_id 需按主仓 business_role 实际 ID 替换后执行）
-- chain=1：定价审批人-1 → 定价审批人-2 → 定价审批人-3（均为办事角色 approver_type=2）
-- chain=2/3：订单审批（直线上级 → 分销主管；大额加 CEO）
-- -----------------------------------------------------------------------------
-- INSERT INTO internal_app.data_distribution_order_approval_config
--   (chain_code, step_no, approver_type, role_id, role_name) VALUES
-- (1, 1, 1, 0, '直线上级'),
-- (1, 2, 2, 0, '分销主管'),
-- (2, 1, 1, 0, '直线上级'),
-- (2, 2, 2, 0, '分销主管'),
-- (3, 1, 1, 0, '直线上级'),
-- (3, 2, 2, 0, '分销主管'),
-- (3, 3, 3, 0, 'TH分销负责人'),
-- (3, 4, 4, 0, 'CEO');

-- 存量库迁移：submit_by（提交审核发起人）
-- ALTER TABLE internal_app.data_distribution_order
--   ADD COLUMN `submit_by` INT NULL COMMENT '提交审核发起人(报价/订单 submit 时写入)' AFTER `create_by`;
