# 全平台完整字段与无上限分页实施计划

日期：2026-07-23

关联设计：
`docs/superpowers/specs/2026-07-23-full-platform-data-restoration-design.md`

## 实施原则

- 只修改当前 `codex/creator-ops-migration` 分支。
- 只向 `752801828/MediaCrawler` 的 Fork 推送。
- 旧定制仓库只作为字段映射参考，不整文件覆盖新版实现。
- 数据库迁移只新增缺失结构，不删除或改写现有数据。
- 每个平台先补失败测试，再实现，再运行该平台测试。
- 飞书隐私过滤保持不变。
- 二级评论开关保持不变。

## 阶段 1：建立恢复字段契约

### 任务 1：定义平台完整字段测试契约

涉及文件：

- `tests/test_douyin_full_user_info.py`
- `tests/test_xhs_full_user_info.py`
- `tests/test_kuaishou_full_user_info.py`
- `tests/test_weibo_full_user_info.py`
- `tests/test_tieba_full_user_info.py`
- `tests/test_zhihu_full_user_info.py`
- `tests/test_bilibili_full_user_info.py`

工作：

1. 从现有 `no_user_info` fixture 和旧定制仓库字段映射中提取最小代表样例。
2. 断言内容、评论和创作者对象保留原始用户 ID、昵称以及平台实际提供的头像、签名、IP、性别等字段。
3. 断言 `creator_hash` 可继续存在，但原始 ID 和原始昵称不可被替代。
4. 删除或改写与新需求相反的脱敏断言。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_*_full_user_info.py -q
```

首次运行应因模型或映射缺失而失败。

## 阶段 2：恢复 ORM 与数据库升级

### 任务 2：恢复内容和评论 ORM 原始字段

涉及文件：

- `database/models.py`
- 各平台完整字段测试

工作：

1. 为 7 个平台的内容和评论 ORM 恢复原始身份及资料字段。
2. 沿用旧数据库列名，避免同义重复列。
3. 保留新版已经增加的媒体 URL、`creator_hash` 和其他业务字段。
4. 为常用原始用户 ID 增加普通索引，不创建破坏现有数据的唯一约束。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_*_full_user_info.py -q
```

### 任务 3：恢复创作者 ORM 模型

涉及文件：

- `database/models.py`
- `database/__init__.py`（如模型导出需要）
- 创作者测试

工作：

1. 恢复抖音、小红书、快手、微博、贴吧、知乎的 creator 模型。
2. 恢复 B 站 UP 主及采集流程实际需要的资料模型。
3. 以原始用户 ID 建立索引；更新逻辑负责去重，不在未知旧数据上强加唯一约束。
4. 兼容现有 creator history 表，不自动回填历史数据。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_*_full_user_info.py tests\creator_ops -q
```

### 任务 4：增加幂等结构升级器

涉及文件：

- `database/schema_migrations.py`
- `database/db.py`
- `tests/test_schema_migrations.py`

工作：

1. 使用 SQLAlchemy inspector 获取现有表、列和索引。
2. MySQL 和 SQLite 分别生成兼容的只增不删变更。
3. 新建数据库仍由完整 ORM `create_all()` 创建。
4. 已存在数据库在抓取前补齐缺失列和 creator 表。
5. 重复运行不产生额外变更。
6. 结构升级失败时终止初始化并保留原始异常。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_schema_migrations.py -q
```

## 阶段 3：恢复平台字段映射与创作者写入

### 任务 5：恢复抖音

涉及文件：

- `store/douyin/__init__.py`
- `store/douyin/_store_impl.py`
- `tests/test_douyin_full_user_info.py`

工作：

1. 内容恢复 `user_id`、`sec_uid`、`short_user_id`、`user_unique_id`、原始昵称、头像、签名和 IP。
2. 评论恢复同类字段，并兼容多个头像尺寸。
3. 恢复 `save_creator()` 规范化映射。
4. MySQL/SQLite creator 存储按 `user_id` 更新。
5. CSV/JSON/JSONL/MongoDB/Excel 接收完整字典。
6. 不删除新版封面、视频、音乐和图集 URL 字段。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_douyin_full_user_info.py tests\test_douyin_login_state.py -q
```

### 任务 6：恢复小红书

涉及文件：

- `store/xhs/__init__.py`
- `store/xhs/_store_impl.py`
- `tests/test_xhs_full_user_info.py`

工作：

1. 笔记和评论恢复原始用户 ID、昵称、头像、IP。
2. 恢复 creator 的昵称、性别、头像、简介、IP、关注、粉丝、互动和标签。
3. 保留新版 `xsec_token`、媒体 URL 和内容字段。
4. creator history 只处理未来正常采集。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_xhs_full_user_info.py -q
```

### 任务 7：恢复快手与微博

涉及文件：

- `store/kuaishou/__init__.py`
- `store/kuaishou/_store_impl.py`
- `store/weibo/__init__.py`
- `store/weibo/_store_impl.py`
- `tests/test_kuaishou_full_user_info.py`
- `tests/test_weibo_full_user_info.py`

工作：

1. 快手同时兼容新版 snake_case 与旧版 camelCase 评论响应。
2. 恢复快手作品、评论和 creator 原始字段。
3. 恢复微博内容、评论和 creator 原始字段。
4. 保留微博正文清理和当前业务字段。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_kuaishou_full_user_info.py tests\test_weibo_full_user_info.py -q
```

### 任务 8：恢复贴吧与知乎

涉及文件：

- `media_platform/tieba/help.py`
- `model/m_baidu_tieba.py`
- `store/tieba/__init__.py`
- `store/tieba/_store_impl.py`
- `media_platform/zhihu/help.py`
- `model/m_zhihu.py`
- `store/zhihu/__init__.py`
- `store/zhihu/_store_impl.py`
- `tests/test_tieba_full_user_info.py`
- `tests/test_zhihu_full_user_info.py`

工作：

1. 恢复提取模型中的原始用户标识、昵称和可用资料。
2. 恢复内容、评论和 creator 存储映射。
3. 保留当前多种页面/API 解析路径。
4. 可选字段缺失时返回空值，不影响整页。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_tieba_full_user_info.py tests\test_zhihu_full_user_info.py tests\test_tieba_extractor.py -q
```

### 任务 9：恢复 B 站

涉及文件：

- `store/bilibili/__init__.py`
- `store/bilibili/_store_impl.py`
- `media_platform/bilibili/core.py`
- `tests/test_bilibili_full_user_info.py`

工作：

1. 视频、评论和动态恢复原始 UP 主或评论用户字段。
2. 恢复 UP 主资料写入。
3. 恢复采集流程确实使用的相关资料表。
4. 不破坏新版视频、评论和动态业务字段。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_bilibili_full_user_info.py -q
```

## 阶段 4：统一存储端

### 任务 10：验证所有存储后端字段一致性

涉及文件：

- `store/excel_store_base.py`
- 各平台 `_store_impl.py`
- `tests/test_full_user_info_store_parity.py`
- `tests/test_excel_store.py`

工作：

1. 检查 CSV、JSON、JSONL 是否直接输出完整平台字典。
2. 恢复 MongoDB creator 写入并按原始用户 ID 更新。
3. Excel 动态表头或新输出包含完整字段。
4. SQLite 与 MySQL 共用完整 ORM。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_full_user_info_store_parity.py tests\test_excel_store.py -q
```

## 阶段 5：取消作品和一级评论分页上限

### 任务 11：建立分页终止契约

涉及文件：

- `tests/test_unbounded_pagination.py`
- 现有平台分页测试

工作：

1. 构造超过旧上限的多页响应。
2. 断言抓取持续到 `has_more=false`。
3. 断言空页、重复游标和无进展响应安全终止。
4. 断言二级评论关闭时不请求二级接口。

### 任务 12：移除通用和平台专用数量截断

涉及文件：

- `config/base_config.py`
- 各平台 config
- `cmd_arg/arg.py`
- `api/schemas.py`
- `api/services/crawler_manager.py`
- 各平台 `core.py` 和 `client.py`

工作：

1. 分页循环不再读取作品和一级评论数量上限。
2. 保留旧参数解析一个兼容周期并输出弃用提示。
3. 保留抓取间隔、并发和代理配置。
4. 二级评论开关不变。
5. 逐平台加入已访问游标集合及空页退出。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\test_unbounded_pagination.py tests\test_api_limits.py -q
```

## 阶段 6：飞书边界和回归

### 任务 13：确认飞书仍过滤个人字段

涉及文件：

- `creator_ops/sync.py`
- `creator_ops/feishu/schema.py`
- `tests/creator_ops/test_sync_runner.py`

工作：

1. 不修改本地完整字段。
2. 保持飞书 payload 过滤。
3. 增加“本地完整、飞书受限”的回归断言。

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests\creator_ops\test_sync_runner.py -q
```

### 任务 14：全量自动化验证

验证：

```cmd
.venv\Scripts\python.exe -m pytest tests -q
git diff --check
```

如全量测试受外部依赖影响，记录失败分类，并确保本次修改相关测试全部通过。

## 阶段 7：真实数据库和抖音验收

### 任务 15：目标 MySQL 只增不删升级

工作：

1. 读取并记录升级前表、列和行数摘要。
2. 执行幂等升级器。
3. 再次运行升级器确认无变化。
4. 核对没有删除表、列或现有记录。

### 任务 16：单作品抖音验收

工作：

1. 选择评论数超过 10 的一个已授权抖音作品。
2. 只运行抖音详情和一级评论。
3. 不运行小红书、创作者后台或飞书同步。
4. 核对实际评论数超过旧上限。
5. 核对原始昵称、用户 ID及接口实际返回的头像、签名和 IP 字段。

## 阶段 8：交付

### 任务 17：提交和推送

工作：

1. 检查工作区只有本次范围内修改。
2. 按逻辑拆分提交。
3. 确认 `origin` 推送仍为 `DISABLED`。
4. 只推送到 `fork/codex/creator-ops-migration`。
5. 核对远端 SHA，现有 PR 自动更新。
