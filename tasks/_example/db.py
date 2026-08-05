"""数据库会话依赖（占位 stub）。

主仓真身：
- `get_async_session`     —— 主业务库 inter（读写）
- `get_async_data_session` —— BI 库（只读）

两者都返回 SQLAlchemy 2.0 `AsyncSession`，所有 SQL 操作必须 `await`：
    await session.execute(...)
    await session.scalar(...)
    await session.commit()
    await session.rollback()

主仓真实实现通常是 async generator（`async def f() -> AsyncIterator[AsyncSession]`，
内部 `yield session` 并在 finally 关闭）。本 stub 仅为类型占位，复制任务后改回主仓 import。
"""
from sqlalchemy.ext.asyncio import AsyncSession


async def get_async_session() -> AsyncSession:
    """主业务库 inter_session（读写）。"""
    raise NotImplementedError("replace with real dependency from main repo")


async def get_async_data_session() -> AsyncSession:
    """BI 库 bi_session（只读）。"""
    raise NotImplementedError("replace with real dependency from main repo")
