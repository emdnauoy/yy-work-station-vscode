# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : constants.py
# @Description : 分销订单状态与展示文案
"""
from decimal import Decimal

from apps.system.distribution_order.distribution_order_workflow_engine import (
    STATUS_COMPLETED,
    STATUS_DRAFT,
    STATUS_FULFILLING,
    STATUS_ORDER_CREATE,
    STATUS_ORDER_REVIEW,
    STATUS_PENDING_DISPATCH,
    STATUS_PENDING_PAYMENT,
    STATUS_PREPAY,
    STATUS_QUOTE_REVIEW,
    STATUS_VOIDED,
)

STATUS_LABELS = {
    STATUS_DRAFT: "草稿",
    STATUS_QUOTE_REVIEW: "报价审核",
    STATUS_ORDER_CREATE: "订单创建",
    STATUS_ORDER_REVIEW: "订单审核",
    STATUS_PREPAY: "确认预付",
    STATUS_PENDING_DISPATCH: "待下发",
    STATUS_FULFILLING: "履约中",
    STATUS_PENDING_PAYMENT: "待回款",
    STATUS_COMPLETED: "已完成",
    STATUS_VOIDED: "已作废",
}

# 主单创建来源 create_source
CREATE_SOURCE_NORMAL = 0
CREATE_SOURCE_BATCH_DROPSHIP = 1
CREATE_SOURCE_LABELS = {
    CREATE_SOURCE_NORMAL: "普通",
    CREATE_SOURCE_BATCH_DROPSHIP: "一件代发批量",
}

# 线下客户合作方式 OfflineCustomer.cooperation_method
COOPERATION_METHOD_WHOLESALE = 1
COOPERATION_METHOD_DROPSHIP = 2
COOPERATION_METHOD_LABELS = {
    COOPERATION_METHOD_WHOLESALE: "批发",
    COOPERATION_METHOD_DROPSHIP: "一件代发",
}

EDITABLE_DRAFT_STATUSES = (STATUS_DRAFT,)

# 作废：仅草稿、订单创建
VOID_ALLOWED_STATUSES = (STATUS_DRAFT, STATUS_ORDER_CREATE)

# 明细行可编辑主状态（报价/订单分表，逻辑共用 line_service）
EDITABLE_QUOTE_DETAIL_STATUSES = (STATUS_DRAFT,)
EDITABLE_ORDER_DETAIL_STATUSES = (STATUS_ORDER_CREATE,)

# 手工调整：确认预付 ~ 待回款（确认回款前）
ADJUSTMENT_ALLOWED_STATUSES = (
    STATUS_PREPAY,
    STATUS_PENDING_DISPATCH,
    STATUS_FULFILLING,
    STATUS_PENDING_PAYMENT,
)

# 列表/详情行操作按钮 value（与前端约定一致）
STATUS_BUTTON_LIST = {
    # 草稿：提交报价审核、编辑、详情、作废、操作记录
    STATUS_DRAFT: [
        "quote_submit", "edit", "select", "terminate", "log",
    ],
    # 报价审核：审核、详情、撤回、操作记录
    STATUS_QUOTE_REVIEW: [
        "quote_review", "select", "quote_withdraw", "terminate", "log",
    ],
    # 订单创建：提交订单审核、编辑、详情、作废、操作记录
    STATUS_ORDER_CREATE: [
        "order_submit", "edit", "select", "terminate", "log",
    ],
    # 订单审核：审核、详情、撤回、操作记录
    STATUS_ORDER_REVIEW: [
        "order_review", "select", "order_withdraw", "terminate", "log",
    ],
    # 确认预付：确认预付、详情、操作记录
    STATUS_PREPAY: [
        "prepay_confirm", "adjust",  "select", "terminate", "log",
    ],
    # 待下发：下发、拆单、详情、操作记录
    STATUS_PENDING_DISPATCH: [
        "dispatch", "split", "adjust", "select", "terminate", "log",
    ],
    # 履约中：确认实收、详情、操作记录
    STATUS_FULFILLING: [
        "receive_confirm", "adjust", "select", "log",
    ],
    # 待回款：确认回款、详情、操作记录
    STATUS_PENDING_PAYMENT: [
        "payment_confirm", "adjust", "select", "log",
    ],
    # 已完成 / 已作废：详情、操作记录
    STATUS_COMPLETED: ["select", "log"],
    STATUS_VOIDED: ["select", "log"],
}

# 全量按钮元数据（前端下拉/权限配置用；loading=1 表示需异步鉴权）
ORDER_ACTION_BUTTONS = [
    {"label": "详情", "value": "select", "loading": 1},
    {"label": "编辑", "value": "edit", "loading": 1},
    {"label": "提交审核(报价)", "value": "quote_submit", "loading": 1},
    {"label": "审核(报价)", "value": "quote_review", "loading": 1},
    {"label": "撤回审核(报价)", "value": "quote_withdraw", "loading": 1},
    {"label": "提交审核(订单)", "value": "order_submit", "loading": 1},
    {"label": "审核(订单)", "value": "order_review", "loading": 1},
    {"label": "撤回审核(订单)", "value": "order_withdraw", "loading": 1},
    {"label": "确认预付", "value": "prepay_confirm", "loading": 1},
    {"label": "确认实收", "value": "receive_confirm", "loading": 1},
    {"label": "确认回款", "value": "payment_confirm", "loading": 1},
    {"label": "下发", "value": "dispatch", "loading": 1},
    {"label": "拆单", "value": "split", "loading": 1},
    {"label": "作废", "value": "terminate", "loading": 1},
    {"label": "操作记录", "value": "log", "loading": 1},
    {"label": "手工调整", "value": "adjust", "loading": 1},
]

# 列表标签位图（与 schema.sql / models.tags_bitmask 注释一致）
TAG_PRICE_DEVIATION = 1
TAG_LARGE_AMOUNT = 2
TAG_SAMPLE = 4
TAG_OUT_OF_STOCK = 8
TAG_SPLIT = 16
TAG_SPECIAL_OPS = 32
TAG_URGENT = 64
TAG_RECEIVE_DIFF = 128
TAG_PAYMENT_OVERDUE = 256

TAG_BITS = (
    TAG_PRICE_DEVIATION,
    TAG_LARGE_AMOUNT,
    TAG_SAMPLE,
    TAG_OUT_OF_STOCK,
    TAG_SPLIT,
    TAG_SPECIAL_OPS,
    TAG_URGENT,
    TAG_RECEIVE_DIFF,
    TAG_PAYMENT_OVERDUE,
)

TAG_LABELS = {
    TAG_PRICE_DEVIATION: "价偏",
    TAG_LARGE_AMOUNT: "大额",
    TAG_SAMPLE: "样品",
    TAG_OUT_OF_STOCK: "缺货",
    TAG_SPLIT: "拆单",
    TAG_SPECIAL_OPS: "特殊作业",
    TAG_URGENT: "紧急",
    TAG_RECEIVE_DIFF: "实收差异",
    TAG_PAYMENT_OVERDUE: "回款超期",
}

TAG_FILTER_OPTIONS = [
    {"label": TAG_LABELS[bit], "value": bit} for bit in TAG_BITS
]

LARGE_AMOUNT_USD_THRESHOLD = Decimal("5000")
