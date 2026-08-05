# -*- coding:utf-8-*-
# @FileName : schemas.py
# @Time     : 2024/11/26 11:01
# @Author   : yuhaiping
# @Email    : ping.yu@yaoyao-inc.com
# @Software : PyCharm
from datetime import date, datetime
from typing import Optional, List, Union, Any

from pydantic import BaseModel, Field, validator, root_validator

from apps.system.offline_customer.models import (
    CUSTOMER_TYPE_RELATIONS,
    SettlementMethodEnum,
    DeliveryMethodEnum,
    ContractStatus,
)



class OfflineCustomerContactCreateRequest(BaseModel):
    """新增一条客户联系人（`data_sys_offline_customer_contact`）。"""
    name: Optional[str] = Field(None, description="联系人姓名")
    position: Optional[str] = Field(None, description="联系人职位")
    contact_info: Optional[str] = Field(None, description="联系人联系方式")
    district: Optional[str] = Field(None, description="联系人县/区")
    address: Optional[str] = Field(None, description="联系人详细地址")
    post_code: Optional[str] = Field(None, description="联系人邮编")
    remark: Optional[str] = Field(None, description="联系人备注")

    class Config:
        orm_mode = True


class OfflineCustomerContactListRequest(BaseModel):
    """新增一条客户联系人（`data_sys_offline_customer_contact`）。"""
    contact_id: Optional[int] = Field(None, alias="_id", description="主键ID")
    name: Optional[str]  = Field(None, description="联系人姓名")
    position: Optional[str] = Field(None, description="联系人职位")
    contact_info: Optional[str] = Field(None, description="联系人联系方式")
    district: Optional[str] = Field(None, description="联系人县/区")
    address: Optional[str] = Field(None, description="联系人详细地址")
    post_code: Optional[str] = Field(None, description="联系人邮编")
    remark: Optional[str] = Field(None, description="联系人备注")
    is_delete: Optional[int] = Field(None, description="是否删除")

    class Config:
        orm_mode = True
        allow_population_by_field_name = True
        underscore_attrs_are_private = False


class OfflineCustomerAddressCreateRequest(BaseModel):
    country: Optional[str] = Field(None, description="国家")
    province: Optional[str] = Field(None, description="省/州")
    city: Optional[str] = Field(None, description="城市")
    district: Optional[str] = Field(None, description="县/区")
    address: Optional[str] = Field(None, description="详细地址")
    post_code: Optional[str] = Field(None, description="邮编")
    remark: Optional[str] = Field(None, description="备注")

    class Config:
        orm_mode = True


class OfflineCustomerAddressListRequest(BaseModel):
    address_id: Optional[int] = Field(None, alias="_id", description="主键ID")
    country: Optional[str] = Field(None, description="国家")
    province: Optional[str] = Field(None, description="省/州")
    city: Optional[str] = Field(None, description="城市")
    district: Optional[str] = Field(None, description="县/区")
    address: Optional[str] = Field(None, description="详细地址")
    post_code: Optional[str] = Field(None, description="邮编")
    remark: Optional[str] = Field(None, description="备注")
    is_delete: Optional[int] = Field(None, description="是否删除")

    class Config:
        orm_mode = True
        allow_population_by_field_name = True
        underscore_attrs_are_private = False


class OfflineCustomerUpdateRequest(BaseModel):
    customer_short_name: Optional[str] = Field(None, description="客户简称", max_length=100)
    customer_company_full_name: Optional[str] = Field(None, description="客户公司全称", max_length=255)
    customer_country: Optional[str] = Field(None, description="客户国家", max_length=100)
    customer_code: Optional[str] = Field(None, description="客户编码", max_length=50)
    customer_type_first: Optional[str] = Field(None, description="客户类型一层")
    customer_type_second: Optional[str] = Field(None, description="客户类型二层")
    is_ka: Optional[int] = Field(0, description="是否KA客户")
    is_tax_free: Optional[int] = Field(0, description="是否免税 0否1是")
    remark: Optional[str] = Field(None, description="备注")
    cooperation_method: Optional[int] = Field(
        None, description="合作方式 1批发 2一件代发"
    )
    contact_frequency: Optional[int] = Field(None, description="联络频率(1:周度, 2:双周度, 3:月度, 4:双月度, 5:季度, 6:半年度, 7:年度)")
    business_license: Optional[List[Any]] = Field(None, description="营业执照等资质附件列表")
    settlement_currency: Optional[str] = Field(None, description="结算币种")
    customer_files: Optional[List[Any]] = Field(None, description="客户资料附件列表")

    # contract_method: Optional[str] = Field(None, description="合同方式")
    # contract_points: Optional[float] = Field(None, description="合同点数")
    # settlement_method: Optional[str] = Field(None, description="结算方式")
    # billing_period: Optional[Union[int, str]] = Field(None, description="账期，单位天")
    # payment_date_type: Optional[str] = Field(None, description="出账日范围，1-31号")
    # payment_date: Optional[str] = Field(None, description="出账日，1-31号")
    # effective_node: Optional[str] = Field(None, description="生效节点")
    # payment_method: Optional[str] = Field(None, description="支付方式")
    # prepayment_ratio: Optional[float] = Field(None, description="预付比例，0-100")
    # recipient_name: Optional[str] = Field(None, description="收件人姓名", max_length=100)
    # recipient_phone_area: Optional[str] = Field(None, description="收件人手机号区号")
    # recipient_phone: Optional[str] = Field(None, description="收件人手机号")
    # recipient_country: Optional[str] = Field(None, description="收件人国家")
    # recipient_province: Optional[str] = Field(None, description="收件人省/州")
    # recipient_city: Optional[str] = Field(None, description="收件人城市")
    # recipient_district: Optional[str] = Field(None, description="收件人县/区")
    # recipient_address: Optional[str] = Field(None, description="收件人详细地址")
    # recipient_post_code: Optional[str] = Field(None, description="收件人邮编")


    # delivery_method: Optional[str] = Field(None, description="提货方式")
    # carrier: Optional[str] = Field(None, description="默认物流商")
    # delivery_fee_payment: Optional[str] = Field(None, description="运费支付方")
    # delivery_remark: Optional[str] = Field(None, description="提货备注")
    # company_materials: Optional[List[str]] = Field(None, description="公司材料")

    # 合同新增
    # customer_status: Optional[str] = Field(None, max_length=128, description="客户状态")
    yy_company_id: Optional[int] = Field(None, description="曜曜签约主体主键")

    contacts: Optional[List[OfflineCustomerContactListRequest]] = Field(default_factory=list, description="客户联系人列表")
    addresses: Optional[List[OfflineCustomerAddressListRequest]] = Field(default_factory=list, description="客户地址列表")

    # 验证必填字段
    @root_validator(pre=True)
    def validate_multiple_fields(cls, values):
        required_fields = ["customer_short_name", "customer_company_full_name", "customer_country"]
        for field in required_fields:
            if field in values and (values[field] is None or values[field] == ""):
                raise ValueError(f"{field} 不能为空")
        # 验证客户类型
        customer_type_first = values.get("customer_type_first")
        customer_type_second = values.get("customer_type_second")

        if customer_type_first and customer_type_first not in CUSTOMER_TYPE_RELATIONS:
            raise ValueError(f"无效的 customer_type_first 值，应为 {list(CUSTOMER_TYPE_RELATIONS.keys())}")

        valid_second_types = CUSTOMER_TYPE_RELATIONS.get(customer_type_first, [])
        if customer_type_first in ['MTR', 'WHS'] and customer_type_second and customer_type_second not in valid_second_types:
            raise ValueError(
                f"无效的 customer_type_second 值，应为 {valid_second_types}，对应的 customer_type_first: {customer_type_first}"
            )

        if customer_type_first in ['COC', 'SMALL', 'OTH'] and customer_type_second:
            raise ValueError(f"customer_type_first 为 {customer_type_first} 时，不应指定 customer_type_second")

        return values


class OfflineCustomerFollowupCreateRequest(BaseModel):
    offline_customer_id: str
    company_contact_id: Optional[int] = Field(None, description="公司联系人ID, 关联 yy_user.id， yaoyao内部用户id")
    # customer_contact_id: Optional[int] = Field(None, description="客户联系人ID, 关联客户联系方式中的 _id")
    customer_contact_name: Optional[str] = Field(None, description="客户联系人姓名")
    contact_time: Optional[datetime] = Field(None, description="联络时间")
    content: Optional[str] = Field(None, description="随访内容")


class ContractAttachmentIn(BaseModel):
    """合同附件元数据；文件需先走上传服务拿到 `file_url` 再提交。"""

    attachment_type: int = Field(
        ...,
        description=(
            "附件类型：1=银行/账户类证明 2=补充协议 3=合同扫描件 9=其他；"
            "与列表展示、统计维度一致，勿混用"
        ),
    )
    file_name: str = Field(
        ..., max_length=255, description="用户上传的原始文件名（含扩展名）"
    )
    file_url: str = Field(
        ...,
        max_length=512,
        description="对象存储地址、CDN URL 或内部文件 key，由上传接口返回",
    )
    file_size: Optional[int] = Field(
        None, description="文件大小，单位：字节，可选用于前端展示/校验"
    )


class ContractUncondRebateIn(BaseModel):
    """无条件返利行：满足即按规则算返利，不依赖采购额门槛。"""

    fee_category_id: int = Field(
        None, description="费用/返利类目主键，对应 `level=3` 的类目或费用项配置"
    )
    calc_method: int = Field(
        None,
        description="计算方式：1=按比例 2=固定金额；与 `value` 含义联动",
    )
    calc_base: Optional[int] = Field(
        None,
        description="当 `calc_method` 为比例时，分母/基数类型（如含税销售额等），整型编码见字典",
    )
    value: float = Field(
        None, description="返利值：比例时为百分点或小数（与后端约定一致）；固定额时为金额"
    )
    currency: Optional[str] = Field(
        None, max_length=8, description="币种 ISO 码或业务简码，如 CNY、USD"
    )
    remark: Optional[str] = Field(None, description="本行补充说明，展示在合同子表备注列")


class ContractCondRebateStepIn(BaseModel):
    """有条件返利按「年采购额」分档的台阶，一行一格；`step_no` 升序，门槛递增。"""

    step_no: int = Field(
        None, description="台阶序号，从 1 连续递增，用于排序与展示"
    )
    annual_purchase_amount: float = Field(
        None, description="本档年采购额（或滚动采购额）门槛，达到则适用本档 `rebate_ratio`"
    )
    rebate_ratio: float = Field(
        None, description="本档返利比例，单位与业务约定一致（如 0.05 或 5 表示 5%）"
    )
    currency: Optional[str] = Field(
        None, max_length=8, description="与采购额/返利口径一致时的币种，可与主合同币种一致"
    )


# 合同主状态，与 `ContractStatus` 一致，供文档引用
_OFFLINE_CONTRACT_STATUS_DESC = (
    f"{ContractStatus.DRAFT}=草稿 {ContractStatus.REVIEWING}=审核中 "
    f"{ContractStatus.PENDING_EFFECTIVE}=待生效 {ContractStatus.EFFECTIVE}=已生效 {ContractStatus.EXPIRED}=已失效"
)


class OfflineContractCreateRequest(BaseModel):
    """
    创建 `data_sys_offline_contract` 及子表信息。

    **主键/外键：**
    - `customer_id`：`data_sys_offline_customers._id`
    - `yy_company_id`：曜曜签约主体表 `yy_company_info._id`
    - `owner_staff_id`：负责签订的内勤用户主键

    **合同号：**
    - `contract_no` 可不传，由服务按「签订日+规则」生成；传则须全局唯一，见服务校验。

    **子表：**
    - `contacts`、`attachments`、`uncond_rebates`、`cond_rebate_steps` 均为可选数组，默认空列表表示不建子行。
    """

    customer_id: int = Field(
        ..., description="客户主表主键 `data_sys_offline_customers._id`"
    )
    customer_code: str = Field(
        ...,
        max_length=128,
        description="客户编码快照，须与当时客户主档 `customer_code` 一致，用于报表与对账",
    )
    owner_staff_id: Optional[int] = Field(
        None, description="本合同业务负责人/签订跟进人，对应内勤用户表主键"
    )
    contract_no: Optional[str] = Field(
        None, max_length=64, description="业务合同号；不传则按规则生成，传则须唯一"
    )
    sign_date: Optional[date] = Field(
        None, description="合同签订日 `YYYY-MM-DD`，参与合同号、生效逻辑等"
    )
    effective_start: Optional[date] = Field(
        None, description="合同约定期生效起始日，未到可能为待生效/计划生效"
    )
    effective_end: Optional[date] = Field(
        None, description="合同约定期失效/到期日，与终止、续签相关"
    )
    customer_type: Optional[int] = Field(
        None,
        description="合同侧归类的客户类型大类整型编码（如 1=MT 2=WS 3=CC 4=小B，以实际数据字典为准）",
    )
    status: Optional[int] = Field(
        default=ContractStatus.DRAFT,
        description=f"主状态。{_OFFLINE_CONTRACT_STATUS_DESC}；创建默认 {ContractStatus.DRAFT}（草稿）",
    )
    flow_id: Optional[int] = Field(
        1, description="状态机/流程集 ID，默认 1，与审批引擎配置一致"
    )
    audit_flow_id: Optional[int] = Field(
        1, description="审核流配置集 ID，默认 1"
    )

    # 结算信息
    contract_method: Optional[int] = Field(
        None, description="合同方式：1=寄售 2=非寄售（以数据字典为准）"
    )
    contract_points: Optional[float] = Field(
        None, description="合同点数"
    )
    settlement_method: Optional[int] = Field(
        None, description="结算方式编码，与财务/对账主数据一致"
    )
    settlement_days: Optional[int] = Field(
        None, description="账期天数，与 `settlement_method`、开账日规则配合"
    )
    billing_period: Optional[int] = Field(
        None, description="开账/对账周期编码（如周结、月结等）"
    )
    effective_node: Optional[int] = Field(
        None, description="账期节点， 1：客户提货， 2：发票日期 3 固定付款日， 4 分批结算"
    )
    payment_date: Optional[int] = Field(
        None, description="出账日规则编码（如固定每月几号出账）"
    )
    payment_date_type: Optional[int] = Field(
        None, description="出账日类型/口径编码（如自然月/滚动周期）"
    )
    payment_method: Optional[int] = Field(
        None, description="付款方式编码（对公转账/票据等）"
    )
    is_prepayment: Optional[bool] = Field(
        False, description="是否预付款/预付条款，与 `prepayment_ratio` 联动"
    )
    prepayment_ratio: Optional[float] = Field(
        None, description="预付比例，0～100 或 0～1 以业务与存储约定为准"
    )
    sample_policy: Optional[int] = Field(
        None, description="样品政策整型编码：1=免费供样 2=折扣供样"
    )
    sample_discount: Optional[float] = Field(
        None, description="样品折扣，小数或点数以约定为准"
    )
    bank_account_confirmation: Optional[List[Any]] = Field(
        None,
        description="银行账户确认材料，JSON 数组，元素含 url、类型等",
    )
    front_margin: Optional[float] = Field(
        None, description="前台毛利"
    )

    # 交付信息
    delivery_method: Optional[int] = Field(
        None, description="配送/交货方式：1=在指定地点交付 2=在配送中心交付 3=客户自提"
    )
    carrier: Optional[str] = Field(
        None, description="约定物流商名称或主数据编码"
    )
    delivery_fee_payment: Optional[int] = Field(
        None, description="运费承担方编码，见数据字典"
    )
    delivery_remark: Optional[str] = Field(
        None, description="交付/物流补充条款文字"
    )

    # 目标与激励
    mt_min_order_amount: Optional[float] = Field(
        None, description="起订金额或最小订单额，与币种一致"
    )
    mt_has_delivery_target: Optional[int] = Field(
        False, description="是否约定送货率/送达率类 KPI：0=否 1=是"
    )
    mt_delivery_target_ratio: Optional[float] = Field(
        None, description="目标送货率/达成率，小数或百分数以约定为准"
    )
    mt_has_penalty: Optional[int] = Field(
        False, description="是否约定未达标违约金条款：0=否 1=是"
    )
    mt_penalty_fee: Optional[float] = Field(
        None, description="违约金金额，币种与主合同一致"
    )
    mt_delivery_mode: Optional[int] = Field(
        None, description="交货模式：1=一次性交付 2=多批次交付"
    )
    mt_currency: Optional[str] = Field(
        None, description="现代通路最小起送金额对应币种"
    )

    # 退货条款
    return_policy: Optional[int] = Field(
        None, description="退货政策整型编码, 1=可退 0=不可退"
    )
    return_ratio: Optional[float] = Field(
        None, description="可退比例/额度相关数值，与政策编码联动"
    )

    # 授权与激励
    # authorized_channels: Optional[int] = Field(
    #     None, description="授权渠道：1=线上 2=线下"
    # )
    # authorized_channels_next: Optional[int] = Field(
    #     None, description="授权渠道下一级：1=地区 2=渠道"
    # )
    is_online_channel: Optional[int] = Field(
        None, description="是否线上授权渠道"
    )
    online_channel_text: Optional[str] = Field(
        None, description="线上授权渠道文本"
    )
    is_offline_channel: Optional[int] = Field(
        None, description="是否线下授权渠道"
    )
    offline_channel_text: Optional[str] = Field(
        None, description="线下授权渠道文本"
    )

    reword_policy: Optional[int] = Field(
        None, description="奖励政策编码：1=季度采购激励 2=年度采购激励 3=其他"
    )

    attachments: Optional[List[Any]] = Field(
        None, description="合同附件"
    )
    business_license: Optional[List[Any]] = Field(
        None, description="营业执照等资质附件列表"
    )
    supplementary_agreement: Optional[List[Any]] = Field(
        None, description="补充协议正文或富文本的存储引用/摘要"
    )
    previous_contract_id: Optional[int] = Field(
        None, description="续签或替代场景下，上一版合同主键，用于关联查询"
    )
    contact_id: Optional[int] = Field(
        None, description="合同联系人主键，关联 `data_sys_offline_customer_contact._id`"
    )
    address_id: Optional[int] = Field(
        None, description="合同地址主键，关联 `data_sys_offline_customer_address._id`"
    )

    # 子表
    uncond_rebates: Optional[List[ContractUncondRebateIn]] = Field(
        default_factory=list, description="无条件返利子表，默认 []"
    )
    cond_rebate_steps: Optional[List[ContractCondRebateStepIn]] = Field(
        default_factory=list, description="有条件返利分档子表，默认 []"
    )

    class Config:
        arbitrary_types_allowed = True
        schema_extra = {
            "example": {
                "customer_id": 10001,
                "customer_code": "CN-MTR-00001",
                "country": "CN",
                "yy_company_id": 1,
                "owner_staff_id": 200,
                "sign_date": "2025-01-10",
                "status": 10,
                "contacts": [
                    {
                        "name": "张三",
                        "position": "采购经理",
                        "phone_area": "86",
                        "phone": "13800138000",
                        "email": "zhang@example.com",
                        "is_primary": True,
                    }
                ],
                "attachments": [
                    {
                      ""
                    }
                ],
            }
        }


class OfflineContractUpdateRequest(BaseModel):
    """
    更新线下合同主表及子表。

    - 仅将 **需要修改** 的字段放入 JSON；未出现字段不更新（Pydantic `exclude_unset`）。
    - 子表 `contacts`、`attachments`、`uncond_rebates`、`cond_rebate_steps`：若本请求 **包含** 该 key 且值为数组，则对该子表 **全量覆盖**（先删后插）；不传 key 则不改子表。
    - 主键 `id` 必填，指向 `data_sys_offline_contract.id`。
    - `current_step` / `review_round` / `terminate_type` 多由流程引擎回写，前端仅在特定场景提交。
    """

    _id: int = Field(
        ..., alias="_id", description="合同主键 `data_sys_offline_contract.id`"
    )
    customer_id: Optional[int] = Field(
        None, description="见创建接口；非必要勿改，避免与业务单据不一致"
    )
    sign_date: Optional[date] = Field(None, description="见创建接口")
    effective_start: Optional[date] = Field(None, description="见创建接口")
    effective_end: Optional[date] = Field(None, description="见创建接口")
    yy_company_id: Optional[int] = Field(None, description="见创建接口")
    owner_staff_id: Optional[int] = Field(None, description="见创建接口")
    contract_no: Optional[str] = Field(None, description="见创建接口；一般仅草稿阶段允许改号")
    customer_type: Optional[int] = Field(None, description="见创建接口")
    status: Optional[int] = Field(
        None, description=f"主状态。{_OFFLINE_CONTRACT_STATUS_DESC}"
    )
    flow_id: Optional[int] = None
    audit_flow_id: Optional[int] = None
    current_step: Optional[int] = Field(
        None, description="当前审核步骤序号，由审批流驱动时可回传"
    )
    review_round: Optional[int] = Field(
        None, description="审核轮次，驳回后再提交通常递增"
    )
    terminate_type: Optional[int] = Field(
        None, description="终止类型：1=自然到期 2=人工终止 3=被新合同替代"
    )

    # 结算信息
    contract_method: Optional[int] = None
    settlement_method: Optional[int] = None
    settlement_days: Optional[int] = None
    billing_period: Optional[int] = None
    effective_node: Optional[int] = None
    payment_date: Optional[int] = None
    payment_date_type: Optional[int] = None
    payment_method: Optional[int] = None
    is_prepayment: Optional[bool] = None
    prepayment_ratio: Optional[float] = None
    sample_policy: Optional[int] = None
    sample_discount: Optional[float] = None
    bank_account_confirmation: Optional[List[Any]] = None
    front_margin: Optional[float] = None

    # 交付信息
    delivery_method: Optional[int] = None
    carrier: Optional[str] = None
    delivery_fee_payment: Optional[int] = None
    delivery_remark: Optional[str] = None

    # 目标与激励
    mt_has_delivery_target: Optional[bool] = None
    mt_delivery_target_ratio: Optional[float] = None
    mt_has_penalty: Optional[bool] = None
    mt_penalty_fee: Optional[float] = Field(None, description="违约金金额")
    mt_delivery_mode: Optional[int] = None
    mt_min_order_amount: Optional[float] = None
    mt_currency: Optional[str] = None

    # 退货条款
    return_policy: Optional[int] = None
    return_ratio: Optional[float] = None

    # 授权与激励
    # authorized_channels: Optional[int] = Field(None, description="授权渠道 1:线上 2:线下")
    # authorized_channels_next: Optional[int] = Field(None, description="授权渠道下一级 1:地区 2:渠道")
    is_online_channel: Optional[int] = Field(None, description="是否线上授权渠道")
    online_channel_text: Optional[str] = Field(None, description="线上授权渠道文本")
    is_offline_channel: Optional[int] = Field(None, description="是否线下授权渠道")
    offline_channel_text: Optional[str] = Field(None, description="线下授权渠道文本")

    reword_policy: Optional[int] = Field(None, description="奖励政策编码 1:季度采购激励 2:年度采购激励 3:其他")

    supplementary_agreement: Optional[List[Any]] = None
    attachments: Optional[List[Any]] = None
    business_license: Optional[List[Any]] = None
    previous_contract_id: Optional[int] = None
    contact_id: Optional[int] = None
    address_id: Optional[int] = None
    uncond_rebates: Optional[List[ContractUncondRebateIn]] = None
    cond_rebate_steps: Optional[List[ContractCondRebateStepIn]] = None

    class Config:
        arbitrary_types_allowed = True


class OfflineContractDeleteRequest(BaseModel):
    """删除合同；仅允许删除草稿等限定状态，见服务层校验与错误信息。"""

    _id: int = Field(
        ...,
        description="要删除的合同主键 `data_sys_offline_contract.id`；通常仅 `status=10`（草稿）可删",
    )
