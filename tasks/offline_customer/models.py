# -*- coding:utf-8-*-
# @FileName : models.py
# @Time     : 2024/11/25 16:44
# @Author   : yuhaiping
# @Email    : ping.yu@yaoyao-inc.com
# @Software : PyCharm
from sqlalchemy import (Column, String, Integer, BigInteger, Text, DateTime, func, ForeignKey, SmallInteger, Float,
                        Boolean, Date, JSON, Numeric)
from core.db.base import Base
from enum import Enum


class PaymentMethodEnum(Enum):
    BANK_TRANSFER = "银行转账"
    CHEQUE = "支票"
    CASH = "现金"
    NO_PAYMENT_REQUIRED = "无需支付"


class EffectiveNodeEnum(Enum):
    CUSTOMER_PICK = "客户提货"
    INVOICE_DATE = "发票日期"


class DeliveryMethodEnum(Enum):
    DELIVERY_TO_DC = "Delivery to DC"
    DELIVERY_TO_STORE = "Delivery to Store"
    DELIVERY_TO_CUSTOMER = "Delivery to Customer"
    SELF_PICKUP = "Self Pick Up"


class SettlementMethodEnum(Enum):
    DELIVERY_ON_CASH = "带款提货"
    DYNAMIC_ACCOUNT_PERIOD = "账期"
    FIXED_ACCOUNT_PERIOD = "固定账期"


CUSTOMER_TYPE_RELATIONS = {
    "MTR": ["Hyper", "Appliance Specialty", "Home Specialty", "Convenient Store", "New Retail"],
    "WHS": ["Exclusive Wholesaler", "Non-exclusive Wholesaler"],
    "COC": ["-"],  # Corporate Customers 无二层类型
    "SMALL": ["SMALL-"],
    "OFF": ["OFF-"],
    "OTH": ["OTH-"]
}


class CustomerTypeFirstEnum(Enum):
    MTR = "Modern Trade Retailer"
    WHS = "Wholesaler"
    COC = "Corporate Customers"
    SMALL = "Small B Buyers"
    OFF = "Off-price Buyer"
    OTH = "Others"

    @staticmethod
    def get_description(abbreviation):
        """根据简称获取全称"""
        for member in CustomerTypeFirstEnum:
            if member.name == abbreviation:
                return member.value
        return None


class CustomerTypeSecondEnum(Enum):
    HYPER = "Hyper"
    APPLIANCE_SPECIALITY = "Appliance Specialty"
    HOME_SPECIALITY = "Home Specialty"
    EXCLUSIVE_WHOLESALER = "Exclusive Wholesaler"
    NON_EXCLUSIVE_WHOLESALER = "Non-exclusive Wholesaler"
    CONVENIENT_STORE = "Convenient Store"
    # SMALL_B_BUYERS = "Small B buyers"




class OfflineCustomer(Base):
    __tablename__ = "data_sys_offline_customers"
    __table_args__ = {"comment": "线下客户信息表", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    customer_short_name = Column(String(255), nullable=False, comment="客户简称")
    customer_company_full_name = Column(String(255), comment="客户公司全称")
    customer_country = Column(String(64), comment="客户国家")
    customer_code = Column(String(128), nullable=False, unique=True, comment="客户编码")
    customer_type_first = Column(String(128), comment="客户类型一层")
    customer_type_second = Column(String(128), comment="客户类型二层")
    contact_frequency = Column(Integer, comment="联络频率")
    settlement_currency = Column(String(128), comment="结算币种")
    business_license = Column(JSON, comment="营业执照等资质附件列表，结构由前端/约定 JSON 模式定义")
    customer_files = Column(JSON, comment="客户资料附件列表，结构由前端/约定 JSON 模式定义")
    is_ka = Column(Integer, default=0, comment="是否KA")
    is_tax_free = Column(SmallInteger, nullable=False, default=0, comment="是否免税 0否1是")
    remark = Column(Text, comment="备注")
    cooperation_method = Column(
        SmallInteger, comment="合作方式 1批发 2一件代发"
    )

    # 拆分出的合同相关字段
    # contract_method = Column(String(128), comment="合同方式")
    # contract_points = Column(Float, comment="合同点数")
    # settlement_method = Column(String(128), comment="结算方式")
    # billing_period = Column(String(64), comment="账期")
    # payment_date_type = Column(String(64), comment="出账日范围")
    # payment_date = Column(String(64), comment="出账日")
    # effective_node = Column(String(128), comment="生效节点")
    # payment_method = Column(String(128), comment="支付方式")
    # prepayment_ratio = Column(Float, comment="预付比例")
    # recipient_name = Column(String(255), comment="收件人姓名")
    # recipient_phone_area = Column(String(32), comment="收件人手机区号")
    # recipient_phone = Column(String(64), comment="收件人号码")
    # recipient_country = Column(String(64), comment="收件人国家")
    # recipient_province = Column(String(128), comment="收件人省/州")
    # recipient_city = Column(String(128), comment="收件人城市")
    # recipient_district = Column(String(128), comment="收件人县/区")
    # recipient_address = Column(Text, comment="收件人详细地址")
    # recipient_post_code = Column(String(32), comment="收件人邮编")
    # delivery_method = Column(String(128), comment="提货方式")
    # carrier = Column(String(128), comment="默认物流商")
    # delivery_fee_payment = Column(String(128), comment="运费支付方")
    # delivery_remark = Column(Text, comment="提货备注")
    # company_materials = Column(JSON, comment="公司材料")

    # 合同新增
    customer_tag = Column(Integer, default=0, comment="客户标签,0:non-KA,1=KA")
    customer_status = Column(Integer, default=10, comment="客户生命周期状态：10=建联中(未与当前生效合同绑定或业务未生效) 20=生效中(存在生效合同且未过期) 30=已过期(无有效合同或业务判为过期)；与列表/统计口径以产品为准")
    yy_company_id = Column(BigInteger, comment="曜曜签约主体主键，关联 yy_company_info._id；客户维度的签约公司")
    current_contract_id = Column(BigInteger, comment="客户当前唯一生效或展示用的合同主键，冗余字段；权威合同数据仍在 data_sys_offline_contract，切换合同时需同步本字段")
    had_ever_effect = Column(Integer, default=0, comment="是否曾经生效过")

    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    create_by = Column(BigInteger, nullable=False, comment="创建人用户ID")
    update_by = Column(BigInteger, nullable=False, comment="最后更新人用户ID")


class OfflineCustomerFollowupRecord(Base):
    __tablename__ = "data_sys_offline_customers_follow_up_records"
    __table_args__ = {"comment": "线下客户随访记录表", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    offline_customer_id = Column(BigInteger, comment="线下客户id")
    company_contact_id = Column(Integer, comment="公司联系人,yy_user.id")
    # customer_contact_id = Column(Integer, comment="客户联系人,data_sys_offline_contract_contact._id")
    customer_contact_name = Column(String(128), comment="客户联系人姓名")
    contact_time = Column(DateTime, comment="联络时间")
    content = Column(Text, comment="随访内容")
    operator = Column(String(128), comment="操作人")
    operator_user_id = Column(BigInteger, comment="操作人id")
    invalid_ind = Column(Integer, comment='是否删除', default=0)
    create_date = Column(Date, server_default=func.now(), comment="创建日期")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class DataOfflineCustomerSku(Base):
    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    customer_code = Column(String(128), nullable=False, comment="客户编码")
    product_id = Column(String(255), nullable=True, comment="Product Id")
    sku = Column(String(255), nullable=True, comment="SKU")
    status = Column(SmallInteger, default=0, comment="是否启用")
    effective_date = Column(Date, default=func.now(), comment="起始生效时间")
    remark = Column(String(556), comment="备注")
    create_time = Column(DateTime, default=func.now(), comment="创建时间")
    update_time = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    create_by = Column(String(255), comment="创建人")
    update_by = Column(String(255), comment="更新人")


    __tablename__ = "data_offline_customer_sku"
    __table_args__ =  {"comment": "线下客户SKU表", "schema": "bi"}

class OfflineSellOutSales(Base):
    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    batch_number = Column(String(32), nullable=False, comment="客户编码")
    customer_code = Column(String(128), nullable=False, comment="客户编码")
    currency = Column(String(10), nullable=True, comment="币种")
    store_code = Column(String(255), nullable=True, comment="店铺编码")
    store_name = Column(String(255), nullable=True, comment="店铺名称")
    sales_date = Column(Date, nullable=True, comment="销售日期")
    sales = Column(Numeric(15, 4), nullable=True, comment="销售额")
    item_sold = Column(Integer, nullable=True, comment="销量")
    is_tax = Column(SmallInteger, nullable=True, comment="是否含税")
    product_id = Column(String(255), nullable=True, comment="Product Id")
    status = Column(SmallInteger, default=0, comment="是否启用")
    create_by = Column(String(64), nullable=True, comment="创建人")
    update_by = Column(String(64), nullable=True, comment="更新人")
    create_time = Column(DateTime, default=func.now(), comment="创建时间")
    update_time = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    __tablename__ = "data_offline_sell_out_sales"
    __table_args__ = {"comment": "线下客户SKU Sellout 销售明细数据表", "schema": "bi"}


class OfflineSellOutStock(Base):
    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    batch_number = Column(String(128), nullable=False, comment="客户编码")
    customer_code = Column(String(128), nullable=False, comment="客户编码")
    store_code = Column(String(255), nullable=True, comment="店铺编码")
    store_name = Column(String(255), nullable=True, comment="店铺名称")
    sales_date = Column(Date, nullable=True, comment="统计时间")
    stock_num = Column(Integer, nullable=True, comment="库存数")
    product_id = Column(String(255), nullable=True, comment="Product Id")
    status = Column(SmallInteger, default=0, comment="是否启用")
    create_by = Column(String(64), nullable=True, comment="创建人")
    update_by = Column(String(64), nullable=True, comment="更新人")
    create_time = Column(DateTime, default=func.now(), comment="创建时间")
    update_time = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    __tablename__ = "data_offline_sell_out_stock"
    __table_args__ = {"comment": "线下客户SKU Sellout 库存明细数据表", "schema": "bi"}


class ContractStatus:
    """合同主状态(初稿，与设计方案附录一致)。"""
    DRAFT = 10
    REVIEWING = 20
    PENDING_EFFECTIVE = 30
    EFFECTIVE = 40
    EXPIRED = 50


class OfflineContract(Base):
    __tablename__ = "data_sys_offline_contract"
    __table_args__ = {"comment": "线下合同主表", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    contract_no = Column(String(64), nullable=False, unique=True, comment="业务唯一合同编号")
    sign_date = Column(Date, comment="签订日")
    effective_start = Column(Date, comment="合同生效起")
    effective_end = Column(Date, comment="合同生效止")
    customer_id = Column(BigInteger, nullable=False, comment="客户ID data_sys_offline_customers")
    customer_code = Column(String(128), nullable=False, comment="客户编码快照")
    owner_staff_id = Column(BigInteger, nullable=False, comment="签订负责人 yy_user 等主键")
    status = Column(Integer, nullable=False, default=ContractStatus.DRAFT, comment="10草稿 20审核中 20审核 30待生效 40已生效 50已失效")
    current_step = Column(Integer, comment="当前审核环节序号")
    review_round = Column(Integer, nullable=False, default=1, comment="审核轮次")
    terminate_type = Column(Integer, comment="1自然到期2人工3被顶替")

    # 结算信息
    contract_method = Column(Integer, comment="合同方式如1寄售2非寄售")
    contract_points = Column(Float, comment="合同点数")
    settlement_method = Column(Integer, comment="结算方式")
    settlement_days = Column(Integer, comment="账期天数")
    billing_period = Column(Integer, comment="开账周期编码")
    effective_node = Column(String(128), comment="生效节点:1：客户提货， 2：发票日期 3 固定付款日， 4 分批结算")
    payment_date = Column(Integer, comment="出账日规则编码")
    payment_date_type = Column(Integer, comment="出账日类型编码")
    payment_method = Column(Integer, comment="付款方式编码")
    is_prepayment = Column(Integer, default=0, comment="是否预付")
    prepayment_ratio = Column(Numeric(9, 4), comment="预付比例")
    sample_policy = Column(Integer, comment="样品政策编码, 1:免费供样 2:折扣供样")
    sample_discount = Column(Numeric(9, 4), comment="样品折扣")
    bank_account_confirmation = Column(JSON, comment="银行账户材料JSON")
    front_margin = Column(Numeric(9, 4), comment="前台毛利")

    # 交付信息
    delivery_method = Column(Integer, comment="配送方式编码")
    carrier = Column(String(128), comment="物流商")
    delivery_fee_payment = Column(Integer, comment="运费支付方编码")
    delivery_remark = Column(Text, comment="配送备注")

    # 目标与激励
    mt_has_delivery_target = Column(Integer, nullable=False, default=0, comment="是否有送货率目标")
    mt_delivery_target_ratio = Column(Numeric(9, 4), comment="目标送货率")
    mt_has_penalty = Column(Integer, nullable=False, default=0, comment="是否有违约金")
    mt_penalty_fee = Column(Numeric(9, 4), comment="违约金金额")
    mt_delivery_mode = Column(Integer, comment="交付方式1一次性 2多批")
    mt_min_order_amount = Column(Numeric(18, 2), comment="起送/最小订单金额")
    mt_currency = Column(String(8), comment="现代通路最小起送金额对应币种")

    # 退货条款
    return_policy = Column(Integer, comment="退货政策编码")
    return_ratio = Column(Numeric(9, 4), comment="可退货比例")

    # authorized_channels = Column(Integer, comment="授权渠道 1:线上 2：线下 ")
    # authorized_channels_next = Column(Integer, comment="授权渠道下一级 1:地区 2：渠道 ")
    is_online_channel = Column(Integer, comment="是否线上授权渠道")
    online_channel_text = Column(Text, comment="线上授权渠道文本")
    is_offline_channel = Column(Integer, comment="是否线下授权渠道")
    offline_channel_text = Column(Text, comment="线下授权渠道文本")

    reword_policy = Column(Integer, comment="奖励政策编码,1:季度采购激励 2:年度采购激励, 3:其他")

    previous_contract_id = Column(BigInteger, comment="续签/旧合同主键")
    contact_id = Column(BigInteger, comment="合同联系人ID")
    address_id = Column(BigInteger, comment="合同地址ID")
    supplementary_agreement = Column(JSON, comment="补充协议")
    attachments = Column(JSON, comment="合同附件")
    business_license = Column(JSON, comment="改为普通附件")
    create_by = Column(BigInteger, nullable=False, comment="创建人用户ID")
    update_by = Column(BigInteger, nullable=False, comment="最后更新人用户ID")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    @property
    def id(self):
        return self._id


class OfflineContractContact(Base):
    __tablename__ = "data_sys_offline_contract_contact"
    __table_args__ = {"comment": "合同联系人", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    contract_id = Column(BigInteger, nullable=False, index=True, comment="合同ID")
    name = Column(String(128), comment="姓名")
    position = Column(String(128), comment="职位")
    phone_area = Column(String(16), comment="电话区号")
    phone = Column(String(64), comment="电话")
    email = Column(String(128), comment="邮箱")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")


class OfflineCustomerContact(Base):
    __tablename__ = "data_sys_offline_customer_contact"
    __table_args__ = {"comment": "客户联系人", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(BigInteger, nullable=False, index=True, comment="客户ID")
    name = Column(String(128),  comment="姓名")
    position = Column(String(128), comment="职位")
    contact_info = Column(String(64), comment="联系方式")
    remark = Column(String(1024), comment="备注")
    is_delete = Column(Integer, default=0, comment="是否删除")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class OfflineCustomerAddress(Base):
    __tablename__ = "data_sys_offline_customer_address"
    __table_args__ = {"comment": "客户地址", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(BigInteger, nullable=False, index=True, comment="客户ID")
    country = Column(String(64), comment="国家")
    province = Column(String(128), comment="省/州")
    city = Column(String(128), comment="城市")
    district = Column(String(128), comment="县/区")
    address = Column(String(1024), comment="详细地址")
    post_code = Column(String(32), comment="邮编")
    remark = Column(String(1024), comment="备注")
    is_delete = Column(Integer, default=0, comment="是否删除")
    create_by = Column(String(64), comment="创建人")
    update_by = Column(String(64), comment="更新人")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class OfflineContractAttachment(Base):
    __tablename__ = "data_sys_offline_contract_attachment"
    __table_args__ = {"comment": "合同附件", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    contract_id = Column(BigInteger, nullable=False, index=True, comment="合同ID")
    attachment_type = Column(Integer, comment="1银行证明2补充协议3扫描件9其他")
    file_name = Column(String(255), comment="原始文件名")
    file_url = Column(String(512), comment="存储URL或key")
    file_size = Column(BigInteger, comment="文件大小字节")
    uploaded_by = Column(BigInteger, comment="上传人用户ID")
    create_time = Column(DateTime, server_default=func.now(), comment="上传时间")


class OfflineContractUncondRebate(Base):
    __tablename__ = "data_sys_offline_contract_uncond_rebate"
    __table_args__ = {"comment": "合同-无条件返利项", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    contract_id = Column(BigInteger,  index=True, comment="合同ID")
    fee_category_id = Column(BigInteger,  comment="费用项类目ID")
    calc_method = Column(Integer,  comment="1比例2固定额")
    calc_base = Column(Integer, comment="比例计费基数类型")
    value = Column(Numeric(18, 4),  comment="返利值")
    currency = Column(String(8), comment="币种")
    remark = Column(Text, comment="行备注")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")


class OfflineContractCondRebateStep(Base):
    __tablename__ = "data_sys_offline_contract_cond_rebate_step"
    __table_args__ = {"comment": "合同-有条件返利台阶", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    contract_id = Column(BigInteger, nullable=False, index=True, comment="合同ID")
    step_no = Column(Integer, comment="台阶序号1..N")
    annual_purchase_amount = Column(Numeric(18, 2),  comment="年采购额门槛")
    rebate_ratio = Column(Numeric(9, 4), comment="返利比例")
    currency = Column(String(8), comment="币种")


class OfflineContractStatusLog(Base):
    """状态变更日志（设计方案 3.8）"""

    __tablename__ = "data_sys_offline_contract_status_log"
    __table_args__ = {"comment": "合同状态变更日志", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True)
    contract_id = Column(BigInteger, nullable=False, index=True)
    from_status = Column(Integer, nullable=True)
    to_status = Column(Integer, nullable=False)
    from_step = Column(Integer, nullable=True)
    to_step = Column(Integer, nullable=True)
    action_code = Column(Integer, nullable=True, comment="附录A.12")
    operator_id = Column(BigInteger, nullable=True)
    operator_role = Column(Integer, nullable=True, comment="附录A.13")
    trigger_type = Column(Integer, nullable=False, default=1, comment="附录A.14 1人工")
    remark = Column(Text, nullable=True)
    create_time = Column(DateTime, server_default=func.now())


class ContractApprovalConfig(Base):
    """合同审批链配置（全局一条链：启用行按 step_no 升序，供 contract_workflow_engine 加载）。 """

    __tablename__ = "data_sys_offline_contract_approval_config"
    __table_args__ = (
        {"comment": "线下合同审批链配置", "schema": "internal_app"},
    )

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    step_no = Column(Integer, nullable=False, comment="环节序号 1..N，全表唯一")
    role_id = Column(Integer, nullable=True, comment="办事角色码，关联data_sys_offline_contract_status_log.operator_role, business_role.role_id")
    role_name = Column(String(64), nullable=True, comment="办事角色名，可选")
    is_active = Column(Boolean, nullable=False, default=True, comment="0停用 1启用")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")