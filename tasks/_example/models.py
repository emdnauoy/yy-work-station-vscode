"""ORM 模型示例（SQLAlchemy 2.0，保留 Column 旧风格以兼容主仓既有代码）。

约定：
- 主键固定列名 `_id`，BigInteger autoincrement
- 选项/状态字段用 SmallInteger，含义写在 comment 里
- 时间字段统一 DB 端默认值（server_default / server_onupdate）
- 不加 ForeignKey 约束
- 表名 data_<模块>_<业务>，schema 固定 internal_app

## 草稿支持

业务字段（外键、状态、备注、关联列表等）默认 `nullable=True` **且不给默认值**，
让"用户没填"（NULL）与"用户主动填空值"（"" / 0 / [] 等）能在 DB 层区分开。
状态字段 `status` 的 NULL 即代表"草稿/未提交"。

如果你的业务**不需要草稿**：复制后把对应字段改回 `nullable=False` + 合理 default 即可。
"""
from sqlalchemy import BigInteger, Column, DateTime, SmallInteger, String, func
from core.db.base import Base


class ExampleRecord(Base):
    __tablename__ = "data_example_record"
    __table_args__ = {"comment": "示例业务表（支持草稿）", "schema": "internal_app"}

    _id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    offline_customer_id = Column(
        BigInteger, nullable=True, comment="关联客户的id；草稿可空"
    )
    status = Column(
        SmallInteger,
        nullable=True,
        comment="状态：1=正常 2=禁用；NULL=草稿/未提交",
    )
    remark = Column(String(500), nullable=True, comment="备注；草稿可空")
    create_time = Column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    update_time = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
        comment="更新时间",
    )
    create_by = Column(BigInteger, nullable=True, comment="创建人id")
    update_by = Column(BigInteger, nullable=True, comment="更新人id")
