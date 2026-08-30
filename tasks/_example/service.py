"""业务逻辑层示例。

分层职责见 `.agent/rules/api-patterns.md` 的"模块分层"小节。
**关键**：service 不 commit / rollback，事务边界由 view 管。

session 是 SQLAlchemy 2.0 `AsyncSession`，所有 SQL 必须 `await`，
故 service 函数本身也都是 `async def`，view 调用时同样要 `await`。

下面给四个最小桩，对齐 view 里的 list / save（合一） / add+update（分开）三种范式。
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import ExampleIn


async def list_example(
    bi_session: AsyncSession,
    customer_ids: List[int],
    keyword: str,
    page: int,
    pageSize: int,
) -> Dict[str, Any]:
    """列表查询，返回 {data, total}。"""
    # TODO: 用 await bi_session.execute(select(...)) 查询 + 分页
    return {"data": [], "total": 0}


async def save_example(
    inter_session: AsyncSession,
    body: ExampleIn,
    operator_id: Optional[int] = None,
) -> int:
    """合一接口：按 body.id 是否存在分新增/更新，返回主键 id。"""
    if body.id:
        # TODO: await inter_session.execute(update(...))
        return body.id
    # TODO: await inter_session.execute(insert(...))，返回新主键
    return 0


async def add_example(
    inter_session: AsyncSession,
    body: ExampleIn,
    operator_id: Optional[int] = None,
) -> int:
    """新增。"""
    # TODO: await inter_session.execute(insert(...))
    return 0


async def update_example(
    inter_session: AsyncSession,
    body: ExampleIn,
    operator_id: Optional[int] = None,
) -> None:
    """更新。view 层负责保证 body.id 非空。"""
    # TODO: await inter_session.execute(update(...))
    return None
