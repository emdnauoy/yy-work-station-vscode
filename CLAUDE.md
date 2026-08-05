# yy-work-station

yy 主项目卫星工作区。小需求拆到 `tasks/<snake_case>/`，任务间隔离。

## 技术栈

Python 3.8 · FastAPI · Pydantic v1 · SQLAlchemy 2.0 async · MySQL 8.0 · uvicorn
**禁** Django/Flask/Pydantic v2/3.9+ 语法。依赖以主仓为准。

## 核心约束

1. **先设计后编码** — 新需求先定表设计+方案，用户确认后再写代码（修 bug 等小改动除外）
2. **任务隔离** — 禁跨 `tasks/*` 改代码（除非用户明确要求）
3. **交流用简体中文** · **仅用户要求时** git commit/push/PR
4. **Karpathy Guidelines** — 行为准则，详见 `/karpathy-guidelines` skill

## 模块分层

| 层 | 文件 | 职责 |
|----|------|------|
| 路由 | `urls.py` | 绑定 view：`api.<method>(path, summary=...)(fn)` |
| 接口 | `view/<业务>.py` | 校验、调 service、组装返回；**管事务**（try/commit/except/rollback）；**禁**直接写 SQLAlchemy 查询 |
| 业务 | `service.py` | 规则、SQL/ORM、状态机；**禁 commit/rollback** |
| 数据 | `models.py` / `schemas.py` | ORM + Pydantic；只放形状，不放逻辑 |
| DDL | `<表名>.sql` | 建表脚本 |

## 路由

- `urls.py` 用调用形式，**禁** view 上写 `@router.get/post`
- 路径：`/<模块>/<子业务>/<动作>/`，全小写 snake_case，尾斜杠
- 每条路由必 `summary="<中文>"`

## 鉴权

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=settings.AuthUrlPart + "/login/")
token: str = Depends(oauth2_scheme)  # 取用户用主仓 Depends(get_current_user)，禁自行解析
```

## Session

| 参数 | 库 | 用途 |
|------|-----|------|
| `bi_session` | BI 库（只读） | 报表、列表、统计 |
| `inter_session` | 主业务库（读写） | 增改、状态变更 |

- 所有 SQL 必须 `await`；service 用 session → `async def`
- 同接口读 BI + 写主库 → 两者同时注入；**禁** `inter_session` 当只读
- 取用户：`request.user.id` / `request.user.display_name`，**禁** `getattr(getattr(request, "user", None), ...)`

## 命名与返回值

- Python：`snake_case`；HTTP 字段：**保留驼峰**（`pageSize`）；不一致 → `Field(alias=...)`
- 成功：`{"code": 200, "msg": "操作成功", "data": data}`（msg 必须翻译，**禁** `"success"`）
- 异常：`{"code": 40000, "msg": "<描述>", "data": {}}`（**禁**其他错误码，**禁** raise HTTPException）
- 文件下载（`is_download=1`）→ `StreamingResponse`/`FileResponse`，不套 code/msg/data
- 用户：`request.user.id` / `request.user.display_name`；`user_id=0` → 固定 "System" 禁查库

## _id 主键陷阱（Pydantic v1）

v1 忽略下划线开头字段，**禁**写 `_id: Optional[int] = None`，必须：

```python
id: Optional[int] = Field(None, alias="_id")
class Config:
    allow_population_by_field_name = True
# SQL 写 _id，Python 用 body.id
```

**禁** v2 语法（`ConfigDict` / `model_config` / `model_validator`）。可变默认值：`Field(default_factory=list)`，**禁** `= []`。

## 数据库

- 主键：列名 `_id`，`BigInteger`，`autoincrement=True`
- 选项/状态：`SmallInteger`，含义写 `comment`；**禁**字符串枚举
- 外键：`<关联表名>_id`，**禁** ForeignKey 约束
- 表名：`data_<模块>_<业务>`，schema `internal_app`，`utf8mb4_unicode_ci`，`InnoDB`
- 审计四件套：`create_time` / `update_time` / `create_by` / `update_by`（**禁** `_at` / `created_*`）
- 软删：`is_deleted TINYINT DEFAULT 0`（0=正常 1=已删），**禁** body 传入，查询默认 `=0`
- 时间默认值：DB 端 `server_default=func.now()`，**禁** Python+SQL 双写
- `TEXT` 禁 `DEFAULT ''`；必须参数化，**禁**字符串拼接

### Pydantic 读写模型

- `XxxIn`：参考 `_id` 别名陷阱
- `XxxOut`：`id: int = Field(..., alias="_id")`；Config 加 `orm_mode = True` + `allow_population_by_field_name = True`

## 列表接口

参数：`page: int = 1`、`pageSize: int = 50`、`keyword: str = ""`；导出加 `is_download: int = 0`
多选筛选：`some_filter: str = "[]"` → `ast.literal_eval` 解析；失败返 `40000`；**禁**改 `List[int] = Query([])`
仅查询 → `bi_session`；需写库 → 加 `inter_session`
挂 `@translate_all_output`，`skip_fields` 至少 `data, pageSize, page, total, page_total`
枚举/状态字段须附可读文案（`status_str`），**禁**只返魔法数字

## 增改接口

逻辑基本一致 → 合一（按 `body.id` 分支）；差异大 → 拆 add/update；同模块禁混用

## View 层骨架

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

- 业务异常（`SomeBusinessError`）：返回 `exc.msg`，已翻译
- 兜底异常：`logger.error(f"<操作>失败：{e}")`，msg 返回翻译后的通用文案（如"操作失败"），**禁**暴露异常细节给前端

## 翻译（i18n）

- 读接口：挂 `@translate_all_output` 装饰器，**禁**再手动 `translate_text`
- 写接口：POST 返回体 `msg` 按请求语言翻译

```python
from apps.system.<任务包名>.translate import translate_text

is_trans, translation_dict = get_translaiton_dict_from_request(
    request, ["<任务包名>", "common", "common_filters", "msg"]
)
msg = translate_text("操作成功", is_trans, translation_dict)
return {"code": 200, "msg": msg, "data": data}
```

## 操作日志

> 编辑 `tasks/**/view/**/*.py` 时生效。增改必记，与业务同事务。

- 函数：`log_async_create`（`apps.common.service.yy_log`）、`deep_diff_create`/`deep_diff`（`apps.<模块>.change_diff`）
- view 层 `commit` 前调用，传同一 `inter_session`
- 更新：`deep_diff` 非空才记；新建：无差异也记
- `ignore_keys` 至少：`_id`、`create_time`、`update_time`、`create_by`、`update_by`、`button_list`
- `refer_type`：`<模块中文>-新建` 或 `-修改`；子业务加主业务前缀（如 `分销订单-修改行`）

```python
from apps.common.service.yy_log import log_async_create
from apps.system.<模块>.change_diff import deep_diff_create, deep_diff

IGNORE = {"_id", "create_time", "update_time", "create_by", "update_by", "button_list"}

if is_create:
    details = json.dumps(deep_diff_create(original_data) or {}, ensure_ascii=False, default=_log_json_default)
    await log_async_create(username=user_name, types="新建", operation_details=details,
        session=inter_session, refer_type="<模块>-新建", refer_table="data_<表>", refer_id=entity_id)
else:
    clean_logs = deep_diff(old_data=old_data, new_data=original_data, ignore_keys=IGNORE)
    if clean_logs:
        details = json.dumps(clean_logs, ensure_ascii=False, default=json_serializer)
        await log_async_create(username=user_name, types="更新", operation_details=details,
            session=inter_session, refer_type="<模块>-修改", refer_table="data_<表>", refer_id=entity_id)
```

## 代码风格

- 文件头：`# -*- coding: utf-8 -*-` + `@Time` / `@Author` / `@File` / `@Description`
- 单行 ≤ 100 字符；`import` 每行多个符号，**禁**一项一行
- **禁**相对路径（`from ..x`）；**用**主仓绝对路径：`from apps.system.<任务包名>.<模块> import ...`
- logger：`logger.error(f"<操作>失败：{e}")`，**禁** `%s` 占位

## 子任务规则

每个子任务目录下有自己的 `CLAUDE.md`，进入该目录时自动加载。

| 子任务 | 规则文件 |
|--------|----------|
| `distribution_order` | `tasks/distribution_order/CLAUDE.md` |
| `offline_customer` | 无专属规则，仅全局规则生效 |
| `code_analys` | `tasks/code_analys/CLAUDE.md` |

## 新建子任务

1. 复制 `tasks/_example/` → `tasks/<任务名>/`，编辑 README
2. 复制 `tasks/_example/CLAUDE.md` → `tasks/<任务名>/CLAUDE.md`，替换任务名
3. 复制 `.cursor/rules/tasks/_example.mdc` → `.cursor/rules/tasks/<任务名>.mdc`（Cursor 用）
4. 在本文件"子任务规则"表中补充新任务条目
5. 代码模式参考 `tasks/distribution_order/`（service/view/schemas/models/urls）
