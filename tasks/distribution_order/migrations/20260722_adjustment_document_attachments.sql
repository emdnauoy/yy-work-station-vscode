-- 手工调整：单据附件（NormalizedJSON，与 customer_po_attachments 同类）
ALTER TABLE `internal_app`.`data_distribution_order_adjustment`
  ADD COLUMN `document_attachments` JSON NULL COMMENT '单据附件' AFTER `fee_category_id`;
