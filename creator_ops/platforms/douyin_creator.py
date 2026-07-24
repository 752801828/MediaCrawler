from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, AsyncIterator

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from creator_ops.domain import AccountProfile, MetricRecord, Platform
from tools import utils

from .base import (
    locator_text,
    make_content_key,
    parse_metric_number,
    parse_published_at,
    persistent_page,
    save_diagnostic,
)

DOUYIN_CREATOR_URL = "https://creator.douyin.com/creator-micro/data-center/content"
DOUYIN_CREATOR_TABLE_SELECTOR = "tr.douyin-creator-pc-table-row"
DOUYIN_VERIFICATION_POLL_MS = 1_000
RowSource = Callable[[AccountProfile], AsyncIterator[list[dict[str, Any]]]]

DOUYIN_COLUMN_INDEX = {
    "浏览": 3,
    "完播率": 4,
    "5S完播率": 5,
    "封面点击率": 6,
    "2S跳出率": 7,
    "人均观看时长": 8,
    "点赞": 9,
    "分享": 10,
    "评论": 11,
    "收藏": 12,
    "主页访问量": 13,
    "涨粉": 14,
}


def normalize_douyin_row(
    profile_key: str,
    row: dict[str, Any],
    snapshot_date: date | None = None,
) -> MetricRecord:
    title = str(row.get("标题") or "").strip()
    if not title:
        raise ValueError("Douyin creator row is missing 标题")
    published_at = parse_published_at(row.get("创建时间"))
    metrics = {
        key: parse_metric_number(value)
        for key, value in row.items()
        if key not in {"标题", "创建时间", "内容ID"}
    }
    return MetricRecord(
        platform=Platform.DOUYIN,
        profile_key=profile_key,
        content_key=make_content_key(
            platform=Platform.DOUYIN.value,
            profile_key=profile_key,
            title=title,
            published_at=published_at,
            explicit_id=str(row.get("内容ID") or ""),
        ),
        title=title,
        published_at=published_at,
        snapshot_date=snapshot_date or date.today(),
        metrics=metrics,
    )


class DouyinCreatorCollector:
    def __init__(self, row_source: RowSource | None = None) -> None:
        self.row_source = row_source or self._iter_browser_rows

    async def collect(
        self,
        profile: AccountProfile,
        *,
        snapshot_date: date | None = None,
    ) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        async for rows in self.row_source(profile):
            for row in rows:
                records.append(
                    normalize_douyin_row(profile.template, row, snapshot_date)
                )
        return records

    async def _iter_browser_rows(
        self,
        profile: AccountProfile,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        async with persistent_page(profile.path, headless=False) as page:
            try:
                await page.goto(DOUYIN_CREATOR_URL, wait_until="domcontentloaded", timeout=60_000)
                await wait_for_douyin_creator_table(page)

                parsed_by_key: dict[str, dict[str, Any]] = {}
                unchanged = 0
                previous_count = -1
                for _ in range(50):
                    current_rows = await self._parse_visible_rows(page)
                    for row in current_rows:
                        key = f"{row.get('标题', '')}|{row.get('创建时间', '')}"
                        parsed_by_key[key] = row
                    row_count = len(parsed_by_key)
                    if row_count == previous_count:
                        unchanged += 1
                    else:
                        unchanged = 0
                    if unchanged >= 3:
                        break
                    previous_count = row_count
                    container = page.locator("div.douyin-creator-pc-table-body")
                    if await container.count():
                        await container.first.evaluate("element => element.scrollTo(0, element.scrollHeight)")
                    await page.mouse.wheel(0, 1200)
                    await page.wait_for_timeout(1500)
                yield list(parsed_by_key.values())
            except Exception:
                await save_diagnostic(page, "douyin", "creator-table")
                raise

    async def _parse_visible_rows(self, page: Any) -> list[dict[str, Any]]:
        rows_locator = page.locator("tr.douyin-creator-pc-table-row")
        rows: list[dict[str, Any]] = []
        for index in range(await rows_locator.count()):
            row = rows_locator.nth(index)
            parsed: dict[str, Any] = {
                "标题": await locator_text(row.locator("[class*='workTitle'] span")),
                "创建时间": await locator_text(row.locator("[class*='date']")),
            }
            for field, column_index in DOUYIN_COLUMN_INDEX.items():
                parsed[field] = await locator_text(
                    row.locator(f"td[aria-colindex='{column_index}'] span")
                )
            rows.append(parsed)
        return rows


async def wait_for_douyin_creator_table(
    page: Any,
    *,
    poll_ms: int = DOUYIN_VERIFICATION_POLL_MS,
) -> None:
    utils.logger.info(
        "[DouyinCreatorCollector] 持续等待创作者数据表；"
        "登录、短信或身份验证期间浏览器不会自动关闭，"
        "按 Ctrl+C 可停止任务"
    )
    submission_tab = page.get_by_text("投稿列表", exact=True)
    verification_title = page.get_by_text("身份验证", exact=True)
    verification_logged = False
    submission_clicked = False

    while True:
        table = page.locator(DOUYIN_CREATOR_TABLE_SELECTOR)
        if await table.count() and await table.first.is_visible():
            utils.logger.info(
                "[DouyinCreatorCollector] 已进入投稿数据表，"
                "开始采集"
            )
            return

        verification_visible = (
            await verification_title.count()
            and await verification_title.first.is_visible()
        )
        if verification_visible:
            if not verification_logged:
                utils.logger.info(
                    "[DouyinCreatorCollector] 检测到身份验证，"
                    "浏览器将持续保持开启，直到投稿数据表出现；"
                    "按 Ctrl+C 可停止任务"
                )
                verification_logged = True
            submission_clicked = False
        else:
            if (
                not submission_clicked
                and await submission_tab.count()
                and await submission_tab.first.is_visible()
            ):
                try:
                    await submission_tab.first.click(
                        timeout=min(1_000, poll_ms)
                    )
                except PlaywrightTimeoutError:
                    # The verification dialog can appear between the
                    # visibility check and click. Keep retrying.
                    pass
                else:
                    submission_clicked = True

        await page.wait_for_timeout(poll_ms)
