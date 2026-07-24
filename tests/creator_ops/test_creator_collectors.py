from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from creator_ops.domain import AccountProfile, Platform
from creator_ops.platforms.base import parse_metric_number
from creator_ops.platforms.douyin_creator import (
    DouyinCreatorCollector,
    normalize_douyin_row,
    wait_for_douyin_creator_table,
)
from creator_ops.platforms.xhs_creator import XhsCreatorCollector, normalize_xhs_row


def profile(platform: Platform) -> AccountProfile:
    return AccountProfile(
        platform=platform,
        template="%s_use_data_dir",
        path=Path("D:/browser_data") / f"{platform.value}_use_data_dir",
        is_main=True,
        is_water=False,
    )


def test_parse_metric_number_handles_chinese_units_and_percentages():
    assert parse_metric_number("1.2万") == 12000
    assert parse_metric_number("3.5亿") == 350000000
    assert parse_metric_number("12.5%") == 12.5
    assert parse_metric_number("--") == 0
    assert parse_metric_number("00:13") == "00:13"


def test_normalize_xhs_row_converts_metrics_and_builds_stable_key():
    record = normalize_xhs_row(
        profile_key="%s_use_data_dir",
        row={
            "标题": "示例笔记",
            "创建时间": "2026-07-20 10:00",
            "曝光": "1.2万",
            "点赞": "23",
        },
        snapshot_date=date(2026, 7, 21),
    )

    assert record.platform is Platform.XHS
    assert record.metrics == {"曝光": 12000, "点赞": 23}
    assert record.content_key == normalize_xhs_row(
        "%s_use_data_dir",
        {"标题": "示例笔记", "创建时间": "2026-07-20 10:00"},
        date(2026, 7, 21),
    ).content_key


def test_normalize_douyin_row_converts_percentages():
    record = normalize_douyin_row(
        profile_key="%s_use_data_dir",
        row={
            "标题": "示例视频",
            "创建时间": "2026-07-20 11:30",
            "浏览": "2.5万",
            "完播率": "31.2%",
        },
        snapshot_date=date(2026, 7, 21),
    )

    assert record.platform is Platform.DOUYIN
    assert record.metrics["浏览"] == 25000
    assert record.metrics["完播率"] == 31.2


@pytest.mark.asyncio
async def test_collectors_accept_injected_row_sources():
    async def xhs_rows(_profile):
        yield [{"标题": "笔记", "创建时间": "2026-07-20", "浏览": "10"}]

    async def douyin_rows(_profile):
        yield [{"标题": "视频", "创建时间": "2026-07-20", "浏览": "20"}]

    xhs_records = await XhsCreatorCollector(row_source=xhs_rows).collect(
        profile(Platform.XHS), snapshot_date=date(2026, 7, 21)
    )
    douyin_records = await DouyinCreatorCollector(row_source=douyin_rows).collect(
        profile(Platform.DOUYIN), snapshot_date=date(2026, 7, 21)
    )

    assert [record.title for record in xhs_records] == ["笔记"]
    assert [record.title for record in douyin_records] == ["视频"]


class FakeDouyinLocator:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    @property
    def first(self):
        return self

    async def count(self):
        return 1

    async def is_visible(self):
        if self.kind == "table":
            return self.page.table_visible or (
                self.page.table_visible_after_poll is not None
                and self.page.poll_count >= self.page.table_visible_after_poll
            )
        if self.kind == "verification":
            return self.page.poll_count < self.page.verification_polls
        return True

    async def click(self, **_kwargs):
        self.page.submission_clicks += 1
        if self.page.table_after_click:
            self.page.table_visible = True


class FakeDouyinCreatorPage:
    def __init__(
        self,
        verification_polls,
        *,
        table_after_click=True,
        table_visible_after_poll=None,
    ):
        self.verification_polls = verification_polls
        self.table_after_click = table_after_click
        self.table_visible_after_poll = table_visible_after_poll
        self.poll_count = 0
        self.submission_clicks = 0
        self.table_visible = False

    def get_by_text(self, text, **_kwargs):
        kind = "verification" if text == "身份验证" else "submission"
        return FakeDouyinLocator(self, kind)

    def locator(self, _selector):
        return FakeDouyinLocator(self, "table")

    async def wait_for_timeout(self, _timeout):
        self.poll_count += 1


@pytest.mark.asyncio
async def test_douyin_creator_waits_for_verification_before_opening_table():
    page = FakeDouyinCreatorPage(verification_polls=2)

    await wait_for_douyin_creator_table(
        page,
        normal_timeout_ms=5_000,
        poll_ms=1_000,
    )

    assert page.poll_count == 3
    assert page.submission_clicks == 1


@pytest.mark.asyncio
async def test_douyin_creator_verification_wait_does_not_consume_normal_timeout():
    page = FakeDouyinCreatorPage(verification_polls=5)

    await wait_for_douyin_creator_table(
        page,
        normal_timeout_ms=2_000,
        poll_ms=1_000,
    )

    assert page.poll_count == 6
    assert page.submission_clicks == 1


@pytest.mark.asyncio
async def test_douyin_creator_keeps_waiting_after_verification_title_disappears():
    page = FakeDouyinCreatorPage(
        verification_polls=1,
        table_after_click=False,
        table_visible_after_poll=6,
    )

    await wait_for_douyin_creator_table(
        page,
        normal_timeout_ms=2_000,
        poll_ms=1_000,
    )

    assert page.poll_count == 6
    assert page.submission_clicks == 1


@pytest.mark.asyncio
async def test_douyin_creator_normal_page_wait_has_bounded_timeout():
    page = FakeDouyinCreatorPage(
        verification_polls=0,
        table_after_click=False,
    )

    with pytest.raises(
        PlaywrightTimeoutError,
        match="normal page timeout",
    ):
        await wait_for_douyin_creator_table(
            page,
            normal_timeout_ms=2_000,
            poll_ms=1_000,
        )

    assert page.poll_count == 2
    assert page.submission_clicks == 1
