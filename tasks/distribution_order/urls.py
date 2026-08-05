# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/26
# @Author  : Zhu Yaming
# @File    : urls.py
# @Description : 分销订单路由（主单/明细/履约占位）
"""
from fastapi import APIRouter

from apps.system.distribution_order.views.distribution_order import (
    distribution_order_create_save,
    distribution_order_detail,
    distribution_order_draft_save,
    distribution_order_execute_user_options,
    distribution_order_list,
    distribution_history_order_list,
    distribution_order_remark_save,
    distribution_order_void,
)
from apps.system.distribution_order.views.distribution_order_fulfillment import (
    distribution_order_adjustment_add,
    distribution_order_adjustment_save,
    distribution_order_dispatch,
    distribution_order_payment_confirm,
    distribution_order_prepay_confirm,
    distribution_order_receive_confirm,
    distribution_order_split,
)
from apps.system.distribution_order.views.distribution_order_approve import (
    distribution_order_approval_flow,
    distribution_order_approval_order_approve,
    distribution_order_approval_order_flow,
    distribution_order_approval_order_reject,
    distribution_order_approval_order_withdraw,
    distribution_order_approval_quote_approve,
    distribution_order_approval_quote_flow,
    distribution_order_approval_quote_reject,
    distribution_order_approval_quote_withdraw,
    distribution_order_order_submit,
    distribution_order_quote_submit,
)
from apps.system.distribution_order.views.distribution_order_log import get_distribution_order_logs
from apps.system.distribution_order.views.distribution_order_line import (
    distribution_order_order_details_delete,
    distribution_order_order_details_import,
    distribution_order_order_details_list,
    distribution_order_order_details_save,
    distribution_order_order_details_template,
    distribution_order_quote_details_delete,
    distribution_order_quote_details_import,
    distribution_order_quote_details_list,
    distribution_order_quote_details_save,
    distribution_order_quote_details_template,
)
from apps.system.distribution_order.views.distribution_order_batch import (
    distribution_order_batch_approve,
    distribution_order_batch_dispatch,
    distribution_order_batch_parse,
    distribution_order_batch_submit,
    distribution_order_batch_template,
    distribution_order_dropship_customers,
    distribution_order_framework_quote_get,
    distribution_order_framework_quote_save,
)

distribution_order_api = APIRouter(tags=["distribution_order"])

# 一件代发：框架报价 / 批量建单 / 批量审核 / 批量下发 路由见下方

distribution_order_api.get("/distribution_order/list/", summary="分销订单列表")(distribution_order_list)
distribution_order_api.get("/distribution_order/meta/execute_users/", summary="当前执行人筛选项")(distribution_order_execute_user_options)
distribution_order_api.get("/distribution_order/detail/", summary="分销订单详情")(distribution_order_detail)
distribution_order_api.get("/distribution_order/logs/detail/", summary="分销订单操作日志 refer_id=主单_id")(get_distribution_order_logs)
distribution_order_api.post("/distribution_order/draft/save/", summary="保存分销订单草稿（报价阶段）")(distribution_order_draft_save)
distribution_order_api.post("/distribution_order/order/save/", summary="订单创建阶段保存")(distribution_order_create_save)
distribution_order_api.post("/distribution_order/terminate/", summary="订单作废（草稿/订单创建）")(distribution_order_void)
distribution_order_api.post("/distribution_order/remark/save/", summary="修改订单备注（不限阶段）")(distribution_order_remark_save)
distribution_order_api.get("/distribution_order/quote_details/", summary="报价明细列表")(distribution_order_quote_details_list)
distribution_order_api.post("/distribution_order/quote_details/save/", summary="报价明细批量保存")(distribution_order_quote_details_save)
distribution_order_api.post("/distribution_order/quote_details/delete/", summary="报价明细批量软删")(distribution_order_quote_details_delete)
distribution_order_api.get(
    "/distribution_order/quote_details/template/",
    summary="报价明细导入模板下载（含历史明细）",
    response_model=None,
)(distribution_order_quote_details_template)
distribution_order_api.post("/distribution_order/quote_details/import/", summary="报价明细批量导入")(distribution_order_quote_details_import)
distribution_order_api.get("/distribution_order/order_details/", summary="订单明细列表")(distribution_order_order_details_list)
distribution_order_api.post("/distribution_order/order_details/save/", summary="订单明细批量保存")(distribution_order_order_details_save)
distribution_order_api.post("/distribution_order/order_details/delete/", summary="订单明细批量软删")(distribution_order_order_details_delete)
distribution_order_api.get(
    "/distribution_order/order_details/template/",
    summary="订单明细导入模板下载（含已有明细）",
    response_model=None,
)(distribution_order_order_details_template)
distribution_order_api.post("/distribution_order/order_details/import/", summary="订单明细批量导入")(distribution_order_order_details_import)
distribution_order_api.post("/distribution_order/prepay/confirm/", summary="确认预付")(distribution_order_prepay_confirm)
distribution_order_api.post("/distribution_order/dispatch/", summary="下发千易")(distribution_order_dispatch)
distribution_order_api.post("/distribution_order/receive/confirm/", summary="确认实收")(distribution_order_receive_confirm)
distribution_order_api.post("/distribution_order/payment/confirm/", summary="确认回款")(distribution_order_payment_confirm)
distribution_order_api.post("/distribution_order/split/", summary="拆单")(distribution_order_split)
distribution_order_api.post("/distribution_order/adjustment/save/", summary="手工调整批量保存")(distribution_order_adjustment_save)
distribution_order_api.post("/distribution_order/adjustment/add/", summary="新增手工调整")(distribution_order_adjustment_add)
distribution_order_api.get("/distribution_order/approval/flow/", summary="审批流（报价+订单已审历史，含审核类型）")(distribution_order_approval_flow)
distribution_order_api.get("/distribution_order/approval/quote/flow/", summary="报价审批流")(distribution_order_approval_quote_flow)
distribution_order_api.get("/distribution_order/approval/order/flow/", summary="订单审批流")(distribution_order_approval_order_flow)
distribution_order_api.post("/distribution_order/quote/submit/", summary="提交报价审核")(distribution_order_quote_submit)
distribution_order_api.post("/distribution_order/order/submit/", summary="提交订单审核")(distribution_order_order_submit)
distribution_order_api.post("/distribution_order/approval/quote/approve/", summary="报价审核通过（可填备注）")(distribution_order_approval_quote_approve)
distribution_order_api.post("/distribution_order/approval/quote/reject/", summary="报价审核驳回")(distribution_order_approval_quote_reject)
distribution_order_api.post("/distribution_order/approval/quote/withdraw/", summary="撤回报价审核")(distribution_order_approval_quote_withdraw)
distribution_order_api.post("/distribution_order/approval/order/approve/", summary="订单审核通过（可填备注）")(distribution_order_approval_order_approve)
distribution_order_api.post("/distribution_order/approval/order/reject/", summary="订单审核驳回")(distribution_order_approval_order_reject)
distribution_order_api.post("/distribution_order/approval/order/withdraw/", summary="撤回订单审核")(distribution_order_approval_order_withdraw)
distribution_order_api.get("/distribution_order/history/list/", summary="历史订单列表")(distribution_history_order_list)
distribution_order_api.get("/distribution_order/batch/dropship_customers/", summary="一件代发客户下拉")(distribution_order_dropship_customers)
distribution_order_api.get("/distribution_order/framework_quote/", summary="框架报价详情")(distribution_order_framework_quote_get)
distribution_order_api.post("/distribution_order/framework_quote/save/", summary="框架报价保存")(distribution_order_framework_quote_save)
distribution_order_api.get(
    "/distribution_order/batch/template/",
    summary="一件代发批量导入模板下载",
    response_model=None,
)(distribution_order_batch_template)
distribution_order_api.post("/distribution_order/batch/parse/", summary="一件代发批量上传解析（不落库）")(distribution_order_batch_parse)
distribution_order_api.post("/distribution_order/batch/submit/", summary="一件代发批量提交审核")(distribution_order_batch_submit)
distribution_order_api.post("/distribution_order/batch/approve/", summary="批量订单审核通过")(distribution_order_batch_approve)
distribution_order_api.post("/distribution_order/batch/dispatch/", summary="批量下发千易（库存不足跳过）")(distribution_order_batch_dispatch)
