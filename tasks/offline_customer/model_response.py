# -*- coding:utf-8-*-
# @FileName : model_response.py
# @Time     : 2024/11/25 17:08
# @Author   : yuhaiping
# @Email    : ping.yu@yaoyao-inc.com
# @Software : PyCharm
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, validator, Field
from decimal import Decimal

from apps.system.offline_customer.models import SettlementMethodEnum, PaymentMethodEnum, EffectiveNodeEnum, \
    CustomerTypeFirstEnum, DeliveryMethodEnum, CustomerTypeSecondEnum, OfflineContract

from apps.system.offline_customer.contract_workflow_engine import CUSTOMER_STATUS_STR
CONTACT_FREQUENCY_MAP = {
    1: "周度",
    2: "双周度",
    3: "月度",
    4: "双月度",
    5: "季度",
    6: "半年度",
    7: "年度"
}

COOPERATION_METHOD_STR = {
    1: "批发",
    2: "一件代发",
}


class OfflineCustomerResponse(BaseModel):
    _id: Optional[str]
    offline_customer_id: Optional[str] = Field(alias="_id")
    customer_short_name: str
    customer_company_full_name: Optional[str]
    customer_country: Optional[str]
    customer_code: str
    customer_type_first: Optional[str]
    customer_type_first_str: Optional[str]
    customer_type_second: Optional[str]
    customer_type_second_str: Optional[str]
    is_ka: Optional[int]
    is_ka_str: Optional[str]
    is_tax_free: Optional[int]
    is_tax_free_str: Optional[str]
    cooperation_method: Optional[int]
    cooperation_method_str: Optional[str]
    oa_client_id: Optional[str]
    contact_frequency: Optional[int]
    contact_frequency_str: Optional[str]
    settlement_currency: Optional[str]
    business_license: Optional[List[Any]]
    customer_files: Optional[List[Any]]
    customer_status: Optional[int]
    customer_status_str: Optional[str]
    current_contract_id: Optional[int]

    # contract_method: Optional[str]
    # contract_points: Optional[float]
    # settlement_method: Optional[str]
    # settlement_method_str: Optional[str]
    # billing_period: Optional[str]
    # payment_date_type: Optional[str]
    # payment_date_type_str: Optional[str]
    # payment_date: Optional[str]
    # effective_node: Optional[str]
    # effective_node_str: Optional[str]
    # payment_method: Optional[str]
    # payment_method_str: Optional[str]
    # prepayment_ratio: Optional[float]
    # recipient_name: Optional[str]
    # recipient_phone_area: Optional[str]
    # recipient_phone: Optional[str]
    # recipient_country: Optional[str]
    # recipient_province: Optional[str]
    # recipient_city: Optional[str]
    # recipient_district: Optional[str]
    # recipient_address: Optional[str]
    # recipient_post_code: Optional[str]
    # remark: Optional[str]
    # delivery_method: Optional[str]
    # delivery_method_str: Optional[str]
    # carrier: Optional[str]
    # delivery_fee_payment: Optional[str]
    # delivery_remark: Optional[str]
    # company_materials: Optional[List[str]] = None

    yy_company_id: Optional[int]
    yy_company_name: Optional[str]
    remark: Optional[str]

    button_list: List[str] = ['select', 'edit', 'log']

    create_time: Optional[str]
    update_time: Optional[str]

    class Config:
        orm_mode = True
        underscore_attrs_are_private = False

    @validator("create_time", "update_time", pre=True)
    def datetime_to_string(cls, value):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value

    @classmethod
    def chinese_to_english(cls, value):
        map_info = {
            "账期": "Credit Days",
            "带款提货": "Cash before delivery",
            "固定账期": "Fixed Payment Period",
            "银行转账": "Bank Transfer",
            "支票": "Check",
            "现金": "Cash",
            "无需支付": "No Payment Required",
            "客户提货": "Customer Pickup",
            "发票日期": "Invoice Date"

        }

        return map_info.get(value, "")


    @classmethod
    def from_orm(cls, obj):
        """继承父类逻辑并扩展"""
        instance = super().from_orm(obj)
        is_ka_str = ""
        if instance.is_ka == 1:
            is_ka_str = "KA"
        elif instance.is_ka == 0:
            is_ka_str = "Non-KA"
        else:
            ""

        if instance.is_tax_free == 1:
            is_tax_free_str = "是"
        elif instance.is_tax_free == 0:
            is_tax_free_str = "否"
        else:
            ""

        instance.is_ka_str = is_ka_str
        instance.is_tax_free_str = is_tax_free_str
        instance.cooperation_method_str = COOPERATION_METHOD_STR.get(
            instance.cooperation_method, ""
        )

        instance.customer_status_str = CUSTOMER_STATUS_STR.get(instance.customer_status, instance.customer_status)
        instance.contact_frequency_str = CONTACT_FREQUENCY_MAP.get(instance.contact_frequency, instance.contact_frequency)
        # settlement_method_str = None
        # if instance.settlement_method:
        #     settlement_method_str = SettlementMethodEnum[instance.settlement_method].value
        # instance.settlement_method_str = settlement_method_str

        # payment_method_str = None
        # if instance.payment_method:
        #     payment_method_str = PaymentMethodEnum[instance.payment_method].value
        # instance.payment_method_str = payment_method_str

        # effective_node_str = None
        # if instance.effective_node:
        #     effective_node_str = EffectiveNodeEnum[instance.effective_node].value
        # instance.effective_node_str = effective_node_str

        # payment_date_type_map = {
        #     "0": "次月",
        #     "1": "次次月",
        #     "2": "次次次月"
        # }
        # payment_date_type_str = payment_date_type_map.get(instance.payment_date_type, None)
        # if payment_date_type_str:
        #     payment_date_type_str = payment_date_type_str + str(instance.payment_date) + "日"
        # instance.payment_date_type_str = payment_date_type_str
        instance.oa_client_id = instance.customer_code + '_' + instance.customer_short_name
        instance.customer_type_first_str = CustomerTypeFirstEnum.get_description(instance.customer_type_first)

        customer_type_second_str = instance.customer_type_second
        if customer_type_second_str not in [CustomerTypeSecondEnum.HYPER.value,
                                            CustomerTypeSecondEnum.HOME_SPECIALITY.value,
                                            CustomerTypeSecondEnum.APPLIANCE_SPECIALITY.value,
                                            CustomerTypeSecondEnum.EXCLUSIVE_WHOLESALER.value,
                                            CustomerTypeSecondEnum.NON_EXCLUSIVE_WHOLESALER.value,
                                            CustomerTypeSecondEnum.CONVENIENT_STORE.value
                                            ]:
            customer_type_second_str = '-'
        instance.customer_type_second_str = customer_type_second_str

        # delivery_method_str = None
        # if instance.delivery_method:
        #     delivery_method_str = DeliveryMethodEnum[instance.delivery_method].value
        # instance.delivery_method_str = delivery_method_str
        res = instance.dict()
        res['_id'] = res['offline_customer_id']
        return res


class OfflineCustomerFollowupRecordResponse(BaseModel):
    offline_customer_id: Optional[str]

    content: Optional[str]
    operator: Optional[str]
    operator_user_id: Optional[str]
    company_contact_id: Optional[int]
    operator_user_name: Optional[str]
    customer_contact_name: Optional[str]
    contact_time: Optional[str]
    company_contact_name: Optional[str]
    # contact_date: Optional[str]

    # create_time: Optional[str]

    @validator("contact_time", pre=True)
    def datetime_to_string(cls, value):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value


    # @validator("contact_date", pre=True)
    # def date_to_string(cls, value):
    #     if isinstance(value, date):
    #         return value.strftime("%Y-%m-%d")
    #     return value

    class Config:
        orm_mode = True


class OfflineContractResponse(BaseModel):
    _id: Optional[str]
    offline_contract_id: Optional[str] = Field(alias="_id")

    contract_no: Optional[str]
    customer_id: Optional[int]
    customer_code: Optional[str]
    country: Optional[str]
    owner_staff_id: Optional[int]
    owner_staff_name: Optional[str]  # 假设后续会关联填充负责人名

    status: Optional[int]
    status_str: Optional[str]  # 状态中文名
    current_step: Optional[int]
    review_round: Optional[int]

    terminate_type: Optional[int]
    terminate_type_str: Optional[str]

    sign_date: Optional[str]
    effective_start: Optional[str]
    effective_end: Optional[str]

    # 商务条款
    contract_method: Optional[int]
    contract_method_str: Optional[str]
    settlement_method: Optional[int]
    settlement_method_str: Optional[str]
    settlement_days: Optional[int]
    billing_period: Optional[int]
    payment_date: Optional[int]
    payment_date_type: Optional[int]
    payment_date_type_str: Optional[str]
    payment_method: Optional[int]
    payment_method_str: Optional[str]

    is_prepayment: Optional[int]
    prepayment_ratio: Optional[Decimal]

    # 物流相关
    delivery_method: Optional[int]
    delivery_method_str: Optional[str]
    carrier: Optional[str]
    delivery_fee_payment: Optional[int]
    delivery_fee_payment_str: Optional[str]
    delivery_remark: Optional[str]

    bank_account_confirmation: Optional[Dict[str, Any]]

    # 目标与激励
    mt_min_order_amount: Optional[Decimal]
    mt_has_delivery_target: Optional[bool]
    mt_delivery_target_ratio: Optional[Decimal]
    mt_has_penalty: Optional[bool]
    mt_penalty_detail: Optional[str]
    mt_delivery_mode: Optional[int]
    mt_delivery_mode_str: Optional[str]

    ws_incentive_policy: Optional[Dict[str, Any]]
    ws_authorized_channels: Optional[Dict[str, Any]]

    # 售后与其他
    return_policy: Optional[int]
    return_ratio: Optional[Decimal]
    sample_policy: Optional[int]
    sample_discount: Optional[Decimal]
    supplementary_agreement: Optional[str]

    previous_contract_id: Optional[int]
    contact_id: Optional[int]

    create_by: Optional[int]
    update_by: Optional[int]
    create_time: Optional[str]
    update_time: Optional[str]

    button_list: List[str] = ['select', 'edit', 'log', 'review']

    class Config:
        orm_mode = True
        underscore_attrs_are_private = False

    # 时间格式化
    @validator("sign_date", "effective_start", "effective_end", pre=True)
    def date_to_string(cls, value):
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return value

    @validator("create_time", "update_time", pre=True)
    def datetime_to_string(cls, value):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value

    @classmethod
    def from_orm(cls, obj):
        """继承父类逻辑并扩展"""
        instance = super().from_orm(obj)

        # 1. 状态转换 (参考你提供的常量)
        status_map = {
            10: "草稿",
            20: "审核中",
            30: "待生效",
            40: "已生效",
            50: "已失效"
        }
        instance.status_str = status_map.get(instance.status, "未知")

        # 2. 终止类型转换
        terminate_map = {
            1: "自然到期",
            2: "人工终止",
            3: "被顶替"
        }
        instance.terminate_type_str = terminate_map.get(instance.terminate_type, "-")

        # 3. 配送模式转换
        delivery_mode_map = {
            1: "一次性",
            2: "多批次"
        }
        instance.mt_delivery_mode_str = delivery_mode_map.get(instance.mt_delivery_mode, "-")

        # 4. 模拟枚举转换 (如果没有真实枚举类，建议建立类似的字典映射)
        # instance.contract_method_str = ContractMethodEnum.get_description(instance.contract_method)
        # instance.settlement_method_str = SettlementMethodEnum.get_description(instance.settlement_method)
        # instance.payment_method_str = PaymentMethodEnum.get_description(instance.payment_method)

        # 5. 账期类型拼接逻辑 (参考 OfflineCustomerResponse)
        payment_date_type_map = {
            0: "次月",
            1: "次次月",
            2: "次次次月"
        }
        if instance.payment_date_type is not None and instance.payment_date is not None:
            type_str = payment_date_type_map.get(instance.payment_date_type, "")
            if type_str:
                instance.payment_date_type_str = f"{type_str}{instance.payment_date}日"

        # 6. 处理 _id 别名映射
        res = instance.dict()
        res['_id'] = res['offline_contract_id']
        return res
