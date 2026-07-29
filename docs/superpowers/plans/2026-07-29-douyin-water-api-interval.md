# Douyin Water API Comment Interval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将抖音 `water_api` 评论翻页间隔调整为 1 秒，同时保持作品串行执行，并且不影响 `legacy` 或其他平台。

**Architecture:** 在全局配置中增加仅供抖音 `water_api` 使用的间隔值，`DouYinCrawler.batch_get_note_comments_api_first()` 创建 Fetcher 时读取该值。旧模式继续通过 `get_comments()` 读取全局 `CRAWLER_MAX_SLEEP_SEC`，因此行为保持不变。

**Tech Stack:** Python 3.11、asyncio、pytest、pytest-asyncio

---

### Task 1: 为 Water API 增加专用间隔

**Files:**
- Modify: `tests/test_douyin_comment_fetch_mode.py`
- Modify: `config/base_config.py:114-120`
- Modify: `media_platform/douyin/core.py:294-306`

- [ ] **Step 1: 编写失败测试**

在 `tests/test_douyin_comment_fetch_mode.py` 增加：

```python
@pytest.mark.asyncio
async def test_water_api_uses_dedicated_one_second_interval(monkeypatch):
    observed = []

    class FakeFetcher:
        def __init__(self, **kwargs):
            observed.append(kwargs["crawl_interval"])

        async def fetch(self, _aweme_id):
            return None

    monkeypatch.setattr(
        douyin_core,
        "WaterAccountCommentApiFetcher",
        FakeFetcher,
    )
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "DOUYIN_COMMENT_FETCH_MODE", "water_api")
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 2)
    monkeypatch.setattr(
        config,
        "DOUYIN_WATER_API_CRAWL_INTERVAL_SEC",
        1,
        raising=False,
    )
    crawler = DouYinCrawler()
    crawler.dy_client = object()
    crawler.browser_context = object()
    crawler.context_page = object()

    await crawler.batch_get_note_comments(["aweme-1"])

    assert observed == [1]
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_douyin_comment_fetch_mode.py::test_water_api_uses_dedicated_one_second_interval -q --basetemp C:\tmp\pytest-douyin-water-interval-red
```

Expected: `FAIL`，实际捕获值为 `2`，期望值为 `1`。

- [ ] **Step 3: 增加最小实现**

在 `config/base_config.py` 的抖音评论通道配置旁增加：

```python
# Request interval used only by Douyin water-account comment API mode.
DOUYIN_WATER_API_CRAWL_INTERVAL_SEC = 1
```

在 `media_platform/douyin/core.py` 创建 `WaterAccountCommentApiFetcher` 时改为：

```python
crawl_interval=config.DOUYIN_WATER_API_CRAWL_INTERVAL_SEC,
```

不要修改 `batch_get_note_comments_legacy()`、`get_comments()` 或 `MAX_CONCURRENCY_NUM`。

- [ ] **Step 4: 运行目标测试并确认通过**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_douyin_comment_fetch_mode.py tests\test_douyin_water_comment_api.py -q --basetemp C:\tmp\pytest-douyin-water-interval-green
```

Expected: 所有目标测试通过。

- [ ] **Step 5: 提交功能修改**

```powershell
git add config/base_config.py media_platform/douyin/core.py tests/test_douyin_comment_fetch_mode.py
git commit -m "perf: reduce douyin water comment interval"
```

### Task 2: 全量验证并发布到用户 Fork

**Files:**
- Verify: `config/base_config.py`
- Verify: `media_platform/douyin/core.py`
- Verify: `tests/test_douyin_comment_fetch_mode.py`

- [ ] **Step 1: 运行完整测试集**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp C:\tmp\pytest-douyin-water-interval-full
```

Expected: 完整测试集通过，无新增失败。

- [ ] **Step 2: 检查最终差异**

Run:

```powershell
git diff --check HEAD~1 HEAD
git status --short --branch
```

Expected: 无空白错误，工作区干净，仅包含预期提交。

- [ ] **Step 3: 推送当前分支到用户 Fork**

Run:

```powershell
git -c http.version=HTTP/1.1 push fork codex/creator-ops-migration
```

Expected: 推送到 `https://github.com/752801828/MediaCrawler.git` 成功；不向上游 `origin` 推送。
