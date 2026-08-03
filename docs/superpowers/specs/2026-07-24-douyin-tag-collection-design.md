# 抖音 Tag 数据采集设计

## 背景

运营任务需要从飞书多维表 `tblEBAE044RsVURX` 读取抖音 Tag 链接，解析 Tag ID，并使用抖音水号登录态请求：

`/aweme/v1/web/challenge/aweme/`

当前表包含字段：

- `tag`
- `链接`

样例链接：

`https://www.douyin.com/hashtag/7322391300177987638`

样例接口第一页已使用 `D:\browser_data\dy_text_data_dir` 的水号登录态验证成功：

- `status_code = 0`
- `has_more = 1`
- `cursor = 12`
- `aweme_list` 包含 12 条作品

请求中的 Cookie、`msToken`、`verifyFp`、`uifid` 和 `a_bogus` 均为会话数据或动态参数，不能写入源码、配置示例、数据库原始请求或 Git 提交。

## 目标

- 读取指定飞书 Tag 表中的全部有效链接。
- 从标准抖音 Hashtag URL 中解析 Tag ID。
- 自动选用已启用的抖音水号浏览器目录和 Cookie。
- 使用现有抖音客户端动态生成公共参数、`msToken` 和 `a_bogus`。
- 对每个 Tag 从游标 0 开始抓取全部接口可见作品。
- 只写新的 Tag 数据表，不写现有 `douyin_aweme` 表。
- 以 `tag_id + aweme_id + author_id` 保证幂等。
- 集成到 `run-all` 和 `collect-only`，不回写飞书。

## 非目标

- 不保存或硬编码用户提供的完整请求 URL。
- 不把 Tag 作品写入 `douyin_aweme`。
- 不抓取 Tag 作品评论或媒体文件。
- 不向飞书写回 Tag 结果。
- 不绕过登录、验证或平台访问控制。
- 不保证数据库记录数等于抖音网页展示总数；只保存接口实际返回的数据。

## 方案

采用“稳定字段列 + 完整作品 JSON”结构。稳定字段便于查询和统计，完整 JSON 保留响应中的长尾字段，避免把数百个易变化字段全部展开为数据库列。

不采用仅保存少量字段的方案，因为后续分析可能需要作者、视频和 Tag 扩展数据。

不采用全部字段扁平化方案，因为抖音响应字段数量大、嵌套深、变化频繁，会造成数据库迁移和空字段维护成本。

## 飞书配置与任务规划

增加可配置项：

`FEISHU_DOUYIN_TAG_TABLE_ID`

默认值使用已确认的 `tblEBAE044RsVURX`，以便现有环境无需额外修改也可运行。该表不依赖视图 ID，读取全部记录。

任务规划规则：

1. 读取每条记录的 `tag` 和 `链接`。
2. 忽略空链接。
3. 仅接受 `https://www.douyin.com/hashtag/{数字ID}` 及可安全解析为相同结构的 URL。
4. 相同 Tag ID 在单次计划中只创建一个任务。
5. 从飞书账号表选择已启用的抖音水号。
6. 多个水号按现有轮换逻辑分配。
7. 没有抖音水号时，计划阶段明确失败，不回退到主账号。

新增任务类型 `DOUYIN_TAG_CONTENT`。任务携带 Tag ID、Tag 名称、原始链接和水号 Profile，不携带 Cookie。

## 请求与分页

抖音客户端新增单页 Tag 请求方法，主机使用验证成功的 `https://www-hj.douyin.com`，路径为：

`/aweme/v1/web/challenge/aweme/`

业务参数：

- `ch_id`
- `query_type = 0`
- `sort_type = 0`
- `offset`
- `cursor`
- `count = 12`
- `support_h265 = 1`
- `support_dash = 0`

浏览器公共参数、Cookie、`webid`、`msToken` 和 `a_bogus` 继续由现有客户端生成。请求头的 Referer 使用当前 Hashtag 页面。

分页规则：

1. 初始 `cursor = 0`、`offset = 0`。
2. 每次将响应 `cursor` 用作下一页的 `cursor` 和 `offset`。
3. `has_more` 为假时结束。
4. `aweme_list` 缺失、为 `null` 或为空时结束。
5. 游标重复时记录警告并结束。
6. 同页重复作品由数据库唯一键幂等更新。
7. 每页请求后使用项目现有抓取间隔，避免突发请求。
8. 接口登录失效、账号受限或签名失败时让任务失败，不能伪装为完整结束。

日志包含 Tag 名称、Tag ID、当前游标、本页数量和累计数量，不记录 Cookie、Token、签名或完整请求查询串。

## 数据模型

新增 MySQL 表 `douyin_tag_aweme`。

### 标识与来源

- `id`：数据库主键。
- `tag_id`：抖音 Tag ID。
- `tag_name`：飞书 `tag` 字段原值。
- `tag_url`：飞书链接。
- `aweme_id`：作品 ID。
- `author_id`：优先使用 `author.uid`，缺失时依次回退 `author_user_id`、`author.sec_uid`。
- `sec_uid`：作者安全 ID。
- `source_cursor`：发现该作品的接口页游标。

若所有作者标识均缺失，则跳过该条并记录作品 ID，避免产生无法满足唯一约束的空作者记录。

### 作品字段

- `title`：`item_title`，为空时回退 `caption`。
- `description`：`desc`。
- `aweme_type`
- `media_type`
- `published_at`：由 `create_time` 转换。
- `region`
- `share_url`

### 视频字段

- `duration_ms`
- `width`
- `height`
- `cover_url`
- `play_url`

图片作品没有视频字段时保存为空，不视为错误。

### 作者字段

- `author_nickname`
- `author_account_region`
- `author_custom_verify`
- `author_enterprise_verify_reason`
- `author_follower_count`
- `author_following_count`
- `author_total_favorited`

### 统计字段

从 `statistics` 保存：

- `play_count`
- `digg_count`
- `comment_count`
- `share_count`
- `collect_count`
- `exposure_count`
- `recommend_count`

计数使用 `BigInteger`，缺失值保存为空或 0，并由提取函数统一处理。

### 扩展与原始字段

- `text_extra_json`
- `video_tag_json`
- `raw_aweme_json`
- `fetched_at`
- `created_at`
- `updated_at`

`raw_aweme_json` 只保存响应中的单个作品对象，不保存请求头、Cookie、Token、签名或顶层调试信息。

### 唯一约束

唯一键：

`tag_id + aweme_id + author_id`

重复运行时更新作品、作者、统计、扩展 JSON、来源游标和抓取时间，保留首次创建时间。

## 组件边界

### Tag URL 解析器

负责把飞书值转换为 Tag ID 和标准 URL。它是纯函数，不访问网络或数据库。

### 抖音 Tag 客户端

负责签名单页请求和全量分页，返回原始作品对象及来源游标。它不写数据库。

### Tag 提取器

负责把单个作品响应转换为稳定数据库字段。它不持有 Cookie，也不执行网络请求。

### Tag 存储

负责批量幂等写入 `douyin_tag_aweme`。它不写 `douyin_aweme`，并通过独立模型和方法保证边界。

### 运营任务桥接

负责创建浏览器、水号登录态和抖音客户端，执行 Tag 抓取并调用 Tag 存储。任务横幅在浏览器打开前显示 Tag ID、Tag 名称、水号目录和数据目标。

## 工作流

`run-all`：

1. 读取账号、链接、创作者和 Tag 四张飞书控制表。
2. 构建普通任务和 Tag 任务。
3. 依次使用对应 Profile 执行。
4. Tag 任务只写 MySQL。
5. 非 `collect-only` 模式仍可同步其他既有 Outbox；Tag 不生成 Outbox。

`collect-only`：

1. 执行同样的采集任务。
2. Tag 数据写 MySQL。
3. 不执行任何飞书写入。

## 错误处理

- 非法 Tag URL：记录飞书记录 ID和脱敏 URL，忽略该记录。
- 没有抖音水号：计划失败并返回明确错误。
- 登录失效：显示任务横幅后进入现有登录流程。
- 接口状态非成功：任务失败并保留其他独立任务继续执行。
- 空页、`null` 页、重复游标：视为当前 Tag 分页安全结束并记录原因。
- 单条作品缺少唯一标识：跳过该作品，继续同页其他作品。
- 数据库单批写入失败：回滚该批并让任务失败，不产生部分未知状态。

## 测试

单元测试覆盖：

- 标准 Hashtag URL 解析。
- 非法域名、非数字 ID 和空链接。
- 飞书 Tag 记录去重。
- 仅选择抖音水号，不选择主账号。
- Tag 单页请求参数和动态签名调用边界。
- 多页、结束页、空页、`null` 页和重复游标。
- 作者 ID 的回退顺序。
- 核心作品、作者、统计、视频和 JSON 字段提取。
- 三字段唯一键的幂等更新。
- Tag 存储不调用 `douyin_aweme` 存储。
- `run-all`、`collect-only` 与现有任务的回归行为。
- 任务横幅不泄露请求参数。

集成验证：

1. 读取 `tblEBAE044RsVURX`。
2. 使用 `D:\browser_data\dy_text_data_dir` 水号。
3. 全量抓取 Tag `7322391300177987638`。
4. 核对总页数、作品数、唯一键重复数和数据库记录数。
5. 确认 `douyin_aweme` 记录数在 Tag 任务前后不变。
6. 确认日志和 Git 差异不包含 Cookie、`msToken`、`verifyFp`、`uifid` 或 `a_bogus`。

## 验收标准

- 飞书 Tag 表被只读加载。
- 使用水号 CK，主账号不用于 Tag。
- 所有接口可见页被抓取，无固定页数上限。
- 数据只进入 `douyin_tag_aweme`。
- 唯一键为 `tag_id + aweme_id + author_id`。
- 重复运行不新增重复记录。
- 原始作品 JSON完整保存但不包含请求凭据。
- 完整测试通过。
- 改动仅推送到用户 fork 当前分支，不推送上游。
