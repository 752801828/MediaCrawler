# -*- coding: utf-8 -*-

from types import SimpleNamespace

import pytest

import config
from media_platform.bilibili.client import BilibiliClient
from media_platform.douyin.client import DouYinClient
from media_platform.kuaishou.client import KuaiShouClient
from media_platform.weibo.client import WeiboClient
from media_platform.xhs.client import XiaoHongShuClient


async def _no_sub_comments(*args, **kwargs):
    return []


@pytest.mark.asyncio
async def test_douyin_ignores_legacy_comment_limit_and_walks_to_end():
    responses = [
        {"has_more": 1, "cursor": 20, "comments": [{"cid": "1"}, {"cid": "2"}]},
        {"has_more": 0, "cursor": 40, "comments": [{"cid": "3"}, {"cid": "4"}]},
    ]

    async def get_comments(_aweme_id, _cursor):
        return responses.pop(0)

    client = SimpleNamespace(get_aweme_comments=get_comments)
    result = await DouYinClient.get_aweme_all_comments(
        client,
        aweme_id="aweme",
        crawl_interval=0,
        is_fetch_sub_comments=False,
        max_count=1,
    )

    assert [item["cid"] for item in result] == ["1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_douyin_stops_on_repeated_cursor():
    calls = 0

    async def get_comments(_aweme_id, _cursor):
        nonlocal calls
        calls += 1
        return {"has_more": 1, "cursor": 0, "comments": [{"cid": "1"}]}

    client = SimpleNamespace(get_aweme_comments=get_comments)
    result = await DouYinClient.get_aweme_all_comments(
        client,
        aweme_id="aweme",
        crawl_interval=0,
        is_fetch_sub_comments=False,
    )

    assert calls == 1
    assert len(result) == 1


@pytest.mark.asyncio
async def test_douyin_walks_all_sub_comment_pages():
    sub_responses = [
        {"has_more": 1, "cursor": 10, "comments": [{"cid": "sub-1"}]},
        {"has_more": 0, "cursor": 20, "comments": [{"cid": "sub-2"}]},
    ]
    callback_batches = []

    async def get_comments(_aweme_id, _cursor):
        return {
            "has_more": 0,
            "cursor": 20,
            "comments": [{"cid": "root", "reply_comment_total": 2}],
        }

    async def get_sub_comments(_aweme_id, _comment_id, _cursor):
        return sub_responses.pop(0)

    async def callback(_aweme_id, comments):
        callback_batches.append([item["cid"] for item in comments])

    client = SimpleNamespace(
        get_aweme_comments=get_comments,
        get_sub_comments=get_sub_comments,
    )
    result = await DouYinClient.get_aweme_all_comments(
        client,
        aweme_id="aweme",
        crawl_interval=0,
        is_fetch_sub_comments=True,
        callback=callback,
    )

    assert [item["cid"] for item in result] == ["root", "sub-1", "sub-2"]
    assert callback_batches == [["root"], ["sub-1"], ["sub-2"]]


@pytest.mark.asyncio
async def test_douyin_stops_sub_comments_on_empty_page():
    sub_calls = 0

    async def get_comments(_aweme_id, _cursor):
        return {
            "has_more": 0,
            "cursor": 20,
            "comments": [{"cid": "root", "reply_comment_total": 1}],
        }

    async def get_sub_comments(_aweme_id, _comment_id, _cursor):
        nonlocal sub_calls
        sub_calls += 1
        if sub_calls > 1:
            raise AssertionError("empty sub-comment page must stop pagination")
        return {"has_more": 1, "cursor": 10, "comments": []}

    client = SimpleNamespace(
        get_aweme_comments=get_comments,
        get_sub_comments=get_sub_comments,
    )
    result = await DouYinClient.get_aweme_all_comments(
        client,
        aweme_id="aweme",
        crawl_interval=0,
        is_fetch_sub_comments=True,
    )

    assert [item["cid"] for item in result] == ["root"]
    assert sub_calls == 1


@pytest.mark.asyncio
async def test_douyin_stops_sub_comments_when_comments_are_null():
    async def get_comments(_aweme_id, _cursor):
        return {
            "has_more": 0,
            "cursor": 20,
            "comments": [{"cid": "root", "reply_comment_total": 1}],
        }

    async def get_sub_comments(_aweme_id, _comment_id, _cursor):
        return {"has_more": 1, "cursor": 10, "comments": None}

    client = SimpleNamespace(
        get_aweme_comments=get_comments,
        get_sub_comments=get_sub_comments,
    )
    result = await DouYinClient.get_aweme_all_comments(
        client,
        aweme_id="aweme",
        crawl_interval=0,
        is_fetch_sub_comments=True,
    )

    assert [item["cid"] for item in result] == ["root"]


@pytest.mark.asyncio
async def test_douyin_stops_sub_comments_on_repeated_cursor():
    sub_calls = 0

    async def get_comments(_aweme_id, _cursor):
        return {
            "has_more": 0,
            "cursor": 20,
            "comments": [{"cid": "root", "reply_comment_total": 2}],
        }

    async def get_sub_comments(_aweme_id, _comment_id, _cursor):
        nonlocal sub_calls
        sub_calls += 1
        if sub_calls > 1:
            raise AssertionError("repeated sub-comment cursor must stop pagination")
        return {"has_more": 1, "cursor": 0, "comments": [{"cid": "sub-1"}]}

    client = SimpleNamespace(
        get_aweme_comments=get_comments,
        get_sub_comments=get_sub_comments,
    )
    result = await DouYinClient.get_aweme_all_comments(
        client,
        aweme_id="aweme",
        crawl_interval=0,
        is_fetch_sub_comments=True,
    )

    assert [item["cid"] for item in result] == ["root", "sub-1"]
    assert sub_calls == 1


@pytest.mark.asyncio
async def test_xhs_ignores_legacy_comment_limit_and_walks_to_end():
    responses = [
        {"has_more": True, "cursor": "next", "comments": [{"id": "1"}, {"id": "2"}]},
        {"has_more": False, "cursor": "end", "comments": [{"id": "3"}, {"id": "4"}]},
    ]

    async def get_comments(**_kwargs):
        return responses.pop(0)

    client = SimpleNamespace(
        get_note_comments=get_comments,
        get_comments_all_sub_comments=_no_sub_comments,
    )
    result = await XiaoHongShuClient.get_note_all_comments(
        client,
        note_id="note",
        xsec_token="token",
        crawl_interval=0,
        max_count=1,
    )

    assert [item["id"] for item in result] == ["1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_xhs_walks_all_sub_comment_pages(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)
    responses = [
        {"has_more": True, "cursor": "next", "comments": [{"id": "sub-1"}]},
        {"has_more": False, "cursor": "end", "comments": [{"id": "sub-2"}]},
    ]
    callback_batches = []

    async def get_sub_comments(**_kwargs):
        return responses.pop(0)

    async def callback(_note_id, comments):
        callback_batches.append([item["id"] for item in comments])

    client = SimpleNamespace(get_note_sub_comments=get_sub_comments)
    result = await XiaoHongShuClient.get_comments_all_sub_comments(
        client,
        comments=[
            {
                "id": "root",
                "note_id": "note",
                "sub_comments": [{"id": "embedded"}],
                "sub_comment_has_more": True,
                "sub_comment_cursor": "start",
            }
        ],
        xsec_token="token",
        crawl_interval=0,
        callback=callback,
    )

    assert [item["id"] for item in result] == ["sub-1", "sub-2"]
    assert callback_batches == [["embedded"], ["sub-1"], ["sub-2"]]


@pytest.mark.asyncio
async def test_xhs_stops_sub_comments_on_empty_page(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)
    calls = 0

    async def get_sub_comments(**_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("empty sub-comment page must stop pagination")
        return {"has_more": True, "cursor": "next", "comments": []}

    client = SimpleNamespace(get_note_sub_comments=get_sub_comments)
    result = await XiaoHongShuClient.get_comments_all_sub_comments(
        client,
        comments=[
            {
                "id": "root",
                "note_id": "note",
                "sub_comments": [],
                "sub_comment_has_more": True,
                "sub_comment_cursor": "start",
            }
        ],
        xsec_token="token",
        crawl_interval=0,
    )

    assert result == []
    assert calls == 1


@pytest.mark.asyncio
async def test_xhs_stops_sub_comments_when_comments_are_null(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)

    async def get_sub_comments(**_kwargs):
        return {"has_more": True, "cursor": "next", "comments": None}

    client = SimpleNamespace(get_note_sub_comments=get_sub_comments)
    result = await XiaoHongShuClient.get_comments_all_sub_comments(
        client,
        comments=[
            {
                "id": "root",
                "note_id": "note",
                "sub_comments": [],
                "sub_comment_has_more": True,
                "sub_comment_cursor": "start",
            }
        ],
        xsec_token="token",
        crawl_interval=0,
    )

    assert result == []


@pytest.mark.asyncio
async def test_xhs_stops_sub_comments_on_repeated_cursor(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)
    calls = 0

    async def get_sub_comments(**_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("repeated sub-comment cursor must stop pagination")
        return {
            "has_more": True,
            "cursor": "start",
            "comments": [{"id": "sub-1"}],
        }

    client = SimpleNamespace(get_note_sub_comments=get_sub_comments)
    result = await XiaoHongShuClient.get_comments_all_sub_comments(
        client,
        comments=[
            {
                "id": "root",
                "note_id": "note",
                "sub_comments": [],
                "sub_comment_has_more": True,
                "sub_comment_cursor": "start",
            }
        ],
        xsec_token="token",
        crawl_interval=0,
    )

    assert [item["id"] for item in result] == ["sub-1"]
    assert calls == 1


@pytest.mark.asyncio
async def test_kuaishou_ignores_legacy_comment_limit_and_walks_to_end():
    responses = [
        {"pcursorV2": "next", "rootCommentsV2": [{"commentId": "1"}, {"commentId": "2"}]},
        {"pcursorV2": "no_more", "rootCommentsV2": [{"commentId": "3"}, {"commentId": "4"}]},
    ]

    async def get_comments(_photo_id, _cursor):
        return responses.pop(0)

    client = SimpleNamespace(
        get_video_comments=get_comments,
        get_comments_all_sub_comments=_no_sub_comments,
    )
    result = await KuaiShouClient.get_video_all_comments(
        client,
        photo_id="photo",
        crawl_interval=0,
        max_count=1,
    )

    assert [item["commentId"] for item in result] == ["1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_weibo_ignores_legacy_comment_limit_and_walks_to_end():
    responses = [
        {"max_id": 20, "max_id_type": 0, "data": [{"id": "1"}, {"id": "2"}]},
        {"max_id": 0, "max_id_type": 0, "data": [{"id": "3"}, {"id": "4"}]},
    ]

    async def get_comments(_note_id, _max_id, _max_id_type):
        return responses.pop(0)

    client = SimpleNamespace(
        get_note_comments=get_comments,
        get_comments_all_sub_comments=_no_sub_comments,
    )
    result = await WeiboClient.get_note_all_comments(
        client,
        note_id="note",
        crawl_interval=0,
        max_count=1,
    )

    assert [item["id"] for item in result] == ["1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_bilibili_ignores_legacy_comment_limit_and_walks_to_end():
    responses = [
        {
            "cursor": {"is_end": False, "next": 20},
            "replies": [{"rpid": 1}, {"rpid": 2}],
        },
        {
            "cursor": {"is_end": True, "next": 40},
            "replies": [{"rpid": 3}, {"rpid": 4}],
        },
    ]

    async def get_comments(_video_id, _order_mode, _next_page):
        return responses.pop(0)

    client = SimpleNamespace(get_video_comments=get_comments)
    result = await BilibiliClient.get_video_all_comments(
        client,
        video_id="video",
        crawl_interval=0,
        is_fetch_sub_comments=False,
        max_count=1,
    )

    assert [item["rpid"] for item in result] == [1, 2, 3, 4]
