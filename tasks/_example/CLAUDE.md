# 子任务：_example（模板，勿当真实需求）

> 复制本文件与 `tasks/_example/` 目录后，把 `_example` 全部替换为你的任务名。

## 背景

（从 yy 主项目拆出的原因、相关模块、Issue/文档链接。）

## 允许修改的范围

- **仅** `tasks/_example/` 内文件
- **禁止** 修改其他 `tasks/*` 目录及无关全局配置

## 技术约定

技术栈与代码风格见根目录 `CLAUDE.md`，以下仅列模板特有说明：

- 任务目录名：**snake_case**（如 `fix_login`，不用 `fix-login`）
- 依赖：以本目录 `requirements.txt` 为准；新增包须兼容 Python 3.8

## 代码模式参考

实际代码结构、分层写法、异常处理、翻译调用等，参考 `tasks/distribution_order/`：

| 参考点 | 文件 |
|--------|------|
| service 层写法 | `distribution_order_service.py` |
| view 层骨架（try/except/commit/rollback/翻译/日志） | `views/distribution_order.py` |
| line_service 明细 CRUD 模式 | `distribution_order_line_service.py` |
| schemas 定义（XxxIn/XxxOut/alias） | `schemas.py` |
| models 定义（主键/审计/软删） | `models.py` |
| urls 路由绑定 | `urls.py` |
| 审批流引擎 | `distribution_order_workflow_engine.py` |

## 验收标准

- [ ] （可验证条目 1）
- [ ] （可验证条目 2）

## 参考

- 任务说明：`tasks/_example/README.md`
- 代码示例：`tasks/distribution_order/`
