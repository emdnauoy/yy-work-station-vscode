"""读写模型示例（Pydantic v1）。

## 为什么 ExampleIn 写得这么详细？

每个 `Field` 的 `description` / `example` / 约束都会出现在 FastAPI `/docs/` 里。
前端打开 Swagger UI 就能看到"字段含义、必填/可选、默认值、示例值、长度/范围"，
点 "Try it out" 还能直接拿 `Config.schema_extra.example` 当请求体发联调请求。
这能省掉大量前后端口头沟通。

> 仅"新增/修改"请求体（`ExampleIn`）写到这个详细程度。响应模型 `ExampleOut`
> 只保留字段定义，不写 description/example——避免 docs 里东西过多反而难读。

## 字段写法约定

- 必填：`Field(..., description="<中文>", example=<示例值>, <约束...>)`，不要省略 description。
- 可选：把默认值放在 Field 第一参数位（如 `Field(None, ...)` / `Field("", ...)`），
        description 里加"（可选）"或写明"留空时…"。
- 状态/枚举类字段：在 description 里把所有取值含义列全（如 "1=正常 2=禁用"），
        必要时加 `ge=`/`le=` 限制范围。
- 字符串字段尽量给 `max_length`，避免前端误传巨长内容打爆 DB。
- 数值字段加 `ge` / `gt` / `le` / `lt`，至少限制非负。
- `_id` 主键陷阱：Pydantic v1 会忽略 `_` 开头字段，必须 `Field(None, alias="_id")` +
        `class Config: allow_population_by_field_name = True`。

## 草稿支持

本模板默认支持"保存草稿"——业务字段全部 `Optional[...]` 且默认 `None`，与 DB 层
`nullable=True` 对齐。"用户没填" 与 "用户填了空值" 在 schema 与 DB 都可区分：

- 草稿保存：前端只需传必能确定的字段（甚至全空），后端 service 直接写 NULL。
- 正式提交：前端把字段补全，后端可在 service 层加"提交时校验"（不在 schema 强校验）。

如果你的业务**不需要草稿**，把字段从 `Optional[X]` 改成 `X`、Field 默认值 `None` 改成
`...`（必填）或合理默认值即可。
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# =========================
# 请求体（写入）—— 详细描述给前端 /docs/
# =========================


class ExampleIn(BaseModel):
    """示例 - 新增 / 修改请求体（草稿友好：业务字段均可空）。"""

    id: Optional[int] = Field(
        None,
        alias="_id",
        description="主键 ID。新增时省略或传 null；修改时必传",
        example=1001,
    )
    offline_customer_id: Optional[int] = Field(
        None,
        description="关联客户 ID；草稿可空，正式提交时由 service 校验",
        example=2001,
        gt=0,
    )
    status: Optional[int] = Field(
        None,
        description="状态：1=正常，2=禁用；草稿可空（NULL 表示未提交）",
        example=1,
        ge=1,
        le=2,
    )
    remark: Optional[str] = Field(
        None,
        description="备注，最长 500 字；草稿可空",
        example="VIP 客户",
        max_length=500,
    )
    nation: List[int] = Field(
        default_factory=list,
        description="关联国家 ID 列表；不传或空数组表示不限国家",
        example=[1, 2, 3],
        max_items=100,
    )

    class Config:
        allow_population_by_field_name = True
        # /docs/ 里 "Example Value" 一栏会直接显示这个完整对象，
        # 前端点 "Try it out" 即可发起联调请求。
        schema_extra = {
            "example": {
                "_id": None,
                "offline_customer_id": 2001,
                "status": 1,
                "remark": "新建一条示例记录",
                "nation": [1, 2],
            }
        }


# =========================
# 响应单条（读出）—— 仅字段定义，不写 docs 元数据
# =========================


class ExampleOut(BaseModel):
    """示例 - 单条记录响应（草稿记录的业务字段可能为 null）。"""

    id: int = Field(..., alias="_id")
    offline_customer_id: Optional[int] = None
    status: Optional[int] = None
    remark: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    create_by: Optional[int] = None
    update_by: Optional[int] = None

    class Config:
        allow_population_by_field_name = True
        orm_mode = True  # 支持从 ORM 对象直接序列化
