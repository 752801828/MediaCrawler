# 抖音 Tag 数据采集实施计划

## 目标

从飞书表 `tblEBAE044RsVURX` 读取 Tag 链接，使用抖音水号 CK 全量分页抓取作品，并仅幂等写入新表 `douyin_tag_aweme`。

## 实施原则

- 先写失败测试，再写最小实现。
- URL 解析、响应提取、分页、存储和任务编排保持独立。
- 不保存请求 Cookie、Token 或签名。
- 不调用现有 `douyin_aweme` 存储。
- 每阶段运行聚焦测试，最后运行完整测试和真实抓取。

## 任务 1：配置、领域对象和 Tag URL 解析

涉及文件：

- `creator_ops/config.py`
- `creator_ops/domain.py`
- 新增 `creator_ops/douyin_tags.py`
- `tests/creator_ops/test_config.py`
- 新增 `tests/creator_ops/test_douyin_tags.py`

步骤：

1. 为 `FEISHU_DOUYIN_TAG_TABLE_ID` 编写配置默认值和显式覆盖测试。
2. 为标准 Hashtag URL、查询参数 URL、非法域名、非数字 ID 和空值编写解析测试。
3. 新增 `TaskKind.DOUYIN_TAG_CONTENT` 和不可变的 Tag 目标数据结构。
4. 实现纯函数 URL 解析器。
5. 运行聚焦测试。

## 任务 2：飞书 Tag 记录进入任务计划

涉及文件：

- `creator_ops/planner.py`
- `tests/creator_ops/test_planner.py`

步骤：

1. 扩展 `build_plan` 输入，接收 Tag 记录。
2. 编写测试，验证读取 `tag`、`链接`，按 Tag ID 去重。
3. 编写测试，验证只使用抖音水号，绝不回退主账号。
4. 编写多个水号轮换测试。
5. 实现 Tag 任务规划。
6. 更新现有调用测试并运行聚焦测试。

## 任务 3：Tag 响应提取与数据库模型

涉及文件：

- `creator_ops/storage/models.py`
- 新增 `creator_ops/storage/douyin_tag_repository.py`
- `creator_ops/storage/__init__.py`
- `creator_ops/douyin_tags.py`
- 新增 `tests/creator_ops/test_douyin_tag_storage.py`

步骤：

1. 编写作者 ID 回退顺序测试。
2. 编写作品、视频、作者、统计和 JSON 字段提取测试。
3. 新增 `DouyinTagAweme` 模型和三字段唯一约束。
4. 使用 `BigInteger` 保存计数，使用 `Text` 保存 URL 和 JSON。
5. 编写 SQLite 集成测试，验证重复唯一键更新而不新增。
6. 实现独立 Tag Repository，确保不依赖 `store.douyin.update_douyin_aweme`。
7. 运行模型、迁移和存储测试。

## 任务 4：抖音 Tag 客户端与全量分页

涉及文件：

- `media_platform/douyin/client.py`
- `tests/test_unbounded_pagination.py`
- 新增 `tests/test_douyin_tag_client.py`

步骤：

1. 编写单页业务参数、主机和 Referer 测试。
2. 编写多页抓取测试，验证响应游标同时传入下一页的 `cursor`、`offset`。
3. 编写 `has_more=false`、空页、`null` 页和重复游标测试。
4. 编写接口错误向上抛出测试。
5. 实现单页请求和异步全量迭代接口。
6. 日志只输出 Tag ID、游标和数量。
7. 运行聚焦测试。

## 任务 5：水号浏览器任务桥接

涉及文件：

- `creator_ops/crawler_bridge.py`
- `tests/creator_ops/test_crawler_bridge.py`

步骤：

1. 编写 Tag 横幅测试，验证显示 Tag、ID、水号目录和目标表。
2. 编写测试，验证浏览器打开前输出横幅。
3. 编写测试，验证 Tag 任务只调用独立 Tag Repository。
4. 复用标准 Playwright 水号 Profile、登录检测和客户端 Cookie 更新逻辑。
5. 执行全量分页，并按页批量幂等写入新表。
6. 可靠关闭浏览器及数据库资源。
7. 运行聚焦测试。

## 任务 6：接入 `run-all` 与 `collect-only`

涉及文件：

- `creator_ops/runner.py`
- `creator_ops/cli.py`
- `tests/creator_ops/test_sync_runner.py`
- `tests/creator_ops/test_cli.py`

步骤：

1. 读取第四张 Tag 控制表。
2. 将 Tag 记录传入 Planner。
3. 为 Tag 任务调用专用任务执行器。
4. 验证 Tag 任务写 MySQL 但不创建 Outbox。
5. 验证 `collect-only` 不触发飞书写入。
6. 验证一个 Tag 失败时其他独立任务继续。
7. 运行运营模块测试。

## 任务 7：配置示例、文档和密钥扫描

涉及文件：

- `.env.example`
- `docs/creator_ops_guide.md`

步骤：

1. 增加 `FEISHU_DOUYIN_TAG_TABLE_ID=tblEBAE044RsVURX`。
2. 说明飞书字段 `tag`、`链接` 和水号要求。
3. 说明新表、唯一键、全量分页和不写 `douyin_aweme`。
4. 扫描源码和 Git 差异，确认不存在用户提供的 `msToken`、`verifyFp`、`uifid`、`a_bogus` 值或完整请求 URL。

## 任务 8：回归、提交、推送与真实验证

步骤：

1. 运行 Tag 聚焦测试。
2. 运行完整测试：

   `.venv\Scripts\python.exe -m pytest tests -q`

3. 运行 `git diff --check`。
4. 提交：

   `feat: collect douyin tag content`

5. 推送 `codex/creator-ops-migration` 到 `752801828/MediaCrawler`。
6. 记录真实抓取前：

   - `douyin_aweme` 总数；
   - `douyin_tag_aweme` 总数；
   - 目标 Tag 记录数。

7. 使用 `D:\browser_data\dy_text_data_dir` 执行 Tag `7322391300177987638` 全量抓取。
8. 记录页数、接口作品数、唯一作品数、缺失作者 ID 数和最终数据库记录数。
9. 再次确认 `douyin_aweme` 总数不变。
10. 重复运行并确认 `douyin_tag_aweme` 不产生重复唯一键。
11. 清理临时验证日志。

## 验收

- Tag 控制表只读加载。
- Tag 任务只使用水号。
- 分页无固定上限且异常页安全结束。
- 只写 `douyin_tag_aweme`。
- 唯一键为 `tag_id + aweme_id + author_id`。
- 核心字段和完整作品 JSON 均保存。
- 完整测试通过。
- 代码只推送到用户 fork。
