# Question 3: KOL 自动剪辑视频筛选条件调整

## 问题

`update_tiktok_video_kol_data.py` 的 `_update_tiktok_video_auto_clip` 函数用于给平台自动剪辑视频打标签（`wb_kol_tag |= 64`），其筛选条件需要调整。

## 原因

原筛选条件为「视频原始类型全为 Affiliate + 不挂车 + 账号类型 Official/Marketing」，需求变更为 4 个明确条件：官方/营销账号、不挂车、标题长度≤100、标题无 `#`。原「全为 Affiliate」判断被账号类型条件取代。

## 影响

- 被选中打上 Auto_Clip 标签（`wb_kol_tag` bit 64）的视频集合变化：不再要求视频原始类型（`origin_creator_type`）为 Affiliate，新增标题长度与内容约束。
- 更新目标表不变：`bi.data_tiktok_video_meta.wb_kol_tag`。

## 修复

`_update_tiktok_video_auto_clip` 新筛选条件（全部满足才打标签）：

| 条件 | 实现 | 层级 |
|------|------|------|
| 账号类型 official/marketing | kol `account_type in (2, 3)` + 行级 `creator_type in ['Official', 'Marketing']` | kol 层 SQL + 行级 mask |
| 商品信息为空（不挂车） | `product_list.isin([[], '[]']).all()` | video_id 分组 all() |
| 视频标题字符长度 ≤ 100 | `video_name.str.len().le(100).all()` | video_id 分组 all() |
| 视频标题无 `#` | `(~video_name.str.contains('#')).all()` | video_id 分组 all() |

更新语句：`UPDATE bi.data_tiktok_video_meta SET wb_kol_tag = wb_kol_tag | 64 WHERE video_id IN (...)`。

**2026-08-07 补充**：本次改动已同步到两处文件（内容完全一致，md5 相同）：
- `tasks/code_analys/question3_kol_auto_clip/update_tiktok_video_kol_data.py`（task 副本）
- `apps/pyscript/tiktok_obsess/update_tiktok_video_kol_data.py`（主仓源文件）

### 月度刷新脚本（2026-08-07 新增）

`refresh_auto_clip_monthly.py`：按月度刷新历史 Auto_Clip 标签（完全校正 + 仅 kol 表达人）。

- 位置：`tasks/code_analys/question3_kol_auto_clip/refresh_auto_clip_monthly.py`（仅 task 副本，默认不同步主仓；如需同步 `apps/pyscript/tiktok_obsess/` 需用户明确要求）
- 职责：逐月校正 `data_tiktok_video_meta.wb_kol_tag` bit 64 —— 清除不再满足 4 条件的视频标签（`& ~64`）、补打新满足的视频标签（`| 64`）；处理范围仅官方/营销达人视频（`account_type in (2,3)`）
- 用法：`python refresh_auto_clip_monthly.py [--start_month YYYY-MM] [--end_month YYYY-MM]`，默认最近 12 个月
- 月度流程：查当月 `data_tiktok_video`（`start_time` 月内 + `creator_id IN 达人`）→ 4 条件筛 `keep_ids` → 查 meta 已打 bit64 的 `tagged_ids` → 补打 `keep_ids - tagged_ids`、清除 `tagged_ids - keep_ids`；打标/清除均 500/批参数化
- 与主脚本关系：主脚本 `_update_tiktok_video_auto_clip` 管增量（仅打标不清除）；刷新脚本管存量校正（打标 + 清除），4 条件筛选逻辑保持一致

## 可复用

**字段定义：**
- `bi.data_tiktok_video`（按天统计的视频明细表，ORM `dataTikTokVideo` @ `apps/common/model/tiktok.py:359`）
  - `video_id`：BIGINT，视频 ID；同一视频多天多行
  - `video_name`：String(255)，视频标题
  - `product_list`：String(4096)，商品信息 JSON；`'[]'` = 不挂车，NULL 会被 `isin` 排除
  - `creator_type`：String(30)，账号类型 `Official` / `Marketing` / `Affiliate` 等
  - `start_time`：DateTime，数据起始日期（脚本按此过滤时间范围）
- `bi.data_sys_tiktok_obsess_kol.account_type`：`2`=Official，`3`=Marketing（CASE 映射见脚本 SQL）
- `bi.data_tiktok_video_meta.wb_kol_tag`：位标记，见 `apps/common/service/bitmap_tag_system.py`；`bit 64 (2^6)` = Auto_Clip「平台自动生成直播切片短视频」（`WbKolTag.Auto_Clip`）；另有 bit1=WB、bit8=AI

**数据模型关系：**
- `data_tiktok_video` 与 `data_tiktok_video_meta` 按 `video_id` 关联；脚本更新目标为 meta 表，`WHERE video_id IN (...)`

**关键链路：**
- 脚本（task 与主仓两处已同步一致）：`tasks/code_analys/question3_kol_auto_clip/update_tiktok_video_kol_data.py` / `apps/pyscript/tiktok_obsess/update_tiktok_video_kol_data.py`
- 函数：`_update_tiktok_video_auto_clip`（约 406-474 行），`process()` 中第 5 步调用
- 月度刷新脚本（2026-08-07 新增，仅 task，默认不同步主仓）：`tasks/code_analys/question3_kol_auto_clip/refresh_auto_clip_monthly.py`，按月完全校正 bit64（补打 `| 64` + 清除 `& ~64`）
- 位定义：`apps/common/service/bitmap_tag_system.py` `WbKolTag`（改标签含义需同步协同筛选 common_collaboration 的 Kol_Tags / kol_account_tags）

**验证方法：**
- 对目标 creator_id 拉 `data_tiktok_video` 记录，手动核对 4 条件，确认 `video_ids` 集合与脚本输出一致
- 检查更新后 `data_tiktok_video_meta.wb_kol_tag` 的 bit 64 是否置位（`(wb_kol_tag & 64) = 64`）

**坑点清单：**
- `data_tiktok_video` 按天统计：同一 `video_id` 多行，须按 video_id 分组、组内**所有行都满足**才算（`.all()`），否则会误打标
- `product_list` 为 NULL 时 `isin([[], '[]'])` 不匹配，会被排除；只有 `'[]'` 才视为不挂车
- `video_name` 为 NULL 必须先 `fillna('')`，否则 `str.len()`/`str.contains()` 报错；NULL 视作空标题（满足长度与无 `#` 条件）
- `creator_type` 是行级过滤（mask），`product_list`/`video_name` 是分组级（all()），两者判断层级不同，改动时勿混
- 账号类型双层过滤：kol 层 `account_type in (2,3)`（SQL）+ 视频行层 `creator_type`，两层都要保留

## 关联

无
