# 小红书与抖音二级评论抓取实施计划

## 目标

仅为小红书和抖音开启二级评论抓取，使飞书运营任务与直接运行入口行为一致，并保证异常分页不会无限循环。

## 实施原则

- 先写失败测试，再写最小实现。
- 复用现有评论表、回调和幂等存储逻辑。
- 不修改其他平台的评论行为。
- 每个阶段完成后运行聚焦测试，最后运行完整测试套件。

## 任务 1：增加平台级二级评论配置

涉及文件：

- `config/base_config.py`
- 新增 `tests/test_sub_comment_config.py`

步骤：

1. 编写测试，断言总开关开启后只有 `xhs`、`dy` 返回二级评论开启。
2. 编写测试，断言一级评论关闭时二级评论关闭。
3. 运行测试并确认因缺少统一判断而失败。
4. 增加二级评论平台白名单和统一判断函数。
5. 运行聚焦测试并确认通过。

## 任务 2：接入运营任务配置作用域和横幅

涉及文件：

- `creator_ops/crawler_bridge.py`
- `tests/creator_ops/test_crawler_bridge.py`

步骤：

1. 编写配置作用域测试，验证小红书和抖音任务开启二级评论，其他平台关闭，退出作用域后全局值恢复。
2. 编写横幅测试，验证两个目标平台显示实际启用状态。
3. 运行测试并确认失败。
4. 将二级评论相关配置纳入作用域保存与恢复。
5. 横幅改用统一判断函数。
6. 运行聚焦测试并确认通过。

## 任务 3：加固抖音二级评论分页

涉及文件：

- `media_platform/douyin/client.py`
- `tests/test_unbounded_pagination.py`

步骤：

1. 编写二级评论多页抓取测试。
2. 编写二级评论空页且 `has_more` 为真时结束的测试。
3. 编写二级评论游标重复时结束的测试。
4. 运行测试并确认异常场景失败或卡住。
5. 为每个根评论维护独立的已访问游标集合。
6. 空页立即结束当前根评论分页；重复游标记录警告并结束。
7. 增加带作品 ID、根评论 ID、游标和数量的进度日志。
8. 运行聚焦测试并确认通过。

## 任务 4：加固小红书二级评论分页

涉及文件：

- `media_platform/xhs/client.py`
- `tests/test_unbounded_pagination.py`

步骤：

1. 编写内嵌二级评论与后续分页都进入回调的测试。
2. 编写空页结束测试。
3. 编写重复游标结束测试。
4. 运行测试并确认异常场景失败。
5. 为每个根评论维护独立的已访问游标集合。
6. 空页立即结束；重复游标记录警告并结束。
7. 增加带笔记 ID、根评论 ID、游标和数量的进度日志。
8. 运行聚焦测试并确认通过。

## 任务 5：回归、提交与推送

步骤：

1. 运行新增和相关测试：

   `.venv\Scripts\python.exe -m pytest tests/test_sub_comment_config.py tests/test_unbounded_pagination.py tests/creator_ops/test_crawler_bridge.py -q`

2. 运行完整测试套件：

   `.venv\Scripts\python.exe -m pytest tests -q`

3. 运行 `git diff --check`，检查工作区只包含本次范围。
4. 提交实现，提交信息：

   `feat: enable xhs and douyin sub-comment crawling`

5. 推送 `codex/creator-ops-migration` 到用户 fork `752801828/MediaCrawler`。
6. 单独执行当前抖音评论任务，查询两个作品新增的一级、二级评论数及父评论字段覆盖情况。

## 验收

- `xhs` 和 `dy` 的二级评论判断为开启，其他平台为关闭。
- 两个平台异常分页均能安全结束。
- 飞书任务横幅显示正确状态。
- 新增测试和完整测试通过。
- 实现只推送到用户 fork。
