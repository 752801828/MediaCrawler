from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, AsyncIterator

from creator_ops.domain import AccountProfile, MetricRecord, Platform
from creator_ops.feishu.schema import XHS_STATS_FIELDS

from .base import (
    make_content_key,
    parse_metric_number,
    parse_published_at,
    persistent_page,
    save_diagnostic,
)

XHS_CREATOR_URL = "https://creator.xiaohongshu.com/statistics/data-analysis?source=official"
RowSource = Callable[[AccountProfile], AsyncIterator[list[dict[str, Any]]]]


def normalize_xhs_row(
    profile_key: str,
    row: dict[str, Any],
    snapshot_date: date | None = None,
) -> MetricRecord:
    title = str(row.get("标题") or "").strip()
    if not title:
        raise ValueError("Xiaohongshu creator row is missing 标题")
    published_at = parse_published_at(row.get("创建时间"))
    metrics = {
        key: parse_metric_number(value)
        for key, value in row.items()
        if key not in {"标题", "创建时间", "内容ID"}
    }
    return MetricRecord(
        platform=Platform.XHS,
        profile_key=profile_key,
        content_key=make_content_key(
            platform=Platform.XHS.value,
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


class XhsCreatorCollector:
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
                    normalize_xhs_row(profile.template, row, snapshot_date)
                )
        return records

    async def _iter_browser_rows(
        self,
        profile: AccountProfile,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        async with persistent_page(profile.path, headless=False) as page:
            try:
                await page.goto(XHS_CREATOR_URL, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_selector(
                    "#pane-note-data table tbody tr",
                    timeout=600_000,
                )
                for _ in range(1000):
                    row_locator = page.locator("#pane-note-data table tbody tr")
                    rows: list[dict[str, Any]] = []
                    for index in range(await row_locator.count()):
                        row = row_locator.nth(index)
                        title_locator = row.locator(".note-title")
                        time_locator = row.locator(".time")
                        title = (
                            (await title_locator.first.inner_text()).strip()
                            if await title_locator.count()
                            else ""
                        )
                        created = (
                            (await time_locator.first.inner_text()).strip()
                            if await time_locator.count()
                            else ""
                        )
                        cells = [text.strip() for text in await row.locator("td").all_inner_texts()]
                        parsed: dict[str, Any] = {"标题": title, "创建时间": created}
                        for field, value in zip(XHS_STATS_FIELDS[2:], cells[1:]):
                            parsed[field] = value
                        rows.append(parsed)
                    yield rows

                    buttons = page.locator("div.d-pagination-page.d-clickable")
                    if await buttons.count() == 0:
                        break
                    next_button = buttons.last
                    classes = (await next_button.get_attribute("class")) or ""
                    if "disabled" in classes:
                        break
                    await next_button.click()
                    await page.wait_for_timeout(1500)
            except Exception:
                await save_diagnostic(page, "xhs", "creator-table")
                raise
