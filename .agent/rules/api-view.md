---
description: 编写或修改接口 View 时必读：事务、异常与翻译。独立脚本不适用。
alwaysApply: false
globs: tasks/**/view/**/*.py
---

# View 层事务、异常与翻译

分层、Session 与返回值见 `.agent/rules/api-patterns.md`；操作日志见 `.agent/rules/api-logging.md`。本文件只约束新增代码，既有 View 保持现有事务边界与响应契约。

## 事务与异常

- 新增写接口由 View 在业务成功后 `commit`，异常时 `rollback`；业务与操作日志使用同一事务
- 业务异常返回 `exc.msg`；兜底异常先 `logger.error(f"<操作>失败：{e}")`（禁 `%s` 占位）再返回通用文案，禁向前端暴露异常细节

## 翻译

- 读接口挂 `@translate_all_output`，禁再手动 `translate_text`；`skip_fields` 至少含 `data, pageSize, page, total, page_total, date`，`default_lang` 默认 `cn`
- 装饰顺序：`urls` 路由绑定（外）→ `@translate_all_output`（中）→ `async def`（内核）
- 写接口的 `msg` 按请求语言用 `translate_text` 翻译；翻译来源模块、字段和字典映射按接口实际数据声明
