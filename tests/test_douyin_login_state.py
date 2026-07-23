import asyncio
import sys
import types

from playwright.async_api import Page

fake_help = types.ModuleType("media_platform.douyin.help")
fake_help.Page = Page
fake_help.get_web_id = lambda: "test-web-id"
fake_help.get_a_bogus = lambda *args, **kwargs: ""
fake_help.parse_video_info_from_url = lambda value: value
fake_help.parse_creator_info_from_url = lambda value: value
sys.modules["media_platform.douyin.help"] = fake_help

from media_platform.douyin.client import DouYinClient
from media_platform.douyin.login import DouYinLogin


class FakePage:
    def __init__(self, has_user_login: str):
        self.has_user_login = has_user_login

    async def evaluate(self, _script: str):
        return {"HasUserLogin": self.has_user_login}


class FakeContext:
    def __init__(self, has_user_login: str, cookies: list[dict]):
        self.pages = [FakePage(has_user_login)]
        self._cookies = cookies

    async def cookies(self):
        return self._cookies


def make_client(has_user_login: str) -> DouYinClient:
    return DouYinClient(
        headers={},
        playwright_page=FakePage(has_user_login),
        cookie_dict={},
    )


def test_pong_rejects_stale_local_storage_without_login_cookies(monkeypatch):
    async def fake_cookies(_context, urls):
        return "", {"ttwid": "anonymous"}

    monkeypatch.setattr(
        "media_platform.douyin.client.utils.convert_browser_context_cookies",
        fake_cookies,
    )

    assert asyncio.run(make_client("1").pong(object())) is False


def test_pong_accepts_runtime_session_cookie(monkeypatch):
    async def fake_cookies(_context, urls):
        return "", {"sessionid": "available-at-runtime"}

    monkeypatch.setattr(
        "media_platform.douyin.client.utils.convert_browser_context_cookies",
        fake_cookies,
    )

    assert asyncio.run(make_client("0").pong(object())) is True


def test_login_check_rejects_stale_local_storage_without_session_cookie():
    login = object.__new__(DouYinLogin)
    login.browser_context = FakeContext(
        "1",
        [
            {
                "name": "ttwid",
                "value": "anonymous",
                "domain": ".douyin.com",
                "path": "/",
            }
        ],
    )

    check_once = DouYinLogin.check_login_state.__wrapped__.__wrapped__
    result = asyncio.run(check_once(login))

    assert result is False


def test_login_check_accepts_runtime_session_cookie():
    login = object.__new__(DouYinLogin)
    login.browser_context = FakeContext(
        "0",
        [
            {
                "name": "sessionid_ss",
                "value": "available-at-runtime",
                "domain": ".douyin.com",
                "path": "/",
            }
        ],
    )

    check_once = DouYinLogin.check_login_state.__wrapped__.__wrapped__
    result = asyncio.run(check_once(login))

    assert result is True
