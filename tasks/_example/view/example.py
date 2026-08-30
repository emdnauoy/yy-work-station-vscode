"""接口实现示例：列表 + 增改合一 + 增改分开三种范式。

完整约定见 `.agent/rules/api-patterns.md`。本文件最易出错的三点：
- 路由绑定不在本文件，统一在 ../urls.py 用调用形式 `api.<method>(path, summary=...)(fn)`
- view 管事务边界（`await commit` / `await rollback`）；**service 层不 commit**
- 业务异常 `return {"code": 40000+, "msg": "...", "data": {}}`，**不 raise HTTPException**

session 是 `AsyncSession`，调 service 与 commit/rollback 都要 `await`。
复制任务后把 stub 的 import 改回主仓真实路径（`..auth` / `..db` / `..translate`）。
"""
import ast
import logging
import traceback
from typing import Any, Dict, List

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import service
from ..auth import oauth2_scheme
from ..db import get_async_data_session, get_async_session
from ..schemas import ExampleIn
from ..translate import translate_all_output

logger = logging.getLogger(__name__)


@translate_all_output(
    modules=["example"],
    translatable_fields=["name", "title", "label", "tips"],
    skip_fields=["data", "pageSize", "page", "total", "page_total", "date"],
)
async def example_list(
    request: Request,
    customer_ids: str = "[]",
    keyword: str = "",
    is_download: int = 0,
    page: int = 1,
    pageSize: int = 50,
    bi_session: AsyncSession = Depends(get_async_data_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    try:
        customer_ids_list: List[int] = ast.literal_eval(customer_ids)
    except Exception:
        logger.error("参数错误：%s", traceback.format_exc())
        return {"code": 40001, "msg": "参数错误", "data": {}}

    result = await service.list_example(
        bi_session=bi_session,
        customer_ids=customer_ids_list,
        keyword=keyword,
        page=page,
        pageSize=pageSize,
    )

    if is_download == 1:
        # TODO: 走 StreamingResponse / FileResponse 返回文件，不套 code/msg/data 结构
        ...

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "data": result["data"],
            "page": page,
            "pageSize": pageSize,
            "total": result["total"],
        },
    }


@translate_all_output(
    modules=["example"], translatable_fields=["msg"], skip_fields=["data"]
)
async def example_save(
    request: Request,
    body: ExampleIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    try:
        new_or_updated_id = await service.save_example(inter_session, body)
        await inter_session.commit()
    except Exception:
        await inter_session.rollback()
        logger.error("保存失败：%s", traceback.format_exc())
        return {"code": 50000, "msg": "保存失败", "data": {}}

    return {"code": 200, "msg": "保存成功", "data": {"id": new_or_updated_id}}


@translate_all_output(
    modules=["example"], translatable_fields=["msg"], skip_fields=["data"]
)
async def example_add(
    request: Request,
    body: ExampleIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    try:
        new_id = await service.add_example(inter_session, body)
        await inter_session.commit()
    except Exception:
        await inter_session.rollback()
        logger.error("新增失败：%s", traceback.format_exc())
        return {"code": 50000, "msg": "新增失败", "data": {}}

    return {"code": 200, "msg": "新增成功", "data": {"id": new_id}}


@translate_all_output(
    modules=["example"], translatable_fields=["msg"], skip_fields=["data"]
)
async def example_update(
    request: Request,
    body: ExampleIn,
    inter_session: AsyncSession = Depends(get_async_session),
    token: str = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    if not body.id:
        return {"code": 40001, "msg": "缺少 id", "data": {}}
    try:
        await service.update_example(inter_session, body)
        await inter_session.commit()
    except Exception:
        await inter_session.rollback()
        logger.error("修改失败：%s", traceback.format_exc())
        return {"code": 50000, "msg": "修改失败", "data": {}}

    return {"code": 200, "msg": "修改成功", "data": {"id": body.id}}
