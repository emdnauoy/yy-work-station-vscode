---
description: "线下客户合同：状态机 apply_transition、审批链解析、生效/失效流转、返利台阶校验。"
alwaysApply: false
globs: tasks/offline_customer/view/sys_offline_contract_*.py,tasks/offline_customer/contract_service.py,tasks/offline_customer/contract_workflow_engine.py
---

# offline_customer — 合同审批流

本模块通用约束（双 schema、软删、已知偏差、公共函数）见 `offline_customer.md`。

| 文件 | 行数 | 职责 |
|------|-----:|------|
| `contract_workflow_engine.py` | 998 | 状态机，唯一入口 `apply_transition` |
| `view/sys_offline_contract_view.py` | 892 | 合同列表 / 详情 / 增删改 |
| `view/sys_offline_contract_approve.py` | 466 | 审批动作与审批配置 |
| `contract_service.py` | 505 | 合同增删改业务，**内部自行 commit** |

## 状态码

| 字段 | 取值 |
|------|------|
| `OfflineContract.status` | `10` 草稿 `20` 审核中 `30` 待生效 `40` 已生效 `50` 已失效 |
| `OfflineContract.terminate_type` | `1` 自然到期 `2` 人工终止 `3` 被新合同顶替 |

## 状态机

流转唯一入口 `apply_transition`；合法流转见 `_TRANSITIONS`，动作码 `ACTION_SUBMIT=1` … `ACTION_RESUBMIT=7`、`ACtion_SYSTEM=8`（注意这个拼写就是现状）。**禁**在 view 或 service 里直接改 `contract.status`。

- 审批链读 `ContractApprovalConfig`（`is_active=True`，按 `step_no` 排序）；审批人按客户国家 + `user_business_role_permission`（`config_key='customer_nation'`）匹配
- 末步通过 → `STATUS_PENDING`，再由 `_customer_status_transition` 按 `effective_start/end` 落待生效 / 已生效 / 已失效
- 新合同激活会改写客户 `current_contract_id`、`had_ever_effect`，并把上一份合同置 `STATUS_EXPIRED`
- 每次流转写 `OfflineContractStatusLog`；前端按钮取 `STATUS_BUTTON_LIST`

## 编辑约束

- **仅草稿态可改可删**（非草稿态 `update_offline_contract` 会 `raise HTTPException`，由 view catch）
- 更新时传了 `uncond_rebates` / `cond_rebate_steps` 是**全量覆盖**（先 delete 再 insert）
- 有条件返利台阶 `step_no` 越大 `annual_purchase_amount` 须严格递增
- 合同号由 `contract_service.generate_contract_no` 生成；`change_diff.py` 的默认 `ignore_keys` 比全局多 `contract_no`
