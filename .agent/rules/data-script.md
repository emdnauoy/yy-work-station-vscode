---
description: 数据脚本约定（刷数、回灌、导出）。DfToMySqlHelper 客户端声明位置、get_df_by_sql 读、insert_many_by_executemany 写与 with_id 语义。
alwaysApply: false
globs: tasks/code_analys/**/*.py,tasks/**/scripts/**/*.py
---

# 数据脚本（刷数 / 回灌 / 导出）

读写 MySQL 统一走 `DfToMySqlHelper`，**禁**自己起 `pymysql` 连接或手写连接池。

## 客户端声明

`read_client` / `write_client` **写在导入包之后的模块顶部**，与配置常量放一起；**禁**在 `main()` 或业务函数里临时 new（脚本内多处调用会重复建连）。

```python
sys.path.append(os.getcwd().split('apps')[0])

from apps.pyscript.helpers.df_mysql_helper import DfToMySqlHelper
from conf.settings import settings

read_client = DfToMySqlHelper(host=settings.READ_ONLY_HOST, db='bi', user=settings.USER, password=settings.PASSWORD, port=settings.PORT)
write_client = DfToMySqlHelper(host=settings.HOST, db='bi', user=settings.USER, password=settings.PASSWORD, port=settings.PORT)
```

- 读走 `settings.READ_ONLY_HOST`（只读从库），写走 `settings.HOST`；**禁**拿 `write_client` 跑大查询
- 只读脚本可只留 `read_client`；命名固定 `read_client` / `write_client`，**禁** `my_client` / `client` 这类看不出读写的名字
- **禁**在脚本里硬编码 host / 账号 / 密码，一律取 `settings`

## 读数据

```python
df = read_client.get_df_by_sql(sql)
if df is None or df.empty:
    return
```

返回可能是 `None`，**必须**用 `if df is None or df.empty` 守卫，**禁**直接 `.empty` 或直接下标。

## 写数据

```python
success = write_client.insert_many_by_executemany(table_name=TABLE, tmp_df=chunk, with_id=False)
if not success:
    raise RuntimeError('insert_many_by_executemany 写入失败，offset=%s' % i)
```

| `with_id` | 语义 |
|-----------|------|
| `True` | 带 `_id` 插入，`tmp_df` 必须含 `_id` 列（回写已知主键的行） |
| `False` | 按唯一键插入更新（upsert），表上须有对应唯一键，无 `_id` 列 |

- 返回 bool，**必须**判断，失败要抛出或记 error，**禁**忽略返回值当成功
- 写前把 `NaN` / `inf` 转 `None`：`df.replace([np.inf, -np.inf, np.nan], None, inplace=True)`，否则会写成字符串 `nan`
- 大批量按 `INSERT_BATCH_SIZE`（通常 1000）分片循环写，**禁**一次性 executemany 几十万行
