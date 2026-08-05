# -*- coding: utf-8 -*-
"""
# @Time    : 2026/5/25
# @Author  : Zhu Yaming
# @File    : schemas.py
# @Description : 分销订单 Pydantic v1 读写模型
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, Field, root_validator, validator

_TConfirmOut = TypeVar("_TConfirmOut", bound=BaseModel)

from apps.system.distribution_order.models import normalize_json_column


# ── 行模型 ───────────────────────────────────────────────────────────────────


class LineDetailIn(BaseModel):
    """报价/订单明细批量保存行：无 _id=新增；有 _id=更新；有 _id 且 is_delete≠0=软删。"""

    id: Optional[int] = Field(None, alias="_id", description="行主键；新增不传")
    sku: Optional[str] = Field(None, max_length=64, description="SKU编码")
    price_with_vat: Optional[Decimal] = Field(None, description="含增值税单价/报价")
    price_without_vat: Optional[Decimal] = Field(None, description="不含增值税单价")
    qty: Optional[int] = Field(None, ge=0, description="销售数量")
    guide_price: Optional[Decimal] = Field(None, description="指导价快照")
    red_line_price: Optional[Decimal] = Field(None, description="红线价快照")
    amount_with_vat: Optional[Decimal] = Field(None, description="含增值税行总额")
    amount_without_vat: Optional[Decimal] = Field(None, description="不含增值税行总额")
    vat_amount: Optional[Decimal] = Field(None, description="行VAT税额")
    stock_on_hand: Optional[int] = Field(None, description="在库库存快照")
    stock_in_transit: Optional[int] = Field(None, description="在途库存快照")
    stock_planned: Optional[int] = Field(None, description="计划库存快照")
    is_delete: Optional[int] = Field(
        0, ge=0, le=1,
        description="0=新增/更新；1=软删(须带_id，仅批量save)",
    )

    class Config:
        allow_population_by_field_name = True


class QuoteDetailIn(LineDetailIn):
    """报价明细行（草稿/报价审核）。"""


class OrderDetailIn(LineDetailIn):
    """订单明细行（订单创建阶段，与报价明细独立录入）。"""

    is_protocol_sample: Optional[int] = Field(
        0, ge=0, le=1, description="协议样品 0否1是",
    )
    freight_with_vat: Optional[Decimal] = Field(
        None, description="含增值税运费收入（行级；批量建单时写入）",
    )


class LineDetailBatchSaveIn(BaseModel):
    """明细批量保存：lines 内用 _id / is_delete 区分增删改。"""

    order_id: int = Field(..., gt=0, description="主单_id")
    lines: List[LineDetailIn] = Field(default_factory=list, description="明细行")


class QuoteDetailBatchSaveIn(LineDetailBatchSaveIn):
    lines: List[QuoteDetailIn] = Field(default_factory=list)


class OrderDetailBatchSaveIn(LineDetailBatchSaveIn):
    lines: List[OrderDetailIn] = Field(default_factory=list)


class LineDetailDeleteIn(BaseModel):
    """明细批量软删。"""

    order_id: int = Field(..., gt=0, description="主单_id")
    detail_ids: List[int] = Field(
        ..., min_items=1, description="待软删行_id列表",
    )


class QuoteDetailOut(BaseModel):
    id: int = Field(..., alias="_id")
    sku: str
    price_with_vat: Optional[Decimal] = None
    price_without_vat: Optional[Decimal] = None
    qty: Optional[int] = None
    guide_price: Optional[Decimal] = None
    red_line_price: Optional[Decimal] = None
    amount_with_vat: Optional[Decimal] = None
    amount_without_vat: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    stock_on_hand: Optional[int] = None
    stock_in_transit: Optional[int] = None
    stock_planned: Optional[int] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class OrderDetailOut(BaseModel):
    id: int = Field(..., alias="_id")
    sku: str
    price_with_vat: Optional[Decimal] = None
    price_without_vat: Optional[Decimal] = None
    qty: Optional[int] = None
    guide_price: Optional[Decimal] = None
    red_line_price: Optional[Decimal] = None
    amount_with_vat: Optional[Decimal] = None
    amount_without_vat: Optional[Decimal] = None
    freight_with_vat: Optional[Decimal] = None
    freight_without_vat: Optional[Decimal] = None
    order_amount_with_vat: Optional[Decimal] = None
    order_amount_without_vat: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    stock_on_hand: Optional[int] = None
    stock_in_transit: Optional[int] = None
    stock_planned: Optional[int] = None
    is_protocol_sample: int = 0
    quote_check_passed: int = 0
    dispatched_qty: int = 0
    received_qty: Optional[int] = None
    receive_diff_remark: Optional[str] = None
    dispatch_stock_on_hand: Optional[int] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


# ── 扩展快照（§4.1b，ORM DistributionOrderSnapshot）──────────────────────────


class DistributionOrderSnapshotIn(BaseModel):
    """联系人/地址/合同扩展快照写入，落 data_distribution_order_snapshot。"""

    name: Optional[str] = Field(None, max_length=128, description="联系人姓名快照")
    position: Optional[str] = Field(None, max_length=128, description="联系人职位快照")
    contact_info: Optional[str] = Field(None, max_length=64, description="联系方式快照")
    contact_remark: Optional[str] = Field(None, max_length=1024, description="联系人备注快照")
    country: Optional[str] = Field(None, max_length=64, description="地址-国家")
    province: Optional[str] = Field(None, max_length=128, description="地址-省/州")
    city: Optional[str] = Field(None, max_length=128, description="地址-城市")
    district: Optional[str] = Field(None, max_length=128, description="地址-县/区")
    address: Optional[str] = Field(None, max_length=1024, description="详细地址")
    post_code: Optional[str] = Field(None, max_length=32, description="邮编")
    address_remark: Optional[str] = Field(None, max_length=1024, description="地址备注")
    contract_no: Optional[str] = Field(None, max_length=64, description="合同编号快照")
    effective_start: Optional[date] = Field(None, description="合同生效起")
    effective_end: Optional[date] = Field(None, description="合同生效止")
    effective_node: Optional[int] = Field(None, description="生效节点")
    owner_staff_id: Optional[int] = Field(None, description="签订负责人用户_id")
    uncond_rebate_ratio: Optional[Decimal] = Field(None, description="无条件返利比例快照")
    settlement_days: Optional[int] = Field(None, ge=0, description="账期天数快照")
    settlement_currency: Optional[str] = Field(None, max_length=12, description="结算币种快照")
    delivery_method: Optional[int] = Field(None, description="配送方式编码快照 1指定地点2配送中心3自提")
    carrier: Optional[str] = Field(None, max_length=128, description="运输物流商快照")
    delivery_remark: Optional[str] = Field(None, description="运输配送备注快照")
    sample_policy: Optional[int] = Field(None, description="样品政策编码快照 1免费2折扣")
    sample_discount: Optional[Decimal] = Field(None, description="样品折扣快照")
    delivery_fee_payment: Optional[int] = Field(
        None, description="合同运费承担方编码快照 1=Simplus Pay 2=Customer Pay"
    )
    mt_delivery_mode: Optional[int] = Field(None, description="交付方式1一次性 2多批")
    bank_account_confirmation: Optional[Any] = Field(None, description="银行账户确认JSON快照")

    class Config:
        allow_population_by_field_name = True


class DistributionOrderSnapshotOut(BaseModel):
    """扩展快照读出（详情 service 与主表字段合并返回）。"""

    name: Optional[str] = None
    position: Optional[str] = None
    contact_info: Optional[str] = None
    contact_remark: Optional[str] = None
    country: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    post_code: Optional[str] = None
    address_remark: Optional[str] = None
    contract_no: Optional[str] = None
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    effective_node: Optional[int] = None
    owner_staff_id: Optional[int] = None
    uncond_rebate_ratio: Optional[Decimal] = None
    settlement_days: Optional[int] = None
    settlement_currency: Optional[str] = None
    delivery_method: Optional[int] = None
    carrier: Optional[str] = None
    delivery_remark: Optional[str] = None
    sample_policy: Optional[int] = None
    sample_discount: Optional[Decimal] = None
    delivery_fee_payment: Optional[int] = None
    bank_account_confirmation: Optional[Any] = None
    mt_delivery_mode: Optional[int] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


# ── 主单写入 ─────────────────────────────────────────────────────────────────


class DistributionOrderDraftIn(DistributionOrderSnapshotIn):
    """草稿/报价阶段保存（主表热字段 + 扩展快照 + 报价明细）。"""

    id: Optional[int] = Field(None, alias="_id", description="主键，新增可空")
    offline_customer_id: Optional[int] = Field(None, gt=0, description="客户_id")
    contract_id: Optional[int] = Field(None, gt=0, description="生效合同_id")
    customer_code: Optional[str] = Field(None, max_length=128, description="客户编码快照")
    customer_short_name: Optional[str] = Field(None, max_length=255, description="客户简称快照")
    customer_country: Optional[str] = Field(None, max_length=64, description="客户国家快照")
    customer_type_first: Optional[str] = Field(None, max_length=128, description="客户类型一层快照")
    customer_type_second: Optional[str] = Field(None, max_length=128, description="客户类型二层快照")
    is_prepayment: Optional[int] = Field(None, ge=0, le=1, description="是否预付快照 0无1有")
    shop_id: Optional[str] = Field(None, description="出库店铺_id")
    sales_user_id: Optional[int] = Field(None, description="本单销售员_id")
    is_tax_free: Optional[int] = Field(0, ge=0, le=1, description="是否免税")
    vat_rate: Optional[Decimal] = Field(None, description="VAT税率")
    is_ewt: Optional[int] = Field(0, ge=0, le=1, description="是否预扣税")
    ewt_rate: Optional[Decimal] = Field(None, description="预扣税比例")
    currency: Optional[str] = Field(None, max_length=8, description="币种")
    prepayment_ratio: Optional[Decimal] = Field(None, description="预付比例快照")
    settlement_method: Optional[int] = Field(
        None, description="结算方式编码快照 1=带款提货 2=账期(主表,可筛选)",
    )
    cooperation_method: Optional[int] = Field(
        None, description="合作方式快照 1批发 2一件代发",
    )
    remark: Optional[str] = Field(None, description="订单备注")
    quote_details: List[QuoteDetailIn] = Field(default_factory=list, description="报价明细(每SKU报价)")
    deleted_quote_detail_ids: List[int] = Field(
        default_factory=list,
        description="兼容：软删行_id；推荐在 quote_details 传 _id+is_delete=1",
    )

    class Config:
        allow_population_by_field_name = True


class DistributionOrderDeleteIn(BaseModel):
    """软删主单（仅草稿等可删状态由 service 校验）。"""

    id: int = Field(..., alias="_id", description="订单主键")

    class Config:
        allow_population_by_field_name = True


class DistributionOrderCreateIn(BaseModel):
    """订单创建阶段保存（字段顺序对齐主表 schema 销售结算/物流履约/履约块）。"""

    id: int = Field(..., alias="_id", description="订单主键")
    order_lm_user_id: Optional[int] = Field(
        None, description="订单审核直线上级用户_id(订单创建保存)",
    )
    # 销售结算
    customer_po_attachments: Optional[Any] = Field(None, description="客户采购单文件附件")
    oa_seal_no: Optional[str] = Field(None, max_length=64, description="用印OA编号")
    order_delivery_fee_payment: Optional[int] = Field(
        None, description="本次运费承担方 1=Simplus Pay 2=Customer Pay"
    )
    freight_with_vat: Optional[Decimal] = Field(None, description="含增值税运费收入")
    order_details: List[OrderDetailIn] = Field(default_factory=list, description="订单明细行")
    deleted_order_detail_ids: List[int] = Field(
        default_factory=list,
        description="兼容：软删行_id；推荐在 order_details 传 _id+is_delete=1",
    )
    # 物流履约
    ship_method: Optional[str] = Field(None, max_length=128, description="发货方式")
    expected_ship_date: Optional[date] = Field(None, description="期望出库日期")
    ship_remark: Optional[str] = Field(None, max_length=800, description="发货备注")
    # 履约 & 物流
    ship_guide_attachments: Optional[Any] = Field(None, description="发货指导文件")
    remark: Optional[Any] = Field(None, description="备注")

    @validator("customer_po_attachments", "ship_guide_attachments", pre=True)
    def _normalize_attachments(cls, v: Any) -> Any:
        return normalize_json_column(v)

    class Config:
        allow_population_by_field_name = True


class VoidIn(BaseModel):
    """订单作废（草稿/订单创建 → 已作废）。"""

    order_id: int = Field(..., gt=0, description="订单主键")
    remark: Optional[str] = Field(None, description="订单备注")


class RemarkSaveIn(BaseModel):
    """单独修改订单备注（不限主状态，已作废除外）。"""

    order_id: int = Field(..., gt=0, description="订单主键")
    remark: Optional[str] = Field(None, description="订单备注")


class OrderSubmitIn(BaseModel):
    """提交订单审核（订单创建 → 订单审核）。"""

    order_id: int = Field(..., gt=0, description="订单主键")
    chain_code: Optional[int] = Field(
        None, ge=2, le=3, description="订单审批链 2=标准 3=大额；不传则按含税订单总额USD自动分档",
    )
    order_lm_user_id: Optional[int] = Field(
        None, description="订单审核直线上级用户_id(提交订单审核)",
    )


# ── 审批（对齐合同 TransitionBody，§5.2）──────────────────────────────────────


class TransitionBody(BaseModel):
    order_id: Optional[int] = Field(None, gt=0, description="订单主键")
    remark: Optional[str] = Field(
        None, description="审批意见/备注：通过选填，驳回必填",
    )
    chain_code: Optional[int] = Field(
        None, ge=1, le=3, description="1=定价审批；order/submit 用 2 或 3"
    )
    quote_lm_user_id: Optional[int] = Field(
        None, description="报价审核直线上级用户_id(提交报价审核)",
    )
    reject_to_info: Optional[Dict[str, Any]] = Field(
        None, description="驳回目标：to_step_no, to_status, operator_role"
    )


class TransitionOut(BaseModel):
    order_id: int
    from_status: int
    to_status: int
    current_chain_code: Optional[int] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    message: str = ""


# ── 预付/回款/调整 ───────────────────────────────────────────────────────────


class PrepayConfirmIn(BaseModel):
    """确认预付款写入。"""

    order_id: int = Field(..., gt=0)
    amount_paid: Decimal = Field(..., description="实付预付款金额")
    diff_remark: Optional[str] = Field(None, max_length=800, description="差异备注")
    attachments: Optional[Any] = Field(None, description="水单附件JSON（前端自定结构）")
    system_tracking_number: Optional[str] = Field(
        None, max_length=64, description="千易单号（确认时从主单同步）"
    )

    @validator("attachments", pre=True)
    def _normalize_attachments(cls, v: Any) -> Any:
        return normalize_json_column(v)


class PaymentConfirmIn(BaseModel):
    """确认尾款/回款写入。"""

    order_id: int = Field(..., gt=0)
    amount_paid: Decimal = Field(..., description="实付尾款金额")
    payment_date: date = Field(..., description="回款日期")
    diff_remark: Optional[str] = Field(None, max_length=800, description="差异备注")
    attachments: Optional[Any] = Field(None, description="水单附件JSON（前端自定结构）")
    system_tracking_number: Optional[str] = Field(
        None, max_length=64, description="千易单号（确认时从主单同步）"
    )

    @validator("attachments", pre=True)
    def _normalize_attachments(cls, v: Any) -> Any:
        return normalize_json_column(v)


class AdjustmentLineIn(BaseModel):
    """手工调整批量保存行：无 _id=新增；有 _id=更新；有 _id 且 is_delete≠0=删除。"""

    id: Optional[int] = Field(None, alias="_id", description="调整记录_id；新增不传")
    adjust_amount: Optional[Decimal] = Field(None, gt=0, description="手工调整金额")
    fee_category_id: Optional[int] = Field(None, gt=0, description="费用项类目ID")
    document_attachments: Optional[Any] = Field(None, description="单据附件")
    remark: Optional[str] = Field(None, max_length=800, description="调整备注")
    is_delete: Optional[int] = Field(
        0, ge=0, le=1,
        description="0=新增/更新；1=删除(须带_id，删除后重算调整链)",
    )

    class Config:
        allow_population_by_field_name = True

    @root_validator(pre=True)
    def _normalize_line_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        row = dict(values)
        if row.get("_id") is not None and row.get("id") is None:
            row["id"] = row["_id"]
        if row.get("is_deleted") is not None and row.get("is_delete") is None:
            row["is_delete"] = row["is_deleted"]
        if row.get("adjust_amount") is None and row.get("amount") is not None:
            row["adjust_amount"] = row["amount"]
        if row.get("fee_category_id") is None and row.get("fee_category") is not None:
            row["fee_category_id"] = row["fee_category"]
        return row

    @validator("document_attachments", pre=True)
    def _normalize_document_attachments(cls, v: Any) -> Any:
        return normalize_json_column(v)

    @root_validator
    def _require_fields_unless_delete(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        flag = values.get("is_delete")
        if flag is not None and int(flag) != 0:
            if values.get("id") is None:
                raise ValueError("删除须传 _id")
            return values
        if values.get("adjust_amount") is None:
            raise ValueError("手工调整金额不能为空")
        if values.get("fee_category_id") is None or int(values["fee_category_id"]) <= 0:
            raise ValueError("费用项不能为空")
        remark = (values.get("remark") or "").strip()
        if not remark:
            raise ValueError("手工调整备注不能为空")
        return values


class AdjustmentBatchSaveIn(BaseModel):
    order_id: int = Field(..., gt=0, description="主单_id")
    lines: List[AdjustmentLineIn] = Field(
        default_factory=list, description="手工调整行（可多条）",
    )

    @root_validator(pre=True)
    def _coerce_lines(cls, values: Any) -> Any:
        """兼容 add 扁平入参、adjustments 键名及行内 amount 别名。"""
        if not isinstance(values, dict):
            return values
        data = dict(values)
        lines = data.get("lines")
        if lines is None and data.get("adjustments") is not None:
            lines = data.get("adjustments")
        if not lines and data.get("adjust_amount") is not None:
            data["lines"] = [{
                "adjust_amount": data.get("adjust_amount"),
                "fee_category_id": data.get("fee_category_id"),
                "document_attachments": data.get("document_attachments"),
                "remark": data.get("remark"),
            }]
            return data
        if isinstance(lines, list):
            norm: List[Any] = []
            for item in lines:
                if isinstance(item, dict):
                    row = dict(item)
                    if row.get("adjust_amount") is None and row.get("amount") is not None:
                        row["adjust_amount"] = row["amount"]
                    if row.get("fee_category_id") is None and row.get("fee_category") is not None:
                        row["fee_category_id"] = row["fee_category"]
                    norm.append(row)
                else:
                    norm.append(item)
            data["lines"] = norm
        return data

    @validator("lines")
    def _lines_required(cls, v: List[AdjustmentLineIn]) -> List[AdjustmentLineIn]:
        if not v:
            raise ValueError("手工调整行不能为空")
        return v


class AdjustmentIn(BaseModel):
    order_id: int = Field(..., gt=0)
    adjust_amount: Decimal = Field(..., gt=0, description="手工调整金额")
    fee_category_id: int = Field(..., gt=0, description="费用项类目ID")
    document_attachments: Optional[Any] = Field(None, description="单据附件")
    remark: str = Field(..., min_length=1, max_length=800, description="调整备注")

    @validator("document_attachments", pre=True)
    def _normalize_document_attachments(cls, v: Any) -> Any:
        return normalize_json_column(v)


class ReceiveDetailLineIn(BaseModel):
    """确认实收：订单明细行实收数量。"""

    id: Optional[int] = Field(None, alias="_id", description="订单明细行_id")
    sku: Optional[str] = Field(None, max_length=64, description="SKU(与_id二选一校验)")
    received_qty: Optional[int] = Field(None, ge=0, description="实收数量")
    receive_diff_remark: Optional[str] = Field(
        None, max_length=800, description="实收差异原因",
    )

    class Config:
        allow_population_by_field_name = True


class ReceiveConfirmIn(BaseModel):
    """确认实收：批量回填订单明细实收数量后流转至待回款。"""

    order_id: int = Field(..., gt=0, description="主单_id")
    lines: List[ReceiveDetailLineIn] = Field(
        ..., min_items=1, description="订单明细实收回填（可多条）",
    )


class SplitLineIn(BaseModel):
    """拆单：从主单订单明细行拆出数量。"""

    id: Optional[int] = Field(None, alias="_id", description="订单明细行_id")
    sku: Optional[str] = Field(None, max_length=64, description="SKU")
    qty: int = Field(..., gt=0, description="本次拆出数量")

    class Config:
        allow_population_by_field_name = True


class SplitIn(BaseModel):
    order_id: int = Field(..., gt=0, description="主单_id")
    lines: List[SplitLineIn] = Field(
        ..., min_items=1, description="拆单行",
    )


class DispatchIn(BaseModel):
    """下发千易。"""

    order_id: int = Field(..., gt=0, description="分销订单_id")


class DispatchOut(BaseModel):
    order_id: int
    order_sn: str
    system_tracking_number: Optional[str] = None
    online_order_number: Optional[str] = None
    to_status: int


# ── 框架报价 / 一件代发批量 ───────────────────────────────────────────────────


class FrameworkQuoteLineIn(BaseModel):
    id: Optional[int] = Field(None, alias="_id", description="行主键；新增不传")
    sku: Optional[str] = Field(None, max_length=64, description="SKU编码")
    price_with_vat: Optional[Decimal] = Field(None, description="含增值税单价")
    is_delete: Optional[int] = Field(
        0, ge=0, le=1, description="0=新增/更新；1=软删(须带_id)",
    )

    class Config:
        allow_population_by_field_name = True


class FrameworkQuoteSaveIn(BaseModel):
    offline_customer_id: int = Field(..., gt=0, description="线下客户_id")
    currency: Optional[str] = Field(None, max_length=8, description="币种")
    remark: Optional[str] = Field(None, max_length=800, description="备注")
    lines: List[FrameworkQuoteLineIn] = Field(
        default_factory=list, description="框架报价行（全量替换语义）",
    )


class FrameworkQuoteLineOut(BaseModel):
    id: int = Field(..., alias="_id")
    sku: str
    price_with_vat: Optional[Decimal] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class FrameworkQuoteOut(BaseModel):
    id: int = Field(..., alias="_id")
    offline_customer_id: int
    currency: Optional[str] = None
    remark: Optional[str] = None
    lines: List[FrameworkQuoteLineOut] = Field(default_factory=list)

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class BatchSubmitRowIn(BaseModel):
    """批量提交审核行：与 parse 返回的扁平结构一致（Excel 一行一条）。"""

    customer_po_no: str = Field(..., min_length=1, max_length=128, description="客户侧订单号")
    name: Optional[str] = Field(None, max_length=128, description="收件人姓名")
    contact_info: Optional[str] = Field(None, description="收件人联系方式")
    country: Optional[str] = Field(None, description="收件国家")
    province: Optional[str] = Field(None, description="省州")
    city: Optional[str] = Field(None, description="城市")
    address: Optional[str] = Field(None, description="详细地址")
    post_code: Optional[str] = Field(None, description="邮编")
    sku: str = Field(..., min_length=1, max_length=64, description="SKU编码")
    price_with_vat: Decimal = Field(..., description="含增值税单价")
    qty: int = Field(..., gt=0, description="销售数量")
    freight_with_vat: Decimal = Field(..., description="含增值税运费收入")
    guide_price: Optional[Decimal] = Field(None, description="指导价快照")
    red_line_price: Optional[Decimal] = Field(None, description="红线价快照")
    stock_on_hand: Optional[int] = Field(None, description="在库库存快照")
    stock_in_transit: Optional[int] = Field(None, description="在途库存快照")
    stock_planned: Optional[int] = Field(None, description="计划库存快照")


class BatchSubmitIn(BaseModel):
    """一件代发批量：前端补齐红线价/库存后提交建单并进订单审核。"""

    offline_customer_id: int = Field(..., gt=0, description="一件代发客户_id")
    sales_user_id: int = Field(..., gt=0, description="本单销售员")
    shop_id: str = Field(..., min_length=1, description="出库店铺 id")
    is_tax_free: Optional[int] = Field(0, description="是否免税")
    is_ewt: Optional[int] = Field(0, description="是否预扣税")
    vat_rate: Optional[Decimal] = Field(None, description="VAT 税率")
    ewt_rate: Optional[Decimal] = Field(None, description="预扣税比例")
    currency: Optional[str] = Field(None, max_length=8, description="币种")
    order_delivery_fee_payment: Optional[int] = Field(None, description="运费承担方")
    contract_id: Optional[int] = Field(None, description="合同_id")
    expected_ship_date: Optional[date] = Field(None, description="期望发货日")
    ship_method: Optional[str] = Field(None, description="发货方式")
    remark: Optional[str] = Field(None, description="备注")
    order_lm_user_id: Optional[int] = Field(None, description="订单审核直线上级")
    chain_code: Optional[int] = Field(None, description="审批链 2/3")
    order_details: List[BatchSubmitRowIn] = Field(
        ..., min_items=1, description="parse 返回并补齐后的明细（按顺序，字段名同 order/save）",
    )


class BatchApproveIn(BaseModel):
    """批量审核通过（驳回须单笔填 remark，走单条 reject）。"""

    order_ids: List[int] = Field(..., min_items=1, description="订单_id列表")
    remark: Optional[str] = Field(None, description="审批意见（可选）")


class BatchDispatchIn(BaseModel):
    """批量下发千易。"""

    order_ids: List[int] = Field(..., min_items=1, description="订单_id列表")


class PrepayConfirmOut(BaseModel):
    """确认预付记录（详情回显）。"""

    id: int = Field(..., alias="_id")
    order_id: int
    amount_due: Optional[Decimal] = None
    amount_paid: Optional[Decimal] = None
    payment_date: Optional[date] = None
    diff_remark: Optional[str] = None
    attachments: Optional[Any] = None
    system_tracking_number: Optional[str] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class PaymentConfirmOut(BaseModel):
    """确认回款记录（详情回显）。"""

    id: int = Field(..., alias="_id")
    order_id: int
    amount_due: Optional[Decimal] = None
    amount_paid: Optional[Decimal] = None
    payment_date: Optional[date] = None
    diff_remark: Optional[str] = None
    attachments: Optional[Any] = None
    system_tracking_number: Optional[str] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


_CONFIRM_RECORD_LOG_EXCLUDE = frozenset({"id", "order_id"})


def serialize_confirm_record_log_snapshot(
    row: Any,
    out_model: Type[_TConfirmOut] = PrepayConfirmOut,
) -> Dict[str, Any]:
    """预付/回款 ORM 行 → 操作日志快照（字段与 *ConfirmOut 一致，不写死列名）。"""
    if row is None:
        return {}
    return out_model.from_orm(row).dict(
        by_alias=True,
        exclude=_CONFIRM_RECORD_LOG_EXCLUDE,
    )


def confirm_body_log_snapshot(body: BaseModel) -> Dict[str, Any]:
    """预付/回款入参 → 操作日志快照；仅含请求体实际传入字段（避免未传字段写成 None 产生伪 diff）。"""
    return body.dict(by_alias=True, exclude={"order_id"}, exclude_unset=True)


def receive_confirm_body_log_snapshot(
    body: ReceiveConfirmIn,
    order_lines_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """确认实收入参 → 操作日志快照（含 _id、sku + 实收数量）。"""
    by_id = order_lines_by_id or {}
    by_sku = {
        (r.get("sku") or "").strip(): r
        for r in by_id.values()
        if (r.get("sku") or "").strip()
    }
    lines: List[Dict[str, Any]] = []
    for ln in body.lines:
        row = ln.dict(by_alias=True)
        lid = row.get("_id")
        if lid is not None:
            try:
                ex = by_id.get(int(lid))
            except (TypeError, ValueError):
                ex = None
            if ex:
                row.setdefault("sku", ex.get("sku"))
        sku = (row.get("sku") or "").strip()
        if sku and sku in by_sku:
            ex = by_sku[sku]
            row.setdefault("_id", ex.get("_id"))
            row.setdefault("sku", sku)
        lines.append(row)
    return {"lines": lines}


class AdjustmentOut(BaseModel):
    """手工调整行（详情回显）。"""

    id: int = Field(..., alias="_id")
    seq: int = 0
    adjust_amount: Optional[Decimal] = None
    fee_category_id: Optional[int] = None
    document_attachments: Optional[Any] = None
    remark: Optional[str] = None
    adjusted_balance_after: Optional[Decimal] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True

    @validator("document_attachments", pre=True)
    def _normalize_document_attachments(cls, v: Any) -> Any:
        return normalize_json_column(v)


class ReceiveConfirmLineOut(BaseModel):
    id: int = Field(..., alias="_id")
    sku: str = ""
    qty: int = 0
    received_qty: Optional[int] = None
    receive_diff_remark: Optional[str] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class ReceiveConfirmOut(BaseModel):
    """确认实收回显（订单明细实收数量 + 行级差异原因）。"""

    lines: List[ReceiveConfirmLineOut] = Field(default_factory=list)


class SplitChildOrderOut(BaseModel):
    """拆单生成的子单（详情列表回显）。"""

    id: int = Field(..., alias="_id")
    order_sn: str = ""
    status: int = 0
    status_str: str = ""
    parent_order_id: Optional[int] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


# ── 读出 ─────────────────────────────────────────────────────────────────────


class DistributionOrderOut(DistributionOrderSnapshotOut):
    id: int = Field(..., alias="_id")
    order_sn: str
    status: int
    void_from_status: Optional[int] = None
    parent_order_id: Optional[int] = None
    offline_customer_id: int
    contract_id: Optional[int] = None
    customer_code: str = ""
    customer_short_name: str = ""
    customer_country: Optional[str] = None
    customer_type_first: Optional[str] = None
    customer_type_second: Optional[str] = None
    remark: Optional[str] = None
    shop_id: Optional[str] = None
    sales_user_id: Optional[int] = None
    is_tax_free: int = 0
    is_ewt: int = 0
    vat_rate: Optional[Decimal] = None
    ewt_rate: Optional[Decimal] = None
    currency: Optional[str] = None
    is_prepayment: int = 0
    prepayment_ratio: Optional[Decimal] = None
    settlement_method: Optional[int] = None
    cooperation_method: Optional[int] = None
    current_chain_code: Optional[int] = None
    current_step: Optional[int] = None
    quote_lm_user_id: Optional[int] = None
    order_lm_user_id: Optional[int] = None
    freight_with_vat: Optional[Decimal] = None
    freight_without_vat: Optional[Decimal] = None
    goods_amount_with_vat: Optional[Decimal] = None
    goods_amount_without_vat: Optional[Decimal] = None
    order_amount_with_vat: Optional[Decimal] = None
    order_amount_without_vat: Optional[Decimal] = None
    vat_amount_total: Optional[Decimal] = None
    prepay_amount: Optional[Decimal] = None
    ewt_amount: Optional[Decimal] = None
    balance_amount: Optional[Decimal] = None
    adjusted_balance_amount: Optional[Decimal] = None
    tags_bitmask: Optional[int] = None
    tags: List[int] = Field(default_factory=list, description="标签 bit 值列表")
    tags_str: List[str] = Field(default_factory=list, description="标签中文名")
    system_tracking_number: Optional[str] = None
    waybill_no: Optional[str] = None
    customer_po_attachments: Optional[Any] = None
    ship_method: Optional[str] = None
    order_delivery_fee_payment: Optional[int] = None
    expected_payment_date: Optional[date] = None
    actual_payment_date: Optional[date] = None
    warehouse: Optional[str] = None
    order_status: Optional[str] = None
    logistic_status: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    oa_seal_no: Optional[str] = None
    ship_remark: Optional[str] = None
    expected_ship_date: Optional[date] = None
    actual_ship_date: Optional[date] = None
    ship_guide_attachments: Optional[Any] = None
    create_by: Optional[int] = None
    submit_by: Optional[int] = None
    batch_id: Optional[str] = None
    customer_po_no: Optional[str] = None
    create_source: int = 0
    create_source_str: str = ""
    cooperation_method_str: str = ""


    class Config:
        orm_mode = True
        allow_population_by_field_name = True

        json_encoders = {
            datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S") if v else None
        }


class DistributionOrderDetailOut(DistributionOrderOut):
    """详情：含报价/订单明细及履约模块回显，由 service 组装。"""

    quote_details: List[QuoteDetailOut] = Field(default_factory=list)
    order_details: List[OrderDetailOut] = Field(default_factory=list)
    prepay_confirm: Optional[PrepayConfirmOut] = None
    payment_confirm: Optional[PaymentConfirmOut] = None
    adjustments: List[AdjustmentOut] = Field(default_factory=list)
    receive_confirm: Optional[ReceiveConfirmOut] = None
    split_orders: List[SplitChildOrderOut] = Field(default_factory=list)
    quote_approval_flow: Optional[Dict[str, Any]] = None
    order_approval_flow: Optional[Dict[str, Any]] = None
