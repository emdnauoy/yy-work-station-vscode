# -*- coding:utf-8-*-
# @FileName : urls.py
# @Time     : 2024/11/25 17:06
# @Author   : yuhaiping
# @Email    : ping.yu@yaoyao-inc.com
# @Software : PyCharm
from fastapi import APIRouter

from apps.system.offline_customer.view.sys_offline_customers_view import (get_sys_offline_customers_list, get_active_offline_customers,\
    get_sys_offline_customers_detail, update_sys_offline_customers, get_sys_operator_logs, get_sys_offline_customers_contract_detail,\
    add_offline_customer_followup_record, get_offline_customer_followup_record_list, get_offline_customer_contacts,
    delete_offline_customer_contact, update_offline_customer_contact, add_offline_customer_contact, update_customer_address,
    offline_customer_execute_user_options)

from apps.system.offline_customer.view.sys_offline_sku_view import (create_offline_customer_sku, batch_update_offline_customer_sku, get_offline_customer_skus,
        download_offline_customer_excel_template, upload_offline_customer_sku, get_offline_customer_detail, get_offline_logs)
from apps.system.offline_customer.view.sys_offline_sell_out_sales import upload_offline_sell_out_sales, batch_update_offline_sales, get_offline_customer_slaes_list,batch_disabel_customer_slaes
from apps.system.offline_customer.view.sys_offline_sell_out_stock import upload_offline_sell_out_stock, batch_update_offline_stock, get_offline_customer_stock_list,batch_disabel_customer_stock
from apps.system.offline_customer.view.update_offline_sell_out import sync_offline_sell_out_data, get_task_status, get_latest_offline_task, get_all_task_status

from apps.system.offline_customer.view.sys_offline_contract_view import (
    offline_contract_list,
    offline_contract_detail,
    offline_contract_create,
    offline_contract_update,
    offline_contract_delete,
    get_conract_category_fee_list,
    get_contract_operator_logs
)
from apps.system.offline_customer.view.sys_offline_contract_approve import (
    submit_contract,reject_contract, withdraw_contract, resubmit_contract, approve_contract, get_workflow, terminate_contract
)

sys_offline_customer_api = APIRouter()

sys_offline_customer_api.get('/offline_customer_list/', summary="线下客户管理列表")(get_sys_offline_customers_list)
sys_offline_customer_api.get(
    '/offline_customer/meta/execute_users/',
    summary="当前执行人筛选项",
)(offline_customer_execute_user_options)
sys_offline_customer_api.get('/offline_customer_detail/', summary="线下客户详情")(get_sys_offline_customers_detail)
sys_offline_customer_api.post('/upsert_offline_customer/', summary="新增或更新线下客户")(update_sys_offline_customers)
sys_offline_customer_api.post('/update_customer_address/', summary="更新线下客户地址")(update_customer_address)
sys_offline_customer_api.get('/offline_customer/active/list/', summary="线下生效客户列表")(get_active_offline_customers)
sys_offline_customer_api.get('/offline_customer/contract_detail/', summary="线下客户详情/带关联合同信息")(get_sys_offline_customers_contract_detail)

sys_offline_customer_api.get('/sys_operate_log_list/', summary="获取操作日志")(get_sys_operator_logs)

sys_offline_customer_api.post('/add_offline_customer_followup_record/', summary="新增线下客户随访记录")(add_offline_customer_followup_record)
sys_offline_customer_api.get('/offline_customer_followup_record_list/', summary="线下客户随访记录列表")(get_offline_customer_followup_record_list)

# 线下客户sku
sys_offline_customer_api.get('/offline_customer/detail/', summary="获取线下客户信息")(get_offline_customer_detail)
sys_offline_customer_api.post('/offline_customer/sku/create/', summary="新增线下sku记录")(create_offline_customer_sku)
sys_offline_customer_api.post('/offline_customer/sku/batch_update/', summary="批量更新sku记录")(batch_update_offline_customer_sku)
sys_offline_customer_api.get('/offline_customer/sku/list/', summary="线下sku列表")(get_offline_customer_skus)

sys_offline_customer_api.get('/offline_customer/download_excel_template/', summary="获取下载模板 线下客户sku导入模板，线下Sell Out 销量数据导入模板，线下Sell Out 库存数据导入模板")(download_offline_customer_excel_template)
sys_offline_customer_api.post('/offline_customer/sku/upload/', summary="上传导入线下sku记录")(upload_offline_customer_sku)

# 线下Sell Out Sales， Stock 更新
sys_offline_customer_api.post('/offline_customer/sell_out/sales/batch_update/', summary="批量更新线下销量")(batch_update_offline_sales)
sys_offline_customer_api.post('/offline_customer/sell_out/stock/batch_update/', summary="批量更新线下库存")(batch_update_offline_stock)
sys_offline_customer_api.post('/offline_customer/sell_out/sales/upload/', summary="上传导入销量")(upload_offline_sell_out_sales)
sys_offline_customer_api.post('/offline_customer/sell_out/stock/upload/', summary="上传导入库存")(upload_offline_sell_out_stock)
sys_offline_customer_api.get('/offline_customer/sell_out/sales/list/', summary="Sell Out 销量明细列表")(get_offline_customer_slaes_list)
sys_offline_customer_api.get('/offline_customer/sell_out/stock/list/', summary="Sell Out 库存明细列表")(get_offline_customer_stock_list)

sys_offline_customer_api.get('/offline_customer/sell_out/sales/batch_disable/', summary="批量禁用线下销量")(batch_disabel_customer_slaes)
sys_offline_customer_api.get('/offline_customer/sell_out/stock/batch_disable/', summary="批量禁用线下库存")(batch_disabel_customer_stock)

sys_offline_customer_api.post('/offline_customer/sell_out/sales/sync_data/', summary="同步数据")(sync_offline_sell_out_data)
sys_offline_customer_api.post('/offline_customer/sell_out/sales/all_task_status/', summary="查看所有同步任务情况")(get_all_task_status)
sys_offline_customer_api.post('/offline_customer/sell_out/sales/task_status/', summary="查看同步数据情况")(get_task_status)
sys_offline_customer_api.post('/offline_customer/sell_out/sales/latest_task/', summary="查看同步数据情况")(get_latest_offline_task)

sys_offline_customer_api.get('/offline_customer/logs/detail/', summary="获线下日志信息，mode_type:sku/sales/stock, refer_id: _id")(get_offline_logs)

# 线下合同
sys_offline_customer_api.get('/offline_customer/contract/list/', summary="合同列表分页")(offline_contract_list)
sys_offline_customer_api.get('/offline_customer/contract/detail/', summary="合同详情(含子表)")(offline_contract_detail)
sys_offline_customer_api.post('/offline_customer/contract/create/', summary="新建合同(草稿)")(offline_contract_create)
sys_offline_customer_api.post('/offline_customer/contract/update/', summary="更新合同")(offline_contract_update)
sys_offline_customer_api.post('/offline_customer/contract/delete/', summary="删除合同(仅草稿态)")(offline_contract_delete)
sys_offline_customer_api.get('/offline_customer/contract/operator_logs/', summary="获取合同操作日志")(get_contract_operator_logs)

# 线下客户联系人
sys_offline_customer_api.get('/offline_customer/contact/list/', summary="客户联系人列表",
                             description="根据客户ID获取客户联系人列表, customer_id: 客户ID")(get_offline_customer_contacts)
sys_offline_customer_api.post('/offline_customer/contact/create/', summary="新增客户联系人")(add_offline_customer_contact)
sys_offline_customer_api.post('/offline_customer/contact/update/', summary="更新客户联系人",
                              description="根据联系ID更新客户联系人信息, contact_id: 联系ID(主键)")(update_offline_customer_contact)
sys_offline_customer_api.post('/offline_customer/contact/delete/', summary="删除客户联系人",
                              description="根据联系ID删除客户联系人, contact_id: 联系ID(主键)")(delete_offline_customer_contact)

# 合同审批
sys_offline_customer_api.post('/offline_customer/contract/submit/',
          summary="提交审核", description="草稿状态提交，进入审核中（step=1）, contract_id: 合同ID")(submit_contract)
sys_offline_customer_api.post('/offline_customer/contract/approve/',
          summary="审批通过", description="审批通过，进入下一步审批或待生效, contract_id: 合同ID")(approve_contract)
sys_offline_customer_api.post('/offline_customer/contract/reject/',
          summary="驳回", description="任意审批步均可驳回，合同退回「草稿」, contract_id: 合同ID")(reject_contract)
sys_offline_customer_api.post('/offline_customer/contract/withdraw/',
          summary="撤回", description="提交人在「审核中」阶段主动撤回，合同退回「草稿」, contract_id: 合同ID")(withdraw_contract)
sys_offline_customer_api.post('/offline_customer/contract/terminate/',
          summary="终止", description="终止合同, contract_id: 合同ID")(terminate_contract)
sys_offline_customer_api.post('/offline_customer/contract/resubmit/',
          summary="重新发起", description="已驳回的合同可重新发起，进入审核中（step=1）, contract_id: 合同ID")(resubmit_contract)
sys_offline_customer_api.get('/offline_customer/contract/workflow/', summary="获取合同审批进度")(get_workflow)
sys_offline_customer_api.get('/offline_customer/contract/category_fee/', summary="获取线下合同类目费用")(get_conract_category_fee_list)
