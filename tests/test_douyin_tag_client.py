from types import SimpleNamespace

import pytest

from media_platform.douyin.client import DouYinClient
from media_platform.douyin.exception import DataFetchError


@pytest.mark.asyncio
async def test_tag_page_uses_hj_host_and_matching_cursor_offset():
    captured = {}

    async def process(uri, params, headers, request_method="GET"):
        captured["uri"] = uri
        captured["processed_params"] = dict(params)

    async def request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs["params"]
        captured["headers"] = kwargs["headers"]
        return {"status_code": 0, "aweme_list": []}

    client = SimpleNamespace(
        headers={"User-Agent": "test", "Host": "www.douyin.com"},
        request=request,
    )
    setattr(client, "_DouYinClient__process_req_params", process)

    await DouYinClient.get_tag_aweme_page(
        client,
        tag_id="7322391300177987638",
        tag_url="https://www.douyin.com/hashtag/7322391300177987638",
        cursor=24,
        count=12,
    )

    assert captured["uri"] == "/aweme/v1/web/challenge/aweme/"
    assert captured["url"].startswith("https://www-hj.douyin.com/")
    assert captured["params"]["ch_id"] == "7322391300177987638"
    assert captured["params"]["cursor"] == 24
    assert captured["params"]["offset"] == 24
    assert captured["headers"]["Host"] == "www-hj.douyin.com"
    assert captured["headers"]["Referer"].endswith("/7322391300177987638")


@pytest.mark.asyncio
async def test_tag_pagination_walks_until_has_more_is_false():
    calls = []
    responses = [
        {
            "status_code": 0,
            "has_more": 1,
            "cursor": 12,
            "aweme_list": [{"aweme_id": "1"}],
        },
        {
            "status_code": 0,
            "has_more": 0,
            "cursor": 24,
            "aweme_list": [{"aweme_id": "2"}],
        },
    ]

    async def get_page(**kwargs):
        calls.append(kwargs["cursor"])
        return responses.pop(0)

    client = SimpleNamespace(get_tag_aweme_page=get_page)
    items = await DouYinClient.get_tag_all_awemes(
        client,
        tag_id="tag",
        tag_url="https://www.douyin.com/hashtag/tag",
        crawl_interval=0,
    )

    assert calls == [0, 12]
    assert [(cursor, item["aweme_id"]) for cursor, item in items] == [
        (0, "1"),
        (12, "2"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("aweme_list", [[], None])
async def test_tag_pagination_stops_on_empty_or_null_page(aweme_list):
    calls = 0

    async def get_page(**_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("empty tag page must stop pagination")
        return {
            "status_code": 0,
            "has_more": 1,
            "cursor": 12,
            "aweme_list": aweme_list,
        }

    client = SimpleNamespace(get_tag_aweme_page=get_page)
    items = await DouYinClient.get_tag_all_awemes(
        client,
        tag_id="tag",
        tag_url="https://www.douyin.com/hashtag/tag",
        crawl_interval=0,
    )

    assert items == []
    assert calls == 1


@pytest.mark.asyncio
async def test_tag_pagination_stops_on_repeated_cursor():
    calls = 0

    async def get_page(**_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("repeated cursor must stop pagination")
        return {
            "status_code": 0,
            "has_more": 1,
            "cursor": 0,
            "aweme_list": [{"aweme_id": "1"}],
        }

    client = SimpleNamespace(get_tag_aweme_page=get_page)
    items = await DouYinClient.get_tag_all_awemes(
        client,
        tag_id="tag",
        tag_url="https://www.douyin.com/hashtag/tag",
        crawl_interval=0,
    )

    assert len(items) == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_tag_pagination_raises_nonzero_api_status():
    async def get_page(**_kwargs):
        return {"status_code": 2190008, "status_msg": "invalid", "aweme_list": []}

    client = SimpleNamespace(get_tag_aweme_page=get_page)

    with pytest.raises(DataFetchError, match="2190008"):
        await DouYinClient.get_tag_all_awemes(
            client,
            tag_id="tag",
            tag_url="https://www.douyin.com/hashtag/tag",
            crawl_interval=0,
        )
