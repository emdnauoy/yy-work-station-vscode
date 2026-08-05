-- 作废前主状态快照：status=99 时可通过 void_from_status 知悉作废前所处阶段
ALTER TABLE internal_app.data_distribution_order
  ADD COLUMN `void_from_status` SMALLINT NULL
    COMMENT '作废前主状态(10草稿…90已完成)；仅 status=99 时有值'
    AFTER `status`;

-- 历史已作废单：取最新一条作废日志的 from_status 回填
UPDATE internal_app.data_distribution_order o
INNER JOIN (
    SELECT l.order_id, l.from_status
    FROM internal_app.data_distribution_order_status_log l
    INNER JOIN (
        SELECT order_id, MAX(_id) AS max_id
        FROM internal_app.data_distribution_order_status_log
        WHERE action_code = 90 AND to_status = 99
        GROUP BY order_id
    ) latest ON l._id = latest.max_id
) v ON o._id = v.order_id
SET o.void_from_status = v.from_status
WHERE o.status = 99;
