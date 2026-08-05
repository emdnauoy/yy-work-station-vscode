table_keys =  [
  {
    "name": "操作",
    "key": "button_list",
    "showkey": "button_list",
    "label_type": "value",
    "search_list": [
      {
        "label": "详情",
        "value": "select",
        "loading": 1
      },
      {
        "label": "编辑",
        "value": "edit",
        "loading": 1
      },
      {
        "label": "提交审核",
        "value": "submit",
        "loading": 1
      },
      {
        "label": "审核",
        "value": "review",
        "loading": 1
      },
      {
        "label": "撤回审核",
        "value": "withdraw",
        "loading": 1
      },
      {
        "label": "终止合同",
        "value": "terminate",
        "loading": 1
      },
      {
        "label": "重新发起",
        "value": "resubmit",
        "loading": 1
      },
            {
        "label": "日志",
        "value": "log",
        "loading": 1
      }
    ]
  },
  {
    "key": "status",
    "title": "合同状态",
    "options": [
      {
        "label": "待提交",
        "value": 10,
        "textColor": "#3983E2",
        "color": "#EBF1FD"
      },
      {
        "label": "审核中",
        "value": 20,
        "textColor": "#FA8C16",
        "color": "#FFF6E7"
      },
      {
        "label": "待生效",
        "value": 30,
        "textColor": "#FA8C16",
        "color": "#FFF6E7"
      },
      {
        "label": "生效中",
        "value": 40,
        "textColor": "#0AB24E",
        "color": "#EAF8EF"
      },
      {
        "label": "已失效",
        "value": 50,
        "textColor": "#FF3331",
        "color": "#FFEBEC"
      }
    ]
  },
  {
    "key": "terminate_type",
    "title": "终止类型",
    "options": [
      {
        "label": "自然到期",
        "value": 1
      },
      {
        "label": "人工终止",
        "value": 2
      },
      {
        "label": "被新合同顶替",
        "value": 3
      }
    ]
  },
  {
    "key": "contract_method",
    "title": "合同方式",
    "options": [
      {
        "label": "寄售",
        "value": 1
      },
      {
        "label": "非寄售",
        "value": 2
      }
    ]
  },
  {
    "key": "is_prepayment",
    "title": "是否预付",
    "options": [
      {
        "label": "无预付",
        "value": 0
      },
      {
        "label": "预付比例",
        "value": 1
      }
    ]
  },
  {
    "key": "mt_has_delivery_target",
    "title": "是否有送货率目标",
    "options": [
      {
        "label": "无规定",
        "value": 0
      },
      {
        "label": "有规定",
        "value": 1
      }
    ]
  },
  {
    "key": "mt_has_penalty",
    "title": "是否有违约金条款",
    "options": [
      {
        "label": "无",
        "value": 0
      },
      {
        "label": "有-金额",
        "value": 1
      }
    ]
  },
  {
    "key": "mt_delivery_mode",
    "title": "交货模式",
    "options": [
      {
        "label": "一次性送齐",
        "value": 1
      },
      {
        "label": "允许多批",
        "value": 2
      }
    ]
  },
  {
    "key": "settlement_method",
    "title": "结算方式",
    "options": [
      {
        "label": "带款提货",
        "value": 1
      },
      {
        "label": "账期",
        "value": 2
      }
    ]
  },
  {
    "key": "payment_method",
    "title": "支付方式",
    "options": [
      {
        "label": "银行转账",
        "value": 1
      },
      {
        "label": "支票",
        "value": 2
      },
      {
        "label": "现金",
        "value": 3
      },
      {
        "label": "无需支付",
        "value": 4
      }
    ]
  },
  {
    "key": "delivery_method",
    "title": "配送方式",
    "options": [
      {
        "label": "在指定地点交付",
        "value": 1
      },
      {
        "label": "在配送中心交付",
        "value": 2
      },
      {
        "label": "客户自提",
        "value": 3
      }
    ]
  },
  {
    "key": "return_policy",
    "title": "退货政策",
    "options": [
      {
        "label": "可全部退货",
        "value": 1
      },
      {
        "label": "不接受退货",
        "value": 2
      },
      {
        "label": "接受退货",
        "value": 3
      }
    ]
  },
  {
    "key": "reword_policy",
    "title": "奖励政策",
    "options": [
      {
        "label": "季度采购激励",
        "value": 1
      },
      {
        "label": "年度采购激励",
        "value": 2
      },
      {
        "label": "其他",
        "value": 3
      }
    ]
  },
  {
    "key": "sample_policy",
    "title": "样品政策",
    "options": [
      {
        "label": "免费供样",
        "value": 1
      },
      {
        "label": "折扣供样",
        "value": 2
      }
    ]
  },
  {
    "key": "carrier",
    "title": "默认物流商",
    "options": [
      {
        "label": "Lalamove",
        "value": "Lalamove/ 3rd party big truck"
      },
      {
        "label": "第三方物流",
        "value": "Lalamove/ 3rd party box truck"
      },
      {
        "label": "电商快递",
        "value": "Flash Express"
      }
    ]
  },
  {
    "key": "effective_node",
    "title": "生效节点",
    "options": [
      {
        "label": "客户提货",
        "value": 1
      },
      {
        "label": "发票日期",
        "value": 2
      },
      {
        "label": "固定付款日",
        "value": 3
      },
      {
        "label": "分批结算",
        "value": 4
      }
    ]
  },
  {
    "key": "mt_delivery_mode",
    "title": "交付方式",
    "options": [
      {
        "label": "一次性送齐",
        "value": 1
      },
      {
        "label": "允许多批",
        "value": 2
      }
    ]
  },
  {
    "key": "delivery_fee_payment",
    "title": "运费承担方",
    "options": [
      {
        "label": "曜曜支付",
        "value": 1
      },
      {
        "label": "客户自付",
        "value": 2
      }
    ]
  },
  {
    "key": "calc_method",
    "title": "计算方式",
    "options": [
      {
        "label": "按比例",
        "value": 1
      },
      {
        "label": "固定金额",
        "value": 2
      }
    ]
  },
  {
    "key": "calc_base",
    "title": "计算基数",
    "options": [
      {
        "label": "sell-in",
        "value": 1
      },
      {
        "label": "sell-out",
        "value": 2
      }
    ]
  },
  {
    "key": "fee_category_id",
    "title": "无条件返利费用",
    "options": [
          {
            "label": "销售费用",
            "children": [
              {
                "label": "服务费",
                "children": [
                  {
                    "label": "无条件返利-大仓物流费",
                    "value": 91
                  },
                  {
                    "label": "无条件返利-市场费",
                    "value": 94
                  },
                  {
                    "label": "不退货折扣",
                    "value": 92
                  },
                  {
                    "label": "无条件返利-系统使用费",
                    "value": 93
                  }
                ]
              },
              {
                "label": "平台佣金",
                "children": [
                  {
                    "label": "无条件返利-后台毛利",
                    "value": 95
                  }
                ]
              }
            ]
          },
          {
            "label": "营销费用",
            "children": [
              {
                "label": "站内流量投放",
                "children": [
                  {
                    "label": "海报费",
                    "value": 100
                  },
                  {
                    "label": "招待费",
                    "value": 108
                  },
                  {
                    "label": "陈列费",
                    "value": 99
                  },
                  {
                    "label": "营销支持",
                    "value": 96
                  },
                  {
                    "label": "新品费",
                    "value": 98
                  },
                  {
                    "label": "新店费",
                    "value": 102
                  },
                  {
                    "label": "线上平台使用费/系统使用费",
                    "value": 97
                  },
                  {
                    "label": "促销员费用",
                    "value": 104
                  },
                  {
                    "label": "物料制作费",
                    "value": 106
                  },
                  {
                    "label": "促销费",
                    "value": 107
                  },
                  {
                    "label": "样品费",
                    "value": 105
                  },
                  {
                    "label": "特殊月份活动支持",
                    "value": 101
                  },
                  {
                    "label": "门店装修费",
                    "value": 103
                  }
                ]
              },
              {
                "label": "达人佣金",
                "children": [
                  {
                    "label": "PC工资",
                    "value": 109
                  }
                ]
              }
            ]
          }
        ]
  },
    {
    "key": "log_display",
    "title": "日志回显",
    "options": [
  { "label": "合同编号", "value": "contract_no" },
  { "label": "签订日期", "value": "sign_date" },
  { "label": "合同生效起", "value": "effective_start" },
  { "label": "合同生效止", "value": "effective_end" },
  { "label": "客户ID", "value": "customer_id" },
  { "label": "客户编码", "value": "customer_code" },
  { "label": "国家", "value": "country" },
  { "label": "签订负责人", "value": "owner_staff_id" },
  { "label": "状态", "value": "status" },
  { "label": "当前审核环节", "value": "current_step" },
  { "label": "审核轮次", "value": "review_round" },
  { "label": "终止类型", "value": "terminate_type" },
  { "label": "合同方式", "value": "contract_method" },
  { "label": "合同点数", "value": "contract_points" },
  { "label": "结算方式", "value": "settlement_method" },
  { "label": "账期天数", "value": "settlement_days" },
  { "label": "开账周期", "value": "billing_period" },
  { "label": "生效节点", "value": "effective_node" },  
  { "label": "出账日规则", "value": "payment_date" },
  { "label": "出账日类型", "value": "payment_date_type" },
  { "label": "付款方式", "value": "payment_method" },
  { "label": "是否预付", "value": "is_prepayment" },
  { "label": "预付比例", "value": "prepayment_ratio" },
  { "label": "样品政策", "value": "sample_policy" },
  { "label": "样品折扣", "value": "sample_discount" },
  { "label": "银行账户材料", "value": "bank_account_confirmation" },
  { "label": "前台毛利", "value": "front_margin" },
  { "label": "配送方式", "value": "delivery_method" },
  { "label": "物流商", "value": "carrier" },
  { "label": "运费承担方", "value": "delivery_fee_payment" },
  { "label": "配送备注", "value": "delivery_remark" },
  { "label": "是否有送货率目标", "value": "mt_has_delivery_target" },
  { "label": "目标送货率", "value": "mt_delivery_target_ratio" },
  { "label": "是否有违约金", "value": "mt_has_penalty" },
  { "label": "违约金金额", "value": "mt_penalty_fee" },
  { "label": "交付方式", "value": "mt_delivery_mode" },
  { "label": "起送/最小订单金额", "value": "mt_min_order_amount" },
  { "label": "退货政策", "value": "return_policy" },
  { "label": "可退货比例", "value": "return_ratio" },
  { "label": "是否线上授权渠道", "value": "is_online_channel" },
  { "label": "线上授权渠道文本", "value": "online_channel_text" },
  { "label": "是否线下授权渠道", "value": "is_offline_channel" },
  { "label": "线下授权渠道文本", "value": "offline_channel_text" },
  { "label": "奖励政策", "value": "reword_policy" },
  { "label": "续签/旧合同主键", "value": "previous_contract_id" },
  { "label": "关联联系人", "value": "contact_id" },
  { "label": "补充协议", "value": "supplementary_agreement" },
  { "label": "附件", "value": "attachments" },
  { "label": "关联地址", "value": "address_id" },
  { "label": "费用类目", "value": "fee_category_id" },
  { "label": "费用类目", "value": "fee_category_id_str" },
  { "label": "计算方式", "value": "calc_method" },
  { "label": "计算方式", "value": "calc_method_str" },
  { "label": "计算基数", "value": "calc_base" },
  { "label": "对应值", "value": "value" },
  { "label": "计算基数", "value": "calc_base_str" },
  { "label": "有条件返利", "value": "cond_rebate_steps" },
  { "label": "无条件返利", "value": "uncond_rebates" },
  { "label": "审批数据", "value": "approval_logs" },
  { "label": "原状态", "value": "from_status_str" },
  { "label": "新状态", "value": "to_status_str" },
  { "label": "操作动作", "value": "action_code_str" },
  { "label": "操作人角色", "value": "operator_role_str" },
  { "label": "操作人姓名", "value": "operator_name" },
  { "label": "币种", "value": "currency" },
  { "label": "步骤", "value": "step_no" },
  { "label": "备注", "value": "remark" },
  { "label": "年度采购金额", "value": "annual_purchase_amount" },
  { "label": "返利比例", "value": "rebate_ratio" }
]
  },
  {
    "key": "validation_fields",
    "title": "校验字段",
    "options": [
  { "label": "签订日期", "value": "sign_date" },
  { "label": "合同生效起", "value": "effective_start" },
  { "label": "合同生效止", "value": "effective_end" },
  { "label": "签订负责人", "value": "owner_staff_id" },
  { "label": "地址", "value": "address_id" },
  { "label": "合同联系人ID", "value": "contact_id" },
  { "label": "合同方式", "value": "contract_method" },
  { "label": "结算方式", "value": "settlement_method" },
  { "label": "付款方式", "value": "payment_method" },
  { "label": "是否预付", "value": "is_prepayment" },
  { "label": "样品政策", "value": "sample_policy" },
  { "label": "客户银行账户信息确认函", "value": "bank_account_confirmation" },
  { "label": "配送方式", "value": "delivery_method" },
  { "label": "物流商", "value": "carrier" },
  { "label": "运费承担方", "value": "delivery_fee_payment" },
  { "label": "退货政策", "value": "return_policy" }
]
  }
]

# ── Excel 导出后处理：枚举转文案 + 列名 log_display 映射 ─────────────────────

import argparse
import datetime
import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = os.path.join(_SCRIPT_DIR, "合同信息导出.xlsx")
DEFAULT_OUTPUT = os.path.join(_SCRIPT_DIR, "合同信息导出_已处理.xlsx")
DEFAULT_UNCOND_INPUT = os.path.join(_SCRIPT_DIR, "无条件返利.xlsx")
DEFAULT_COND_INPUT = os.path.join(_SCRIPT_DIR, "有条件返利.xlsx")
DEFAULT_APPROVAL_INPUT = os.path.join(_SCRIPT_DIR, "合同审批数据.xlsx")
_UNCOND_REBATE_ITEM_FIELDS = [
    "fee_category_id", "calc_method", "calc_base", "value", "currency", "remark",
]
_COND_REBATE_ITEM_FIELDS = [
    "step_no", "annual_purchase_amount", "rebate_ratio", "currency",
]
_APPROVAL_ITEM_FIELDS = [
    "from_status_str", "to_status_str", "action_code_str", "operator_role_str", "operator_name",
]
_APPROVAL_COL_RENAME = {
    "原状态": "from_status_str",
    "新状态": "to_status_str",
    "操作动作": "action_code_str",
    "操作人角色": "operator_role_str",
    "操作人姓名": "operator_name",
}
_SKIP_VALUE_MAP_KEYS = frozenset({"log_display", "validation_fields", "button_list"})
_DATE_FMT = "%Y-%m-%d"
_DATE_FIELD_KEYS = frozenset({
    "sign_date", "effective_start", "effective_end",
    "create_time", "update_time", "payment_date",
})


def _flatten_option_maps(options: Optional[List[Dict[str, Any]]], out: Optional[Dict[Any, Any]] = None) -> Dict[Any, Any]:
    """options / search_list → {value: label}，含 str 形态便于 Excel 匹配。"""
    if out is None:
        out = {}
    for item in options or []:
        if not isinstance(item, dict):
            continue
        val = item.get("value")
        lab = item.get("label")
        if val is not None and lab is not None:
            out[val] = lab
            out[str(val)] = lab
        children = item.get("children")
        if children:
            _flatten_option_maps(children, out)
    return out


def build_value_maps(keys_config: List[Dict[str, Any]]) -> Dict[str, Dict[Any, Any]]:
    """按 table_keys 的 key 构建列值 → 展示文案映射。"""
    maps = {}
    for item in keys_config:
        key = item.get("key")
        if not key or key in _SKIP_VALUE_MAP_KEYS:
            continue
        opts = item.get("search_list") or item.get("options") or []
        maps[key] = _flatten_option_maps(opts)
    return maps


def build_column_label_map(keys_config: List[Dict[str, Any]]) -> Dict[str, str]:
    """log_display.options：字段 key → 中文列名。"""
    for item in keys_config:
        if item.get("key") != "log_display":
            continue
        labels = {}
        for opt in item.get("options") or []:
            val = opt.get("value")
            lab = (opt.get("label") or "").strip()
            if val is not None and lab:
                labels[str(val)] = lab
        return labels
    return {}


def _map_cell_value(val: Any, value_map: Dict[Any, Any]) -> Any:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return val
    if isinstance(val, str) and not val.strip():
        return val
    if val in value_map:
        return value_map[val]
    text = str(val).strip()
    if text in value_map:
        return value_map[text]
    try:
        iv = int(float(val))
        if iv in value_map:
            return value_map[iv]
        if str(iv) in value_map:
            return value_map[str(iv)]
    except (TypeError, ValueError, OverflowError):
        pass
    return val


def _rename_columns(columns: List[Any], label_for_col: Dict[Any, str]) -> Dict[Any, str]:
    """列名改为 log_display.label；与已有列名或重复 label 冲突时加 (field_key)。"""
    rename = {}
    existing = {str(c) for c in columns}
    used_new = set()
    for col in columns:
        if col not in label_for_col:
            continue
        col_key = str(col)
        lab = label_for_col[col]
        new_name = lab
        if new_name in used_new or (new_name in existing and col_key != new_name):
            new_name = "%s(%s)" % (lab, col_key)
        used_new.add(new_name)
        rename[col] = new_name
    return rename


def _format_date_value(val: Any) -> Any:
    """统一为 年-月-日（YYYY-MM-DD）。"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return val
    if isinstance(val, pd.Timestamp):
        return val.strftime(_DATE_FMT)
    if isinstance(val, datetime.datetime):
        return val.strftime(_DATE_FMT)
    if isinstance(val, datetime.date):
        return val.strftime(_DATE_FMT)
    text = str(val).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return val
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return val
    return parsed.strftime(_DATE_FMT)


def _date_columns(df: pd.DataFrame) -> List[Any]:
    cols = []
    for col in df.columns:
        col_key = str(col)
        if col_key in _DATE_FIELD_KEYS:
            cols.append(col)
            continue
        if col_key.endswith("_date") or col_key.endswith("_time"):
            cols.append(col)
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            cols.append(col)
    return cols


def _format_date_columns(df: pd.DataFrame, cols: Optional[List[Any]] = None) -> None:
    for col in cols or _date_columns(df):
        if col in df.columns:
            df[col] = df[col].apply(_format_date_value)


def _normalize_contract_no(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _apply_value_maps(df: pd.DataFrame, value_maps: Dict[str, Dict[Any, Any]]) -> None:
    for col in df.columns:
        col_key = str(col)
        if col_key in value_maps:
            df[col] = df[col].apply(lambda v, m=value_maps[col_key]: _map_cell_value(v, m))


def _row_to_rebate_item(
    row: pd.Series,
    fields: List[str],
    col_labels: Dict[str, str],
) -> Dict[str, Any]:
    item = {}
    for field in fields:
        if field not in row.index:
            continue
        val = row[field]
        if val is None or (isinstance(val, float) and pd.isna(val)):
            val = None
        elif field in _DATE_FIELD_KEYS or field.endswith("_date") or field.endswith("_time"):
            val = _format_date_value(val)
        label = col_labels.get(field, field)
        item[label] = val
    return item


def _aggregate_rebate_by_contract(
    df: pd.DataFrame,
    fields: List[str],
    value_maps: Dict[str, Dict[Any, Any]],
    col_labels: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    if df.empty or "contract_no" not in df.columns:
        return {}
    _apply_value_maps(df, value_maps)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for _, row in df.iterrows():
        cn = _normalize_contract_no(row.get("contract_no"))
        if not cn:
            continue
        item = _row_to_rebate_item(row, fields, col_labels)
        if not any(v is not None for v in item.values()):
            continue
        grouped.setdefault(cn, []).append(item)
    return grouped


def _load_rebate_aggregate(
    path: Optional[str],
    fields: List[str],
    value_maps: Dict[str, Dict[Any, Any]],
    col_labels: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    if not path or not os.path.isfile(path):
        return {}
    rebate_df = pd.read_excel(path)
    return _aggregate_rebate_by_contract(rebate_df, fields, value_maps, col_labels)


def _load_approval_aggregate(
    path: Optional[str],
    col_labels: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    if not path or not os.path.isfile(path):
        return {}
    approval_df = pd.read_excel(path)
    approval_df = approval_df.rename(
        columns={k: v for k, v in _APPROVAL_COL_RENAME.items() if k in approval_df.columns},
    )
    return _aggregate_rebate_by_contract(approval_df, _APPROVAL_ITEM_FIELDS, {}, col_labels)


def _attach_rebate_columns(
    df: pd.DataFrame,
    uncond_map: Dict[str, List[Dict[str, Any]]],
    cond_map: Dict[str, List[Dict[str, Any]]],
    approval_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> None:
    if "contract_no" not in df.columns:
        return

    def _to_json(cn: Any, rebate_map: Dict[str, List[Dict[str, Any]]]) -> str:
        items = rebate_map.get(_normalize_contract_no(cn), [])
        return json.dumps(items, ensure_ascii=False)

    df["uncond_rebates"] = df["contract_no"].apply(lambda x: _to_json(x, uncond_map))
    df["cond_rebate_steps"] = df["contract_no"].apply(lambda x: _to_json(x, cond_map))
    if approval_map is not None:
        df["approval_logs"] = df["contract_no"].apply(lambda x: _to_json(x, approval_map))


def process_contract_export_excel(
    input_path: str,
    output_path: str,
    keys_config: Optional[List[Dict[str, Any]]] = None,
    uncond_input_path: Optional[str] = DEFAULT_UNCOND_INPUT,
    cond_input_path: Optional[str] = DEFAULT_COND_INPUT,
    approval_input_path: Optional[str] = DEFAULT_APPROVAL_INPUT,
) -> str:
    keys_config = keys_config if keys_config is not None else table_keys
    df = pd.read_excel(input_path)
    value_maps = build_value_maps(keys_config)
    col_labels = build_column_label_map(keys_config)
    date_cols = _date_columns(df)

    _apply_value_maps(df, value_maps)
    _format_date_columns(df, date_cols)

    uncond_map = _load_rebate_aggregate(
        uncond_input_path, _UNCOND_REBATE_ITEM_FIELDS, value_maps, col_labels,
    )
    cond_map = _load_rebate_aggregate(
        cond_input_path, _COND_REBATE_ITEM_FIELDS, value_maps, col_labels,
    )
    approval_map = _load_approval_aggregate(approval_input_path, col_labels)
    _attach_rebate_columns(df, uncond_map, cond_map, approval_map)

    label_for_col = {}
    for col in df.columns:
        col_key = str(col)
        if col_key in col_labels:
            label_for_col[col] = col_labels[col_key]
    df = df.rename(columns=_rename_columns(list(df.columns), label_for_col))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    df.to_excel(output_path, index=False)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="合同导出 Excel：枚举转文案 + log_display 列名 + 返利聚合")
    parser.add_argument("-i", "--input", default=DEFAULT_INPUT, help="主表 xlsx")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="输出 xlsx")
    parser.add_argument("--uncond-input", default=DEFAULT_UNCOND_INPUT, help="无条件返利 xlsx")
    parser.add_argument("--cond-input", default=DEFAULT_COND_INPUT, help="有条件返利 xlsx")
    parser.add_argument("--approval-input", default=DEFAULT_APPROVAL_INPUT, help="合同审批数据 xlsx")
    args = parser.parse_args()
    out = process_contract_export_excel(
        args.input, args.output,
        uncond_input_path=args.uncond_input,
        cond_input_path=args.cond_input,
        approval_input_path=args.approval_input,
    )
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()