from __future__ import annotations

import pytest

import config
from media_platform.douyin import core as douyin_core
from media_platform.douyin.core import DouYinCrawler


@pytest.mark.asyncio
async def test_water_api_mode_falls_back_only_for_failed_aweme(monkeypatch):
    attempts = []
    legacy_calls = []

    class FakeFetcher:
        def __init__(self, **_kwargs):
            return None

        async def fetch(self, aweme_id):
            attempts.append(aweme_id)
            if aweme_id == "aweme-fails":
                raise RuntimeError("blocked")

    async def legacy(aweme_id, _semaphore, **_kwargs):
        legacy_calls.append(aweme_id)

    monkeypatch.setattr(
        douyin_core,
        "WaterAccountCommentApiFetcher",
        FakeFetcher,
    )
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(
        config,
        "DOUYIN_COMMENT_FETCH_MODE",
        "water_api",
    )
    crawler = DouYinCrawler()
    crawler.dy_client = object()
    crawler.browser_context = object()
    crawler.context_page = object()
    monkeypatch.setattr(crawler, "get_comments", legacy)

    await crawler.batch_get_note_comments(
        ["aweme-fails", "aweme-succeeds"]
    )

    assert attempts == ["aweme-fails", "aweme-succeeds"]
    assert legacy_calls == ["aweme-fails"]


@pytest.mark.asyncio
async def test_water_and_legacy_failures_are_reported_after_other_awemes(
    monkeypatch,
):
    attempts = []
    legacy_calls = []

    class FakeFetcher:
        def __init__(self, **_kwargs):
            return None

        async def fetch(self, aweme_id):
            attempts.append(aweme_id)
            if aweme_id == "aweme-fails":
                raise RuntimeError("blocked")

    async def legacy(aweme_id, _semaphore, **_kwargs):
        legacy_calls.append(aweme_id)
        raise RuntimeError("legacy blocked")

    monkeypatch.setattr(
        douyin_core,
        "WaterAccountCommentApiFetcher",
        FakeFetcher,
    )
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(
        config,
        "DOUYIN_COMMENT_FETCH_MODE",
        "water_api",
    )
    crawler = DouYinCrawler()
    crawler.dy_client = object()
    crawler.browser_context = object()
    crawler.context_page = object()
    monkeypatch.setattr(crawler, "get_comments", legacy)

    with pytest.raises(
        douyin_core.DataFetchError,
        match="aweme-fails",
    ):
        await crawler.batch_get_note_comments(
            ["aweme-fails", "aweme-succeeds"]
        )

    assert attempts == ["aweme-fails", "aweme-succeeds"]
    assert legacy_calls == ["aweme-fails"]


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


@pytest.mark.asyncio
async def test_legacy_mode_keeps_original_comment_path(monkeypatch):
    legacy_calls = []

    async def legacy(aweme_id, _semaphore):
        legacy_calls.append(aweme_id)

    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "DOUYIN_COMMENT_FETCH_MODE", "legacy")
    monkeypatch.setattr(config, "MAX_CONCURRENCY_NUM", 1)
    crawler = DouYinCrawler()
    monkeypatch.setattr(crawler, "get_comments", legacy)

    await crawler.batch_get_note_comments(["aweme-1", "aweme-2"])

    assert legacy_calls == ["aweme-1", "aweme-2"]
