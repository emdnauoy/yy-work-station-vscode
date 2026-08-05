# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/25
# @Author  : Zhu Yaming
# @File    : models.py
# @Description : 分销订单 ORM，与 schema.sql 一一对应
"""
from __future__ import annotations

import copy
import json
from typing import Any

from sqlalchemy import (
    BigInteger, Column, Date, DateTime, Integer,
    JSON, Numeric, SmallInteger, String, Text,
    UniqueConstraint, func, text,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import TypeDecorator

# 软删：0=正常 1=已删；仅 service 写；删传 _id；同单未删 SKU 唯一由 service 校验
_IS_DELETE_COL = dict(
    nullable=False, server_default=text("0"),
    comment="软删 0=正常 1=已删(仅service写,删传_id)",
)

Base = declarative_base()


def _is_empty_json_scalar(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        return val.strip().lower() in ("", "null", "none", "undefined")
    return False


def normalize_json_column(val: Any) -> Any:
    """JSON 列落库：null/空串/字符串 null → None；仅保留 dict/list 结构。"""
    if val is None:
        return None
    if isinstance(val, bytes):
        try:
            val = val.decode("utf-8")
        except Exception:
            return None
    if isinstance(val, str):
        s = val.strip()
        if _is_empty_json_scalar(s):
            return None
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            return None
        return normalize_json_column(parsed)
    if isinstance(val, dict):
        return copy.deepcopy(val)
    if isinstance(val, list):
        return copy.deepcopy(val)
    return None


class NormalizedJSON(TypeDecorator):
    """绑定参数/读出时强制 normalize_json_column；MySQL 用方言 JSON 类型。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "mysql":
            from sqlalchemy.dialects.mysql import JSON as MySQLJSON
            return dialect.type_descriptor(MySQLJSON())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return normalize_json_column(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return normalize_json_column(value)


_ORDER_JSON_KEYS = ("customer_po_attachments", "ship_guide_attachments")


class DistributionOrder(Base):
    __tablename__ = "data_distribution_order"
    __table_args__ = {"schema": "internal_app", "comment": "分销订单主表"}

    # ── 基础信息（单号 / 拆单 / 主状态 / 当前审批链 / 当前步）──────────────────────
    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_sn = Column(String(48), nullable=False, unique=True, comment="WS分销单号 B2B+国家+日期+随机后缀(暂)；子单含后缀-A")
    parent_order_id = Column(BigInteger, nullable=True, comment="拆单父单_id；NULL=主单")
    status = Column(SmallInteger, nullable=False, default=10, comment="主状态 10=草稿 20=报价审核 30=订单创建 40=订单审核 50=确认预付 60=待下发 70=履约中 80=待回款 90=已完成 99=已作废")
    void_from_status = Column(SmallInteger, nullable=True, comment="作废前主状态；仅 status=99 时有值")
    current_chain_code = Column(SmallInteger, nullable=True, comment="当前审批链 1=定价审批 2=订单审批-标准 3=订单审批-大额；NULL=非审核中")
    current_step = Column(Integer, nullable=True, comment="当前待审环节序号（对应 approval_config.step_no）；NULL=非审核中")
    quote_lm_user_id = Column(Integer, nullable=True, comment="报价审核直线上级用户_id")
    order_lm_user_id = Column(Integer, nullable=True, comment="订单审核直线上级用户_id")

    # ── 客户快照 ─────────────────────────────────────────────────────────────────
    offline_customer_id = Column(BigInteger, nullable=False, comment="线下客户 data_sys_offline_customers._id")
    contract_id = Column(BigInteger, nullable=True, comment="生效合同 data_sys_offline_contract._id")
    customer_code = Column(String(128), nullable=False, default="", comment="客户编码快照")
    customer_short_name = Column(String(255), nullable=False, default="", comment="客户简称快照")
    customer_country = Column(String(64), nullable=True, comment="客户国家快照")
    customer_type_first = Column(String(128), nullable=True, comment="客户类型一层快照")
    customer_type_second = Column(String(128), nullable=True, comment="客户类型二层快照")
    is_prepayment = Column(SmallInteger, nullable=False, default=0, comment="是否预付快照(合同 is_prepayment) 0=无预付 1=预付比例")
    prepayment_ratio = Column(Numeric(9, 4), nullable=False, default=0, comment="预付比例快照(合同 prepayment_ratio)")
    settlement_method = Column(SmallInteger, nullable=True, comment="结算方式编码快照 1=带款提货 2=账期(列表筛选)")
    cooperation_method = Column(
        SmallInteger, nullable=True,
        comment="合作方式快照 1批发 2一件代发(来自线下客户)",
    )

    # ── 销售结算 ───────────────────────────────────────────────────────────────
    customer_po_attachments = Column(NormalizedJSON, nullable=True, comment="客户采购单文件附件")
    oa_seal_no = Column(String(64), nullable=True, comment="用印OA编号")
    is_tax_free = Column(SmallInteger, nullable=False, default=0, comment="是否免税 0否1是")
    is_ewt = Column(SmallInteger, nullable=False, default=0, comment="是否预扣税 0否1是")
    vat_rate = Column(Numeric(9, 4), nullable=True, comment="VAT税率")
    ewt_rate = Column(Numeric(9, 4), nullable=True, comment="预扣税比例")
    currency = Column(String(8), nullable=True, comment="币种")
    order_delivery_fee_payment = Column(SmallInteger, nullable=True, comment="本次运费承担方 1=Simplus Pay 2=Customer Pay")
    freight_with_vat = Column(Numeric(18, 2), nullable=True, comment="含增值税运费收入")
    freight_without_vat = Column(Numeric(18, 2), nullable=True, comment="不含增值税运费收入")
    goods_amount_with_vat = Column(Numeric(18, 2), nullable=True, comment="含增值税商品总额")
    goods_amount_without_vat = Column(Numeric(18, 2), nullable=True, comment="不含增值税商品总额")
    order_amount_with_vat = Column(Numeric(18, 2), nullable=True, comment="含增值税订单总额")
    order_amount_without_vat = Column(Numeric(18, 2), nullable=True, comment="不含增值税订单总额")
    vat_amount_total = Column(Numeric(18, 2), nullable=True, comment="订单VAT税额汇总")
    prepay_amount = Column(Numeric(18, 2), nullable=True, comment="预付款金额")
    ewt_amount = Column(Numeric(18, 2), nullable=True, comment="预扣税税额")
    balance_amount = Column(Numeric(18, 2), nullable=True, comment="尾款金额")
    adjusted_balance_amount = Column(Numeric(18, 2), nullable=True, comment="最新调整后尾款应收")
    expected_payment_date = Column(Date, nullable=True, comment="预计回款日期")
    actual_payment_date = Column(Date, nullable=True, comment="实际回款日期")

    # ── 物流履约 ─────────────────────────────────────────────────────────────────
    ship_method = Column(String(128), nullable=True, comment="发货方式")
    expected_ship_date = Column(Date, nullable=True, comment="期望出库日期")
    actual_ship_date = Column(Date, nullable=True, comment="实际出库日期")
    ship_remark = Column(String(800), nullable=True, comment="发货备注")

    # ── 履约 & 物流 ──────────────────────────────────────────────────────────────
    shop_id = Column(String(256), nullable=True, comment="出库店铺id，yy_public_join.shopee_shop_id")
    sales_user_id = Column(BigInteger, nullable=True, comment="本单销售员_id")
    system_tracking_number = Column(String(64), nullable=True, comment="千易单号（下发成功后写入）")
    waybill_no = Column(String(64), nullable=True, comment="运单号")
    ship_guide_attachments = Column(NormalizedJSON, nullable=True, comment="发货指导文件")

    # ── 备注 ─────────────────────────────────────────────────────────────────────
    remark = Column(Text, nullable=True, comment="订单备注")
    batch_id = Column(String(64), nullable=True, index=True, comment="批量建单批次号；普通单 NULL")
    customer_po_no = Column(String(128), nullable=True, comment="客户侧订单号")
    create_source = Column(
        SmallInteger, nullable=False, default=0,
        comment="创建来源 0普通 1一件代发批量",
    )

    # ── 标签 ─────────────────────────────────────────────────────────────────────
    order_status = Column(String(64), nullable=True, comment="千易订单状态")
    online_status = Column(String(64), nullable=True, comment="线上订单状态")
    logistic_status = Column(String(64), nullable=True, comment="物流状态")
    warehouse = Column(String(64), nullable=True, comment="仓库")
    tags_bitmask = Column(Integer, nullable=True, comment="标签位图缓存 bit0(1)=价偏 bit1(2)=大额 bit2(4)=样品 bit3(8)=缺货 bit4(16)=拆单 bit5(32)=特殊作业 bit6(64)=紧急 bit7(128)=实收差异 bit8(256)=回款超期 bit9(512)=待传水单")
    # 首页待办同步标记（见 distribution_order_todo.py；对齐 audit_center.todo_synced）
    quote_approval_todo_synced_step = Column(
        Integer, nullable=True,
        comment="报价审核待办已推送的环节序号；NULL=未推送，≠current_step时需重推",
    )
    order_approval_todo_synced_step = Column(
        Integer, nullable=True,
        comment="订单审核待办已推送的环节序号；NULL=未推送，≠current_step时需重推",
    )
    prepay_todo_synced = Column(
        TINYINT(unsigned=True), nullable=False, default=0,
        comment="确认预付待办是否已推送 0=否 1=是",
    )
    payment_todo_synced = Column(
        TINYINT(unsigned=True), nullable=False, default=0,
        comment="待回款待办是否已推送 0=否 1=是",
    )

    # ── 审计 & 软删 ──────────────────────────────────────────────────────────────
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    create_by = Column(Integer, nullable=True, comment="创建人")
    submit_by = Column(Integer, nullable=True, comment="提交审核发起人(报价/订单 submit 时写入)")
    update_by = Column(Integer, nullable=True, comment="更新人")
    is_delete = Column(TINYINT(unsigned=True), **_IS_DELETE_COL)


class DistributionOrderSnapshot(Base):
    __tablename__ = "data_distribution_order_snapshot"
    __table_args__ = {
        "schema": "internal_app",
        "comment": "分销订单扩展快照(1:1主表)",
    }

    order_id = Column(BigInteger, primary_key=True, comment="主单 data_distribution_order._id")
    name = Column(String(128), nullable=True, comment="联系人姓名快照(主仓 name)")
    position = Column(String(128), nullable=True, comment="联系人职位快照")
    contact_info = Column(String(64), nullable=True, comment="联系方式快照")
    contact_remark = Column(String(1024), nullable=True, comment="联系人备注快照")
    country = Column(String(64), nullable=True, comment="收货国家快照")
    province = Column(String(128), nullable=True, comment="收货省份快照")
    city = Column(String(128), nullable=True, comment="收货城市快照")
    district = Column(String(128), nullable=True, comment="收货区县快照")
    address = Column(String(1024), nullable=True, comment="收货详细地址快照")
    post_code = Column(String(32), nullable=True, comment="邮编快照")
    address_remark = Column(String(1024), nullable=True, comment="地址备注快照")
    contract_no = Column(String(64), nullable=True, comment="合同编号快照")
    effective_start = Column(Date, nullable=True, comment="合同有效期开始")
    effective_end = Column(Date, nullable=True, comment="合同有效期结束")
    effective_node = Column(Integer, nullable=True, comment="生效节点:1：客户提货， 2：发票日期 3 固定付款日， 4 分批结算")
    owner_staff_id = Column(BigInteger, nullable=True, comment="曜曜签订负责人 staff_id")
    uncond_rebate_ratio = Column(Numeric(9, 4), nullable=True, comment="无条件返利比例")
    settlement_days = Column(Integer, nullable=True, comment="账期天数(结算方式=账期)")
    settlement_currency = Column(String(12), nullable=True, comment="结算币种快照")
    delivery_method = Column(SmallInteger, nullable=True, comment="交付方式编码快照")
    mt_delivery_mode = Column(Integer, comment="交付方式1一次性 2多批")
    carrier = Column(String(128), nullable=True, comment="运输及配送/承运商快照")
    delivery_remark = Column(Text, nullable=True, comment="运输及配送备注快照")
    sample_policy = Column(SmallInteger, nullable=True, comment="样品政策编码快照")
    sample_discount = Column(Numeric(9, 4), nullable=True, comment="样品折扣快照")
    delivery_fee_payment = Column(SmallInteger, nullable=True, comment="合同运费承担方快照")
    bank_account_confirmation = Column(NormalizedJSON, nullable=True, comment="客户银行账户信息(JSON快照)")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class DistributionOrderQuoteDetail(Base):
    __tablename__ = "data_distribution_order_quote_detail"
    __table_args__ = {
        "schema": "internal_app",
        "comment": "分销订单报价明细(每SKU报价)",
    }

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(BigInteger, nullable=False, index=True, comment="主单_id data_distribution_order._id")
    sku = Column(String(64), nullable=False, default="", comment="报价单-SKU（下拉选商品）")
    price_with_vat = Column(Numeric(18, 4), nullable=True, comment="报价单-含增值税报价（手动）")
    price_without_vat = Column(Numeric(18, 4), nullable=True, comment="报价单-不含增值税单价（保存时按VAT计算落库）")
    qty = Column(Integer, nullable=True, comment="报价单-销售数量（手动）")
    guide_price = Column(Numeric(18, 4), nullable=True, comment="报价单-指导价（保存时定价快照）")
    red_line_price = Column(Numeric(18, 4), nullable=True, comment="报价单-红线价（保存时定价快照）")
    amount_with_vat = Column(Numeric(18, 2), nullable=True, comment="报价单-行含税金额（保存时计算落库）")
    amount_without_vat = Column(Numeric(18, 2), nullable=True, comment="报价单-行不含税金额（保存时计算落库）")
    vat_amount = Column(Numeric(18, 2), nullable=True, comment="报价单-行VAT税额（保存时计算落库）")
    stock_on_hand = Column(Integer, nullable=True, comment="报价单-库存现货（保存时快照）")
    stock_in_transit = Column(Integer, nullable=True, comment="报价单-在途库存（保存时快照）")
    stock_planned = Column(Integer, nullable=True, comment="报价单-计划库存（保存时快照）")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    is_delete = Column(TINYINT(unsigned=True), **_IS_DELETE_COL)


class DistributionOrderItemDetail(Base):
    __tablename__ = "data_distribution_order_item_detail"
    __table_args__ = {
        "schema": "internal_app",
        "comment": "分销订单明细(订单创建阶段每SKU)",
    }

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(BigInteger, nullable=False, index=True, comment="主单_id data_distribution_order._id")
    sku = Column(String(64), nullable=False, default="", comment="订单创建-SKU编码（手动）")
    price_with_vat = Column(Numeric(18, 4), nullable=True, comment="订单创建-含增值税单价（手动）")
    price_without_vat = Column(Numeric(18, 4), nullable=True, comment="订单创建-不含增值税单价（保存时按VAT计算）")
    qty = Column(Integer, nullable=True, comment="订单创建-销售数量（手动）")
    guide_price = Column(Numeric(18, 4), nullable=True, comment="订单创建-指导价（保存时定价快照）")
    red_line_price = Column(Numeric(18, 4), nullable=True, comment="订单创建-红线价（保存时定价快照）")
    amount_with_vat = Column(Numeric(18, 2), nullable=True, comment="订单创建-行含税金额（保存时计算）")
    amount_without_vat = Column(Numeric(18, 2), nullable=True, comment="订单创建-行不含税金额（保存时计算）")
    freight_with_vat = Column(Numeric(18, 2), nullable=True, comment="含增值税运费收入")
    freight_without_vat = Column(Numeric(18, 2), nullable=True, comment="不含增值税运费收入")
    order_amount_with_vat = Column(Numeric(18, 2), nullable=True, comment="含增值税订单总额，amount_with_vat+ freight_with_vat ")
    order_amount_without_vat = Column(Numeric(18, 2), nullable=True, comment="不含增值税订单总额, amount_without_vat + freight_without_vat")
    vat_amount = Column(Numeric(18, 2), nullable=True, comment="订单创建-行VAT税额（保存时计算）")
    stock_on_hand = Column(Integer, nullable=True, comment="订单创建-库存现货（保存时快照）")
    stock_in_transit = Column(Integer, nullable=True, comment="订单创建-在途库存（保存时快照）")
    stock_planned = Column(Integer, nullable=True, comment="订单创建-计划库存（保存时快照）")
    is_protocol_sample = Column(SmallInteger, nullable=False, default=0, comment="订单创建-协议样品 0否1是（手动）")
    quote_check_passed = Column(SmallInteger, nullable=False, default=0, comment="订单创建-报价校验 0否1是（保存时计算）")
    dispatched_qty = Column(Integer, nullable=False, default=0, comment="已下发数量（履约）")
    received_qty = Column(Integer, nullable=True, comment="实收数量（履约后填）")
    receive_diff_remark = Column(String(800), nullable=True, comment="实收差异原因")
    dispatch_stock_on_hand = Column(Integer, nullable=True, comment="下发时库存现货快照")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    is_delete = Column(TINYINT(unsigned=True), **_IS_DELETE_COL)


class DistributionOrderStatusLog(Base):
    __tablename__ = "data_distribution_order_status_log"
    __table_args__ = {"schema": "internal_app", "comment": "分销订单状态迁移日志"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(BigInteger, nullable=False, index=True, comment="订单主键 data_distribution_order._id")
    from_status = Column(Integer, nullable=True, comment="变更前主状态；首条可为NULL")
    to_status = Column(Integer, nullable=False, comment="变更后主状态")
    action_code = Column(Integer, nullable=True, comment="业务动作 code")
    operator_id = Column(BigInteger, nullable=True, comment="操作人_id")
    operator_role = Column(Integer, nullable=True, comment="操作人角色")
    trigger_type = Column(Integer, nullable=False, default=1, comment="触发类型 1人工 3审批")
    remark = Column(Text, nullable=True, comment="备注/审批意见")
    from_chain_code = Column(SmallInteger, nullable=True, comment="变更前审批链")
    to_chain_code = Column(SmallInteger, nullable=True, comment="变更后审批链")
    from_step = Column(Integer, nullable=True, comment="变更前环节")
    to_step = Column(Integer, nullable=True, comment="变更后环节")
    role_name = Column(String(64), nullable=True, comment="环节角色名快照")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")


class DistributionOrderApprovalConfig(Base):
    __tablename__ = "data_distribution_order_approval_config"
    __table_args__ = {"schema": "internal_app", "comment": "分销订单审批链配置"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    chain_code = Column(SmallInteger, nullable=False, comment="审批链 1定价 2订单标准 3订单大额")
    step_no = Column(Integer, nullable=False, comment="环节序号")
    approver_type = Column(SmallInteger, nullable=False, default=2, comment="审批人类型 1直线上级 2角色")
    role_id = Column(Integer, nullable=False, default=0, comment="办事角色role_id")
    role_name = Column(String(64), nullable=False, default="", comment="办事角色名称快照")
    is_active = Column(SmallInteger, nullable=False, default=1, comment="是否启用 0否1是")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class DistributionOrderAdjustment(Base):
    __tablename__ = "data_distribution_order_adjustment"
    __table_args__ = {"schema": "internal_app", "comment": "分销订单手工调整"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(BigInteger, nullable=False, index=True, comment="订单主键 data_distribution_order._id")
    seq = Column(Integer, nullable=False, default=1, comment="调整序号(同单递增)")
    adjust_amount = Column(Numeric(18, 2), nullable=False, default=0, comment="手工调整金额")
    fee_category_id = Column(BigInteger, nullable=True, comment="费用项类目ID")
    document_attachments = Column(NormalizedJSON, nullable=True, comment="单据附件")
    remark = Column(String(800), nullable=True, comment="调整备注")
    adjusted_balance_after = Column(Numeric(18, 2), nullable=True, comment="本条后调整后尾款应收")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    create_by = Column(Integer, nullable=True, comment="确认人_id")


class DistributionOrderPrepayment(Base):
    __tablename__ = "data_distribution_order_prepayment"
    __table_args__ = (
        UniqueConstraint("order_id", name="uk_order_id"),
        {"schema": "internal_app", "comment": "分销订单预付款确认记录"},
    )

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(BigInteger, nullable=False, index=True, comment="订单主键 data_distribution_order._id")
    amount_due = Column(Numeric(18, 2), nullable=True, comment="应付预付款")
    amount_paid = Column(Numeric(18, 2), nullable=True, comment="实付预付款")
    diff_remark = Column(String(800), nullable=True, comment="差异备注（PRD 800字）")
    attachments = Column(NormalizedJSON, nullable=True, comment="水单附件")
    system_tracking_number = Column(String(64), nullable=True, comment="千易单号快照（确认时从主单同步）")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    create_by = Column(Integer, nullable=True, comment="确认人_id")


class DistributionOrderBalancePayment(Base):
    __tablename__ = "data_distribution_order_balance_payment"
    __table_args__ = (
        UniqueConstraint("order_id", name="uk_order_id"),
        {"schema": "internal_app", "comment": "分销订单尾款确认记录"},
    )

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(BigInteger, nullable=False, index=True, comment="订单主键 data_distribution_order._id")
    amount_due = Column(Numeric(18, 2), nullable=True, comment="应付尾款（含调整后）")
    amount_paid = Column(Numeric(18, 2), nullable=True, comment="实付尾款")
    payment_date = Column(Date, nullable=True, comment="回款日期")
    diff_remark = Column(String(800), nullable=True, comment="差异备注（PRD 800字）")
    attachments = Column(NormalizedJSON, nullable=True, comment="水单附件")
    system_tracking_number = Column(String(64), nullable=True, comment="千易单号快照（确认时从主单同步）")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    create_by = Column(Integer, nullable=True, comment="确认人_id")


class DistributionFrameworkQuote(Base):
    __tablename__ = "data_distribution_framework_quote"
    __table_args__ = {
        "schema": "internal_app",
        "comment": "分销一件代发框架报价头",
    }

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    offline_customer_id = Column(
        BigInteger, nullable=False, index=True,
        comment="线下客户 data_sys_offline_customers._id",
    )
    currency = Column(String(8), nullable=True, comment="币种")
    remark = Column(String(800), nullable=True, comment="备注")
    is_delete = Column(TINYINT(unsigned=True), **_IS_DELETE_COL)
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
    create_by = Column(Integer, nullable=True, comment="创建人")
    update_by = Column(Integer, nullable=True, comment="更新人")


class DistributionFrameworkQuoteLine(Base):
    __tablename__ = "data_distribution_framework_quote_line"
    __table_args__ = {
        "schema": "internal_app",
        "comment": "分销一件代发框架报价明细",
    }

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    framework_quote_id = Column(
        BigInteger, nullable=False, index=True,
        comment="框架头 data_distribution_framework_quote._id",
    )
    sku = Column(String(64), nullable=False, default="", comment="SKU编码")
    price_with_vat = Column(
        Numeric(18, 4), nullable=True, comment="含增值税单价(价目参考)",
    )
    is_delete = Column(TINYINT(unsigned=True), **_IS_DELETE_COL)
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")
    update_time = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
