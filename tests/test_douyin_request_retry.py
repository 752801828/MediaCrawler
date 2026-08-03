from contextlib import asynccontextmanager

import httpx
import pytest

from media_platform.douyin.client import DouYinClient
from media_platform.douyin.exception import DataFetchError


class FakeResponse:
    text = '{"status_code": 0}'

    def json(self):
        return {"status_code": 0}


def make_client() -> DouYinClient:
    return DouYinClient(
        headers={},
        playwright_page=None,
        cookie_dict={},
    )


@pytest.mark.asyncio
async def test_request_retries_transient_connect_error(monkeypatch):
    attempts = 0

    class HttpClient:
        async def request(self, *_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise httpx.ConnectError("temporary")
            return FakeResponse()

    @asynccontextmanager
    async def fake_async_client(**_kwargs):
        yield HttpClient()

    async def no_proxy_refresh():
        return None

    async def no_sleep(_delay):
        return None

    client = make_client()
    monkeypatch.setattr(client, "_refresh_proxy_if_expired", no_proxy_refresh)
    monkeypatch.setattr(
        "media_platform.douyin.client.make_async_client",
        fake_async_client,
    )
    monkeypatch.setattr(
        "media_platform.douyin.client.asyncio.sleep",
        no_sleep,
    )

    assert await client.request("GET", "https://www.douyin.com/test") == {
        "status_code": 0
    }
    assert attempts == 3


@pytest.mark.asyncio
async def test_request_wraps_exhausted_connect_error(monkeypatch):
    class HttpClient:
        async def request(self, *_args, **_kwargs):
            raise httpx.ConnectError("temporary")

    @asynccontextmanager
    async def fake_async_client(**_kwargs):
        yield HttpClient()

    async def no_proxy_refresh():
        return None

    async def no_sleep(_delay):
        return None

    client = make_client()
    monkeypatch.setattr(client, "_refresh_proxy_if_expired", no_proxy_refresh)
    monkeypatch.setattr(
        "media_platform.douyin.client.make_async_client",
        fake_async_client,
    )
    monkeypatch.setattr(
        "media_platform.douyin.client.asyncio.sleep",
        no_sleep,
    )

    with pytest.raises(DataFetchError, match="after 3 attempts"):
        await client.request("GET", "https://www.douyin.com/test")
