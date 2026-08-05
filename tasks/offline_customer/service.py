# -*- coding:utf-8-*-
# @FileName : service.py
# @Time     : 2024/11/26 15:46
# @Author   : yuhaiping
# @Email    : ping.yu@yaoyao-inc.com
# @Software : PyCharm
import copy
import datetime
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from loguru import logger

from apps.common.service.yy_log import log_async_create
from apps.system.offline_customer.model_response import OfflineCustomerResponse
from apps.system.offline_customer.models import OfflineCustomer, SettlementMethodEnum, PaymentMethodEnum, \
    EffectiveNodeEnum, CustomerTypeFirstEnum, DeliveryMethodEnum, OfflineCustomerFollowupRecord, OfflineCustomerContact


async def generate_customer_code(db_session: Session, country: str, customer_type: str) -> str:
    """
    根据国家和客户类型生成唯一的 customer_code。

    :param db_session: 数据库会话
    :param country: 客户国家（如 TH）
    :param customer_type: 客户类型简称（如 MTR）
    :return: 生成的 customer_code（如 THMTR0001）
    """
    prefix = f"{country}{customer_type}"

    # 查询当前已存在的最大 customer_code
    query = select(func.max(OfflineCustomer.customer_code)).where(
        OfflineCustomer.customer_code.like(f"{prefix}%")
    )
    max_code = (await db_session.execute(query)).scalar()

    if max_code:
        # 提取数字部分并递增
        current_number = int(max_code[len(prefix):])
        next_number = current_number + 1
    else:
        # 没有记录，从 0001 开始
        next_number = 1

    # 格式化为4位数字
    return f"{prefix}{next_number:04d}"


def offline_op_log_data_serializer(update_data, pre_obj):
    customer_type_first = update_data.get("customer_type_first")
    customer_type_second = update_data.get("customer_type_second")
    customer_type_str = ""
    if customer_type_first:
        customer_type_first_str = CustomerTypeFirstEnum.get_description(customer_type_first)
        customer_type_str += customer_type_first_str
    if customer_type_second:
        customer_type_str += "/" + customer_type_second
    settlement_method = update_data.get("settlement_method")
    payment_method = update_data.get("payment_method")
    effective_node = update_data.get("effective_node")
    delivery_method = update_data.get("delivery_method")

    settlement_method_str = settlement_method
    if settlement_method:
        settlement_method_str = SettlementMethodEnum[settlement_method].value

    payment_method_str = payment_method
    if payment_method:
        payment_method_str = PaymentMethodEnum[payment_method].value

    effective_node_str = effective_node
    if effective_node:
        effective_node_str = EffectiveNodeEnum[effective_node].value

    delivery_method_str = delivery_method
    if delivery_method:
        delivery_method_str = DeliveryMethodEnum[delivery_method].value
    if not pre_obj:
        log_dict = {
            "客户编码": update_data.get("customer_code", ""),
            "客户简称": update_data.get("customer_short_name", ""),
            "客户公司全称": update_data.get("customer_company_full_name", ""),
            "客户国家": update_data.get("customer_country", ""),
            "客户类型":  customer_type_str,
            "合同方式": update_data.get("contract_method", ""),
            "合同点数": update_data.get("contract_points", ""),
            "结算方式": settlement_method_str,
            "账期": update_data.get("billing_period", ""),
            "生效节点": effective_node_str,
            "支付方式": payment_method_str,
            "预付比例": update_data.get("prepayment_ratio", ""),
            "常用联系人": {
                "姓名": update_data.get("recipient_name", ""),
                "区号": update_data.get("recipient_phone_area", ""),
                "号码": update_data.get("recipient_phone", ""),
                "国家": update_data.get("recipient_country", ""),
                "省/州": update_data.get("recipient_province", ""),
                "城市": update_data.get("recipient_city", ""),
                "县/区": update_data.get("recipient_district", ""),
                "详细地址": update_data.get("recipient_address", ""),
                "邮编": update_data.get("recipient_post_code", ""),
            },
            "Delivery Info": {
                "提货方式": delivery_method_str,
                "默认物流商": update_data.get("carrier", ""),
                "Delivery Fee Payment": update_data.get("delivery_fee_payment", ""),
                "Delivery Remark": update_data.get("delivery_remark", ""),
            },
            "客户资料": update_data.get("company_materials", []),
            "备注": update_data.get("remark", ""),
        }
    else:
        log_dict = {}
        pre_customer_type_first = pre_obj.get("customer_type_first")
        pre_customer_type_second = pre_obj.get("customer_type_second")
        pre_customer_type_str = ""
        if pre_customer_type_first:
            pre_customer_type_first_str = CustomerTypeFirstEnum.get_description(pre_customer_type_first)
            pre_customer_type_str += pre_customer_type_first_str
        if pre_customer_type_second:
            pre_customer_type_str += "/" + pre_customer_type_second
        pre_settlement_method = pre_obj.get("settlement_method")
        pre_payment_method = pre_obj.get("payment_method")
        pre_effective_node = pre_obj.get("effective_node")
        pre_delivery_method = pre_obj.get("delivery_method")

        pre_settlement_method_str = pre_settlement_method
        if pre_settlement_method:
            pre_settlement_method_str = SettlementMethodEnum[pre_settlement_method].value
            pre_settlement_method_str += ' ' + OfflineCustomerResponse.chinese_to_english(pre_settlement_method_str)

        pre_payment_method_str = pre_payment_method
        if pre_payment_method:
            pre_payment_method_str = PaymentMethodEnum[pre_payment_method].value
            pre_payment_method_str += ' ' + OfflineCustomerResponse.chinese_to_english(pre_payment_method_str)

        pre_effective_node_str = pre_effective_node
        if pre_effective_node:
            pre_effective_node_str = EffectiveNodeEnum[pre_effective_node].value
            pre_effective_node_str += ' ' + OfflineCustomerResponse.chinese_to_english(pre_effective_node_str)

        pre_delivery_method_str = pre_delivery_method
        if pre_delivery_method:
            pre_delivery_method_str = DeliveryMethodEnum[pre_delivery_method].value

        if update_data.get("customer_code") != pre_obj.get("customer_code"):
            log_dict['客户编码'] = f'{pre_obj.get("customer_code")} --> {update_data.get("customer_code", "")}'
        if update_data.get("customer_short_name", "") != pre_obj.get("customer_short_name"):
            log_dict["客户简称"] = f'{pre_obj.get("customer_short_name")} --> {update_data.get("customer_short_name", "")}'
        if update_data.get("customer_company_full_name") != pre_obj.get("customer_company_full_name"):
            log_dict["客户公司全称"] = f'{pre_obj.get("customer_company_full_name")} --> {update_data.get("customer_company_full_name", "")}'
        if update_data.get("customer_country") != pre_obj.get("customer_country"):
            log_dict["客户国家"] = f'{pre_obj.get("customer_country")} --> {update_data.get("customer_country", "")}'
        if pre_customer_type_str != customer_type_str:
            log_dict['客户类型'] = customer_type_str
        if update_data.get("contract_method") != pre_obj.get("contract_method"):
            log_dict["合同方式"] = f'{pre_obj.get("contract_method")} --> {update_data.get("contract_method", "")}'
        if update_data.get("contract_points") != pre_obj.get("contract_points"):
            log_dict["合同点数"] = f'{pre_obj.get("contract_points")} --> {update_data.get("contract_points", "")}'
        if settlement_method_str != pre_settlement_method_str:
            log_dict["结算方式"] = settlement_method_str
        if update_data.get("billing_period") is not None and str(update_data.get("billing_period")) != pre_obj.get("billing_period"):
            log_dict["账期"] = f'{pre_obj.get("billing_period")} --> {update_data.get("billing_period", "")}'
        if update_data.get("billing_period") is None and update_data.get("billing_period") != pre_obj.get("billing_period"):
            log_dict["账期"] = f'{pre_obj.get("billing_period")} --> {update_data.get("billing_period", "")}'
        if effective_node_str != pre_effective_node_str:
            log_dict["生效节点"] = effective_node_str
        if payment_method_str != pre_payment_method_str:
            log_dict["支付方式"] = payment_method_str
        if update_data.get("prepayment_ratio") != pre_obj.get("prepayment_ratio"):
            log_dict["预付比例"] = f'{pre_obj.get("prepayment_ratio")} --> {update_data.get("prepayment_ratio", "")}'

        contract_person = {}
        if update_data.get("recipient_name") != pre_obj.get("recipient_name"):
            contract_person["姓名"] = f'{pre_obj.get("recipient_name")} --> {update_data.get("recipient_name", "")}'
        if update_data.get("recipient_phone_area") != pre_obj.get("recipient_phone_area"):
            contract_person["区号"] = f'{pre_obj.get("recipient_phone_area")} --> {update_data.get("recipient_phone_area", "")}'
        if update_data.get("recipient_phone") != pre_obj.get("recipient_phone"):
            contract_person["号码"] = f'{pre_obj.get("recipient_phone")} --> {update_data.get("recipient_phone", "")}'
        if update_data.get("recipient_country") != pre_obj.get("recipient_country"):
            contract_person["国家"] = f'{pre_obj.get("recipient_country")} --> {update_data.get("recipient_country", "")}'
        if update_data.get("recipient_province") != pre_obj.get("recipient_province"):
            contract_person["省/州"] = f'{pre_obj.get("recipient_province")} --> {update_data.get("recipient_province", "")}'
        if update_data.get("recipient_city") != pre_obj.get("recipient_city"):
            contract_person["市/县"] = f'{pre_obj.get("recipient_city")} --> {update_data.get("recipient_city", "")}'
        if update_data.get("recipient_district") != pre_obj.get("recipient_district"):
            contract_person["区/县"] = f'{pre_obj.get("recipient_district")} --> {update_data.get("recipient_district", "")}'
        if update_data.get("recipient_address") != pre_obj.get("recipient_address"):
            contract_person["详细地址"] = f'{pre_obj.get("recipient_address")} --> {update_data.get("recipient_address", "")}'
        if update_data.get("recipient_post_code") != pre_obj.get("recipient_post_code"):
            contract_person["邮编"] = f'{pre_obj.get("recipient_post_code")} --> {update_data.get("recipient_post_code", "")}'
        if contract_person:
            log_dict["常用联系人"] = contract_person

        delivery_info = {}
        if delivery_method_str != pre_delivery_method_str:
            delivery_info["提货方式"] = delivery_method_str
        if update_data.get("carrier") != pre_obj.get("carrier"):
            delivery_info["默认物流商"] = f'{pre_obj.get("carrier")} --> {update_data.get("carrier", "")}'
        if update_data.get("delivery_fee_payment") != pre_obj.get("delivery_fee_payment"):
            delivery_info["Delivery Fee Payment"] = f'{pre_obj.get("delivery_fee_payment")} --> {update_data.get("delivery_fee_payment", "")}'
        if update_data.get("delivery_remark") != pre_obj.get("delivery_remark"):
            delivery_info["Delivery Remark"] = f'{pre_obj.get("delivery_remark")} --> {update_data.get("delivery_remark", "")}'
        if delivery_info:
            log_dict["Delivery Info"] = delivery_info
        # "公司材料 Company Materials": update_data.get("company_materials", []),

        if update_data.get("company_materials") != pre_obj.get("company_materials"):
            log_dict["公司材料"] = f'{pre_obj.get("company_materials")} --> {update_data.get("company_materials", [])}'
        if update_data.get("remark") != pre_obj.get("remark"):
            log_dict["备注"] = f'{pre_obj.get("remark")} --> {update_data.get("remark", "")}'
    return log_dict


async def upsert_offline_customer(db_session: Session, update_data: dict, operator=''):
    """
    新增或更新 OfflineCustomer 数据，自动生成 customer_code。
    """
    customer_code = update_data.get("customer_code")
    if customer_code:
        # 更新逻辑
        query = select(OfflineCustomer).where(OfflineCustomer.customer_code == customer_code)
        existing_customer = (await db_session.execute(query)).scalar_one_or_none()
        if existing_customer:
            await db_session.execute(
                update(OfflineCustomer)
                .where(OfflineCustomer.customer_code == customer_code)
                .values(**update_data)
            )
            await db_session.commit()
            updated_customer = await db_session.execute(query)
            updated_customer = updated_customer.fetchone()
            if updated_customer:
                updated_customer = updated_customer[0].__dict__
            # log_info = offline_op_log_data_serializer(update_data, existing_customer_copy)
            # if log_info:
            #     await log_async_create(
            #         username=operator,
            #         types="修改",
            #         operation_details=f"Update :{log_info}",
            #         session=db_session,
            #         refer_type='线下客户管理-修改',
            #         refer_table='data_sys_offline_customers',
            #         refer_id=updated_customer.get("_id")
            #     )
            return updated_customer

    # 新增逻辑
    if not customer_code:
        # 自动生成 customer_code
        country = update_data.get("customer_country")
        customer_type = update_data.get("customer_type_first")
        if not country or not customer_type:
            raise ValueError("新增客户时需要提供 customer_country 和 customer_type_first")
        customer_short_name = update_data.get("customer_short_name")
        query = select(OfflineCustomer).where(OfflineCustomer.customer_short_name == customer_short_name, OfflineCustomer.customer_country == country)
        existing_customer = (await db_session.execute(query)).scalar()
        if existing_customer:
            raise ValueError("客户已存在，请勿重复新增！")
        update_data["customer_code"] = await generate_customer_code(db_session, country, customer_type)

    new_customer = OfflineCustomer(**update_data)
    db_session.add(new_customer)
    await db_session.commit()
    await db_session.refresh(new_customer)

    # await log_async_create(
    #     username=operator,
    #     types="新增",
    #     operation_details=f"Create :{offline_op_log_data_serializer(update_data, None)}",
    #     session=db_session,
    #     refer_type='线下客户管理-新增',
    #     refer_table='data_sys_offline_customers',
    #     refer_id=new_customer._id
    # )
    return new_customer


async def insert_offline_customer_followup_records(db_session: Session, update_data: dict):
    """

    :param db_session:
    :param update_data:
    :return:
    """
    new_record = OfflineCustomerFollowupRecord(**update_data)
    db_session.add(new_record)
    await db_session.commit()
    await db_session.refresh(new_record)
    return new_record


async def insert_offline_customer_contact_records(db_session: Session, update_data: dict):
    """

    :param db_session:
    :param update_data:
    :return:
    """
    new_record = OfflineCustomerContact(**update_data)
    db_session.add(new_record)
    await db_session.commit()
    await db_session.refresh(new_record)
    return new_record


async def update_offline_customer_contact_records(db_session: Session, update_data: dict):
    """

    :param db_session:
    :param update_data:
    :return:
    """
    await db_session.execute(
        update(OfflineCustomerContact)
        .where(OfflineCustomerContact._id == update_data["_id"])
        .values(**update_data)
    )
    await db_session.commit()