from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, AsyncIterator

from creator_ops.domain import AccountProfile, MetricRecord, Platform

from .base import (
    locator_text,
    make_content_key,
    parse_metric_number,
    parse_published_at,
    persistent_page,
    save_diagnostic,
)

DOUYIN_CREATOR_URL = "https://creator.douyin.com/creator-micro/data-center/content"
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
                submission_tab = page.get_by_text("投稿列表", exact=True)
                if await submission_tab.count():
                    await submission_tab.first.click()
                await page.wait_for_selector(
                    "tr.douyin-creator-pc-table-row",
                    timeout=30_000,
                )

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
