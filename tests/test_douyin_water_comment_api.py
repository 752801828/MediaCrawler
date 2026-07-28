from __future__ import annotations

from collections import defaultdict

import pytest

from media_platform.douyin.comment_api import (
    WaterAccountCommentApiFetcher,
)
from media_platform.douyin.exception import DataFetchError


class FakePage:
    def __init__(self):
        self.goto_urls = []
        self.reloads = 0

    async def goto(self, url, **_kwargs):
        self.goto_urls.append(url)

    async def reload(self, **_kwargs):
        self.reloads += 1

    def is_closed(self):
        return False


class FakeClient:
    def __init__(self, root_responses, reply_responses=None):
        self.root_responses = list(root_responses)
        self.reply_responses = {
            key: list(value)
            for key, value in (reply_responses or {}).items()
        }
        self.root_calls = []
        self.reply_calls = []
        self.cookie_updates = 0
        self.logged_in = True

    async def pong(self, _browser_context):
        return self.logged_in

    async def update_cookies(self, _browser_context):
        self.cookie_updates += 1

    async def get_aweme_comments(self, aweme_id, cursor):
        self.root_calls.append((aweme_id, cursor))
        response = self.root_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def get_sub_comments(self, aweme_id, comment_id, cursor):
        self.reply_calls.append((aweme_id, comment_id, cursor))
        response = self.reply_responses[comment_id].pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_water_api_fetches_all_root_and_reply_pages():
    client = FakeClient(
        root_responses=[
            {
                "has_more": 1,
                "cursor": 20,
                "comments": [
                    {"cid": "root-1", "reply_comment_total": 2},
                ],
            },
            {
                "has_more": 0,
                "cursor": 40,
                "comments": [
                    {"cid": "root-2", "reply_comment_total": 0},
                ],
            },
        ],
        reply_responses={
            "root-1": [
                {
                    "has_more": 1,
                    "cursor": 10,
                    "comments": [{"cid": "reply-1"}],
                },
                {
                    "has_more": 0,
                    "cursor": 20,
                    "comments": [{"cid": "reply-2"}],
                },
            ]
        },
    )
    page = FakePage()
    batches = defaultdict(list)

    async def callback(aweme_id, comments):
        batches[aweme_id].extend(comments)

    fetcher = WaterAccountCommentApiFetcher(
        client=client,
        browser_context=object(),
        page=page,
        callback=callback,
        crawl_interval=0,
        fetch_sub_comments=True,
    )
    stats = await fetcher.fetch("aweme-1")

    assert stats.root_pages == 2
    assert stats.root_comments == 2
    assert stats.reply_pages == 2
    assert stats.reply_comments == 2
    assert stats.total_comments == 4
    assert client.root_calls == [("aweme-1", 0), ("aweme-1", 20)]
    assert client.reply_calls == [
        ("aweme-1", "root-1", 0),
        ("aweme-1", "root-1", 10),
    ]
    assert page.goto_urls == ["https://www.douyin.com/video/aweme-1"]
    assert client.cookie_updates == 1
    assert [
        (row["cid"], row["_parent_comment_id"])
        for row in batches["aweme-1"]
    ] == [
        ("root-1", ""),
        ("reply-1", "root-1"),
        ("reply-2", "root-1"),
        ("root-2", ""),
    ]


@pytest.mark.asyncio
async def test_water_api_refreshes_session_and_retries_without_logging_secrets():
    client = FakeClient(
        root_responses=[
            DataFetchError("blocked"),
            {
                "has_more": 0,
                "cursor": 20,
                "comments": [{"cid": "root-1"}],
            },
        ]
    )
    page = FakePage()
    captured = []

    async def callback(_aweme_id, comments):
        captured.extend(comments)

    fetcher = WaterAccountCommentApiFetcher(
        client=client,
        browser_context=object(),
        page=page,
        callback=callback,
        crawl_interval=0,
        fetch_sub_comments=False,
        max_attempts=2,
    )
    stats = await fetcher.fetch("aweme-1")

    assert stats.root_comments == 1
    assert page.reloads == 1
    assert client.cookie_updates == 2
    assert captured[0]["cid"] == "root-1"


@pytest.mark.asyncio
async def test_water_api_stops_on_repeated_cursor():
    client = FakeClient(
        root_responses=[
            {
                "has_more": 1,
                "cursor": 0,
                "comments": [{"cid": "root-1"}],
            }
        ]
    )

    async def callback(_aweme_id, _comments):
        return None

    fetcher = WaterAccountCommentApiFetcher(
        client=client,
        browser_context=object(),
        page=FakePage(),
        callback=callback,
        crawl_interval=0,
        fetch_sub_comments=False,
    )
    stats = await fetcher.fetch("aweme-1")

    assert stats.root_pages == 1
    assert stats.root_comments == 1
    assert client.root_calls == [("aweme-1", 0)]


@pytest.mark.asyncio
async def test_water_api_rejects_invalid_comment_shape_after_retries():
    client = FakeClient(
        root_responses=[
            {"has_more": 1, "cursor": 20, "comments": "blocked"},
        ]
    )

    async def callback(_aweme_id, _comments):
        return None

    fetcher = WaterAccountCommentApiFetcher(
        client=client,
        browser_context=object(),
        page=FakePage(),
        callback=callback,
        crawl_interval=0,
        fetch_sub_comments=False,
        max_attempts=1,
    )
    with pytest.raises(DataFetchError, match="invalid comments type"):
        await fetcher.fetch("aweme-1")


@pytest.mark.asyncio
async def test_water_api_requires_logged_in_water_profile():
    client = FakeClient(root_responses=[])
    client.logged_in = False

    async def callback(_aweme_id, _comments):
        return None

    fetcher = WaterAccountCommentApiFetcher(
        client=client,
        browser_context=object(),
        page=FakePage(),
        callback=callback,
        crawl_interval=0,
        fetch_sub_comments=False,
    )
    with pytest.raises(DataFetchError, match="not logged in"):
        await fetcher.fetch("aweme-1")


@pytest.mark.asyncio
async def test_water_api_does_not_repeat_client_exhausted_network_retries():
    client = FakeClient(
        root_responses=[
            DataFetchError("Douyin request failed after 3 attempts"),
        ]
    )
    page = FakePage()

    async def callback(_aweme_id, _comments):
        return None

    fetcher = WaterAccountCommentApiFetcher(
        client=client,
        browser_context=object(),
        page=page,
        callback=callback,
        crawl_interval=0,
        fetch_sub_comments=False,
        max_attempts=3,
    )
    with pytest.raises(DataFetchError, match="failed after 1 attempts"):
        await fetcher.fetch("aweme-1")

    assert client.root_calls == [("aweme-1", 0)]
    assert page.reloads == 0
