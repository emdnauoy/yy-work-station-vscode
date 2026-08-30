---
description: API 接口核心约定。分层、路由、Session、鉴权、返回值、View 骨架、翻译、_id 陷阱。
alwaysApply: false
globs: tasks/**/*.py
---

# API 接口核心约定

写新接口 / 建表时另读 `.agent/rules/api-patterns-ref.md`（模板与 DB 三件套）；操作日志见 `.agent/rules/api-logging.md`（编辑 view 时读）。

## 分层

| 层 | 文件 | 职责 |
|----|------|------|
| 路由 | `urls.py` | 绑定 view：`api.<method>(path, summary="<中文>")(fn)`；**禁**在 view 上写 `@router.get/post` |
| 接口 | `view/<业务>.py` | 校验、调 service、组装返回；**管事务**（try/commit/except/rollback）；**禁**直接写 SQLAlchemy 查询 |
| 业务 | `service.py` | 规则、SQL/ORM、状态机、查询条件构建与分页；**禁 commit/rollback** |
| 数据 | `models.py` / `schemas.py` | ORM + Pydantic，只放形状不放逻辑 |
| DDL | `<表名>.sql` | 建表脚本 |

路径格式：`/<模块>/<子业务>/<动作>/`，全小写 snake_case，尾斜杠，每条路由必带 `summary`。

## import

**禁**相对路径（`from .x`、`from ..x`），**用**主仓绝对路径 `from apps.system.<任务包名>.<模块> import ...`；主仓公共包（`core`、`loguru`）保持原写法。

## Session 与用户

| 参数 | 库 | 用途 |
|------|-----|------|
| `bi_session` | BI 库（只读） | 报表、列表、统计 |
| `inter_session` | 主业务库（读写） | 增改、状态变更 |

- 所有 SQL 必须 `await`；service 用 session → `async def`
- 同接口读 BI + 写主库 → 两者同时注入；**禁**拿 `inter_session` 当只读
- 鉴权：`oauth2_scheme = OAuth2PasswordBearer(tokenUrl=settings.AuthUrlPart + "/login/")`，签名末尾注入 `token: str = Depends(oauth2_scheme)`；取用户用主仓 `Depends(get_current_user)`，**禁**自行解析 token
- 取值：`request.user.id` / `request.user.display_name`
- 查显示名：`UserService.get_user_name_by_userid`（`apps.common.service.user`，session 与查询同库），传 list 返 `{user_id: name}`；`user_id == 0` 固定 `"System"`，**禁**查库

## 命名与返回值

- Python 标识符 `snake_case`；HTTP 字段**保留驼峰**（`pageSize`、`isDownload`）；不一致用 `Field(alias=...)` 显式映射，**禁**隐式约定
- 成功：`{"code": 200, "msg": <已翻译文案>, "data": data}`，**禁** `"success"`
- 异常：`{"code": 40000, "msg": "<描述>", "data": {}}`；所有业务异常统一 40000，**禁**其他错误码，**禁** `raise HTTPException`，HTTP 层始终 200
- 文件下载（`is_download=1`）→ `StreamingResponse` / `FileResponse`，不套 code/msg/data

## View 骨架

```python
from loguru import logger

async def some_view(body: SomeIn, inter_session=Depends(get_async_session)):
    try:
        result = await some_service(inter_session, body)
        await inter_session.commit()
        return {"code": 200, "msg": translate_text("操作成功", is_trans, translation_dict), "data": result}
    except SomeBusinessError as exc:
        await inter_session.rollback()
        return {"code": 40000, "msg": translate_text(exc.msg, is_trans, translation_dict), "data": {}}
    except Exception as e:
        await inter_session.rollback()
        logger.error(f"some_view 失败：{e}")
        return {"code": 40000, "msg": translate_text("操作失败", is_trans, translation_dict), "data": {}}
```

业务异常返回 `exc.msg`；兜底异常先 `logger.error(f"<操作>失败：{e}")`（**禁** `%s` 占位）再返回通用文案，**禁**把异常细节暴露给前端。

## 翻译

- 读接口挂 `@translate_all_output`，**禁**再手动 `translate_text`。参数：`modules` 翻译来源模块名；`translatable_fields` 直译字段；`kv_fields` / `v_fields` / `k_fields` 字典翻 key+value / 仅 value / 仅 key；`skip_fields` 至少 `data, pageSize, page, total, page_total, date`；`default_lang` 默认 `cn`
- 装饰链：`urls` 路由绑定（外）→ `@translate_all_output`（中）→ `async def`（内核）
- 写接口 `msg` 按请求语言翻译：

```python
from apps.system.<任务包名>.translate import translate_text

is_trans, translation_dict = get_translaiton_dict_from_request(request, ["<任务包名>", "common", "common_filters", "msg"])
return {"code": 200, "msg": translate_text("操作成功", is_trans, translation_dict), "data": data}
```

## Pydantic v1

`_id` 主键陷阱：v1 忽略下划线开头字段，**禁**写 `_id: Optional[int] = None`，必须用别名：

```python
id: Optional[int] = Field(None, alias="_id")
class Config:
    allow_population_by_field_name = True
# SQL 写 _id，Python 用 body.id
```

**禁** v2 语法（`ConfigDict` / `model_config` / `model_validator`）；可变默认值用 `Field(default_factory=list)`，**禁** `= []` / `= {}`。
