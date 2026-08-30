# 分销下单（distribution_order）

从 yy 主项目拆出的**分销订单生命周期**需求（列表、审批、下发千易、拆单、回款等）。

## 文档

| 文件 | 说明 |
|------|------|
| [API_FRONTEND.md](./API_FRONTEND.md) | **前端接口说明**（路径、入参出参、状态/标签枚举） |
| [需求文档.md](./需求文档.md) | 产品需求（PRD） |
| [design.md](./design.md) | **方案设计草案**（状态机、表/API 草案、待确认问题） |
| [workflow_engine.md](./workflow_engine.md) | **审批流引擎说明**（状态机、同人跳过、Bundle 组装） |
| [schema.sql](./schema.sql) | **全量 DDL**（§4.1–§4.7；单号暂随机，日序列表后续加） |
| [../offline_customer/models.py](../offline_customer/models.py) | 线下客户/合同 ORM（分销单客户信息来源，见 design §4.1.4） |
| [models.py](./models.py) / [schemas.py](./schemas.py) | ORM 与 Pydantic v1 读写模型 |
| [distribution_order_workflow_engine.py](./distribution_order_workflow_engine.py) | 审批流引擎 |

## 开发顺序

1. ~~评审 §8 待确认问题~~ → **Q2/Q5/Q6/Q7/Q9 已确认**，其余见 [design.md §8.2 暂定](./design.md#82-暂定沿用草案倾向实现时可按此开发)  
2. 执行 [schema.sql](./schema.sql) 建表（`internal_app`）  
3. DDL + `models.py` + `schemas.py` 已就绪；`distribution_order_workflow_engine.py` 已对齐主表字段  
4. 下一步：`distribution_order_service.py` / `views/` / `urls.py`  

## 标签位图

- 重算逻辑：`distribution_order_tags.py`（保存/审批/履约后自动 `refresh_order_tags`）
- 历史数据批量刷：`scripts/refresh_distribution_order_tags.py`（合入主仓后 `python -m apps.system.distribution_order.scripts.refresh_distribution_order_tags --all`）
- 列表筛选项 `tags`：传 bit 值数组如 `[1,8]`，多选 **OR**；回显字段 `tags` / `tags_str` / `tags_bitmask`
- 表头筛选项可配置 `constants.TAG_FILTER_OPTIONS`

## 技术栈

Python 3.8 · FastAPI · Pydantic v1 · SQLAlchemy 2.0 (async) · MySQL 8.0（约定见 `.agent/rules/yy-global.md`）。

## 主项目参考

- 仓库 / 分支：（待填）
- 相关模块：线下客户/合同、千易、WS 订单履约、首页待办、OSS（待填链接）
- **审批流**：引擎 [`contract_workflow_engine.py`](../offline_customer/contract_workflow_engine.py)（§5.1）、接口 [`sys_offline_contract_approve.py`](../offline_customer/view/sys_offline_contract_approve.py)（§5.2）；本任务 [`distribution_order_workflow_engine.py`](./distribution_order_workflow_engine.py)
- 路由挂载：（待填，见 design.md Q21）

## 验收标准

以 [design.md §7](./design.md#7-验收标准草案确认后写入-readme--md) 为准；定稿后同步到 `.agent/rules/tasks/distribution_order.md`。
