-- -----------------------------------------------------------------------------
-- 分销下单 yy_permission 初始数据
-- 与 constants.STATUS_BUTTON_LIST / ORDER_ACTION_BUTTONS、需求文档 §2.4 对齐
-- permission_code 与前端按钮 value、列表 status 筛选项一致
-- 执行前请确认主仓是否已有同 permission_type + permission_code 记录，避免重复插入
-- -----------------------------------------------------------------------------

-- §1 列表 Tab 权限（按主状态可见性；permission_code = 主表 status）
INSERT INTO internal_app.yy_permission (
    permission_code, permission_code_desc,
    permission_type, permission_type_desc,
    permission_seq, invalid_ind, data_type
) VALUES
('10',  '草稿',     'tab', '分销下单状态', 10, 0, 0),
('20',  '报价审核', 'tab', '分销下单状态', 20, 0, 0),
('30',  '订单创建', 'tab', '分销下单状态', 30, 0, 0),
('40',  '订单审核', 'tab', '分销下单状态', 40, 0, 0),
('50',  '确认预付', 'tab', '分销下单状态', 50, 0, 0),
('60',  '待下发',   'tab', '分销下单状态', 60, 0, 0),
('70',  '履约中',   'tab', '分销下单状态', 70, 0, 0),
('80',  '待回款',   'tab', '分销下单状态', 80, 0, 0),
('90',  '已完成',   'tab', '分销下单状态', 90, 0, 0),
('99',  '已作废',   'tab', '分销下单状态', 99, 0, 0);

-- §2 行操作权限（与详情 button_list / ORDER_ACTION_BUTTONS.value 一致）
INSERT INTO internal_app.yy_permission (
    permission_code, permission_code_desc,
    permission_type, permission_type_desc,
    permission_seq, invalid_ind, data_type
) VALUES
('select',          '详情',           'tab1', '分销下单操作',  1, 0, 0),
('edit',            '编辑',           'tab1', '分销下单操作',  2, 0, 0),
('quote_submit',    '提交审核(报价)', 'tab1', '分销下单操作',  3, 0, 0),
('quote_review',    '审核(报价)',     'tab1', '分销下单操作',  4, 0, 0),
('quote_withdraw',  '撤回审核(报价)', 'tab1', '分销下单操作',  5, 0, 0),
('order_submit',    '提交审核(订单)', 'tab1', '分销下单操作',  6, 0, 0),
('order_review',    '审核(订单)',     'tab1', '分销下单操作',  7, 0, 0),
('order_withdraw',  '撤回审核(订单)', 'tab1', '分销下单操作',  8, 0, 0),
('prepay_confirm',  '确认预付',       'tab1', '分销下单操作',  9, 0, 0),
('receive_confirm', '确认实收',       'tab1', '分销下单操作', 10, 0, 0),
('payment_confirm', '确认回款',       'tab1', '分销下单操作', 11, 0, 0),
('dispatch',        '下发',           'tab1', '分销下单操作', 12, 0, 0),
('split',           '拆单',           'tab1', '分销下单操作', 13, 0, 0),
('terminate',       '作废',           'tab1', '分销下单操作', 14, 0, 0),
('log',             '操作记录',       'tab1', '分销下单操作', 15, 0, 0);
