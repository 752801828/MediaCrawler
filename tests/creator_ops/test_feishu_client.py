from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from creator_ops.config import FeishuSettings
from creator_ops.feishu.client import FeishuClient, FeishuPermissionError


@dataclass
class FakeResponse:
    status_code: int
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self):
        self.responses: list[FakeResponse] = []
        self.requests: list[dict[str, Any]] = []

    def queue(self, status_code: int, payload: dict[str, Any]) -> None:
        self.responses.append(FakeResponse(status_code, payload))

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


@pytest.fixture
def feishu_settings() -> FeishuSettings:
    return FeishuSettings(
        app_id="cli_xxx",
        app_secret="secret",
        app_token="app",
        link_table_id="link",
        link_view_id="link-view",
        user_table_id="user",
        user_view_id="user-view",
        account_table_id="account",
        account_view_id="account-view",
        xhs_stats_table_id="xhs-stats",
        douyin_stats_table_id="dy-stats",
        comment_table_id="comments",
        comment_view_id="comment-view",
        douyin_creator_table_id="dy-creator",
        xhs_creator_table_id="xhs-creator",
        history_view_id="history",
    )


def queue_token(session: FakeSession) -> None:
    session.queue(
        200,
        {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200},
    )


def test_iter_records_follows_page_token(feishu_settings: FeishuSettings):
    session = FakeSession()
    queue_token(session)
    session.queue(
        200,
        {
            "code": 0,
            "data": {
                "items": [{"record_id": "1", "fields": {}}],
                "has_more": True,
                "page_token": "next",
            },
        },
    )
    session.queue(
        200,
        {
            "code": 0,
            "data": {
                "items": [{"record_id": "2", "fields": {}}],
                "has_more": False,
            },
        },
    )
    client = FeishuClient(feishu_settings, session=session, sleeper=lambda _: None)

    records = client.iter_records("app", "table", "view")

    assert [item["record_id"] for item in records] == ["1", "2"]
    assert session.requests[2]["params"]["page_token"] == "next"


def test_retryable_rate_limit_uses_backoff(feishu_settings: FeishuSettings):
    session = FakeSession()
    queue_token(session)
    session.queue(429, {"code": 99991400, "msg": "rate limited"})
    session.queue(
        200,
        {"code": 0, "data": {"items": [], "has_more": False}},
    )
    delays: list[float] = []
    client = FeishuClient(feishu_settings, session=session, sleeper=delays.append)

    assert client.iter_records("app", "table", "view") == []
    assert delays == [1.0]


def test_permission_error_is_not_retried(feishu_settings: FeishuSettings):
    session = FakeSession()
    queue_token(session)
    session.queue(403, {"code": 99991672, "msg": "forbidden"})
    client = FeishuClient(feishu_settings, session=session, sleeper=lambda _: None)

    with pytest.raises(FeishuPermissionError, match="permission denied"):
        client.iter_records("app", "table", "view")

    assert len(session.requests) == 2
    assert "tenant-token" not in str(session.requests[-1].get("url"))


def test_batch_create_splits_records_at_500(feishu_settings: FeishuSettings):
    session = FakeSession()
    queue_token(session)
    session.queue(200, {"code": 0, "data": {"records": []}})
    session.queue(200, {"code": 0, "data": {"records": []}})
    client = FeishuClient(feishu_settings, session=session, sleeper=lambda _: None)

    client.batch_create_records("app", "table", [{"id": str(i)} for i in range(501)])

    writes = session.requests[1:]
    assert [len(item["json"]["records"]) for item in writes] == [500, 1]
