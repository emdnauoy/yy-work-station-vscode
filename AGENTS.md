# yy-work-station

yy 主项目卫星工作区。小需求按 `tasks/<任务名>/` 隔离。规则统一在 `.agent/rules/`。

## 硬约束（所有会话必读）

- **交流用简体中文**
- **任务隔离** — 只改当前 `tasks/<任务名>/`，禁跨任务改代码（除非明确要求）；禁改 `tasks/_example/`；禁假设主仓结构。副本类任务默认以当前工作区文件为准；仅用户明确要求时才核验主仓分支、提交和文件变更，并将核验结果或「未核验」写入 README
- **技术栈锁定** — 禁 Python 3.9+ 语法、Pydantic v2、Django/Flask
- **禁硬编码密钥** — 禁在代码/规则/文档里硬编码 host/账号/密码/密钥，一律取 `settings`
- **先设计后编码** — 新需求先定表设计 + 方案设计，确认后再写 models/service/urls（修 bug 等小改动除外）
- **能配的不要打补丁** — 配置（Menu、`page_structure.json` 等）能表达的只改配置，禁在代码里覆盖/补列/硬编码
- **改完标路径** — 回复列出改动文件的仓库相对路径 + 一句要点；涉及关键函数时标明函数名；禁只说「已改好」
- **定点读，不通读** — 先 Grep / 符号搜索定位，再读目标与直接调用处；仅在参数来源、计算口径或影响范围不清时扩读相关依赖。大文件/长文档按段读，证据足够即停止
- **历史写法优先** — 既有代码与规则冲突时保持原样，只改需求相关行；规则只约束新增代码。不得顺手重排或重构；发现由本次改动产生的孤儿代码应清理
- **仅用户明确要求时**才 git commit / push / 创建 PR
- **遵循 Karpathy Guidelines** — 行为准则（`.agent/rules/karpathy-guidelines.md`）

## 编辑代码前必读

| 场景 | 必读规则 |
|------|----------|
| 编辑任意 `tasks/**/*.py` | `.agent/rules/api-patterns.md`（分层/Session/鉴权/返回值/翻译/_id 陷阱） |
| 编辑 `tasks/**/view/**/*.py` | 上述 + `.agent/rules/api-logging.md`（操作日志） |
| 写数据脚本/刷数/回灌 | `.agent/rules/data-script.md` |
| 编辑某任务目录 | `.agent/rules/tasks/<任务名>.md` + `tasks/<任务名>/README.md` |
| 写接口骨架/建表 | `.agent/rules/api-patterns-ref.md` |

规则优先级：task 规则 > api-patterns/api-view/db-schema/api-logging/data-script > yy-global > karpathy。

完整约定（技术栈、常用命令、目录、新建子任务、行为准则精炼）见 `.agent/rules/yy-global.md`；规则写法约定见 `.agent/rules/authoring-rules.md`；整体设计与迁移说明见 `AGENTS_GUIDE.md`。
