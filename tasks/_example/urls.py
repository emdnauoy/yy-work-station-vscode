"""路由注册（对齐主仓 urls.py 惯例）。

主仓写法（关键差异，区别于 FastAPI 默认 @装饰器写法）：
- 路由统一在 urls.py 集中绑定，用**调用形式**而非装饰器：
      api.<method>(path, summary="<中文>")(<view_fn>)
- view 函数顶上**不写** @router.xxx，只挂 @translate_all_output（如需）
- 路径风格：`/<业务模块>/<子业务>/<动作>/`，全小写 snake_case，带尾斜杠
      例：/offline_customer/contract/list/
- 每条路由**必给** `summary="<中文描述>"`，方便 Swagger 阅读
- 如需更详细文档，可追加 `description="..."`、`response_model=...` 等

复制任务后：
1. 把 `example_api` 改成你的业务名 `<xxx>_api`
2. 替换每条路由的 path（按主仓既有路径规则）和 view 函数
3. 在主仓总入口 import 并挂载：
      from <你的任务包路径>.urls import <xxx>_api
      app.include_router(<xxx>_api)
"""
from fastapi import APIRouter

from .view.example import (
    example_add,
    example_list,
    example_save,
    example_update,
)

example_api = APIRouter(tags=["example"])

# ---- 列表（GET）----
example_api.get(
    "/example/list/",
    summary="示例列表（分页）",
)(example_list)

# ---- 增改合一（POST）：新增 / 修改逻辑基本一致时使用 ----
example_api.post(
    "/example/save/",
    summary="示例保存（新增/修改合一）",
)(example_save)

# ---- 增改分开（POST + POST）：新增 / 修改差异显著时使用 ----
# 同一业务模块只用一种范式，不要 save 和 add+update 混用
example_api.post(
    "/example/add/",
    summary="示例新增",
)(example_add)
example_api.post(
    "/example/update/",
    summary="示例修改",
)(example_update)
