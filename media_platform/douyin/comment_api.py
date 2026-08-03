from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from playwright.async_api import BrowserContext, Page

from tools import utils

from .client import DouYinClient
from .exception import DataFetchError


CommentCallback = Callable[[str, list[dict[str, Any]]], Awaitable[None]]


@dataclass(frozen=True)
class CommentFetchStats:
    aweme_id: str
    root_pages: int
    root_comments: int
    reply_pages: int
    reply_comments: int

    @property
    def total_comments(self) -> int:
        return self.root_comments + self.reply_comments


class WaterAccountCommentApiFetcher:
    """Fetch Douyin comments directly with an existing water-account session."""

    def __init__(
        self,
        *,
        client: DouYinClient,
        browser_context: BrowserContext,
        page: Page,
        callback: CommentCallback,
        crawl_interval: float,
        fetch_sub_comments: bool,
        max_attempts: int = 3,
    ) -> None:
        self.client = client
        self.browser_context = browser_context
        self.page = page
        self.callback = callback
        self.crawl_interval = max(float(crawl_interval), 0.0)
        self.fetch_sub_comments = fetch_sub_comments
        self.max_attempts = max(int(max_attempts), 1)

    async def fetch(self, aweme_id: str) -> CommentFetchStats:
        aweme_id = str(aweme_id).strip()
        if not aweme_id:
            raise ValueError("aweme_id is required")
        await self._refresh_session(aweme_id, reload=False)
        if not await self.client.pong(self.browser_context):
            raise DataFetchError("water account profile is not logged in")

        root_pages = 0
        root_comments = 0
        reply_pages = 0
        reply_comments = 0
        root_cursor: Any = 0
        seen_root_cursors: set[str] = set()

        while True:
            cursor_key = str(root_cursor)
            if cursor_key in seen_root_cursors:
                utils.logger.warning(
                    "[WaterAccountCommentApiFetcher] "
                    "aweme_id=%s level=root repeated_cursor=%s; stop",
                    aweme_id,
                    root_cursor,
                )
                break
            seen_root_cursors.add(cursor_key)
            requested_cursor = root_cursor
            payload = await self._request_with_retry(
                aweme_id=aweme_id,
                label=f"root cursor={requested_cursor}",
                operation=lambda cursor=requested_cursor: (
                    self.client.get_aweme_comments(aweme_id, cursor)
                ),
            )
            root_batch = self._comments_from_payload(payload)
            root_pages += 1
            prepared_roots = [
                self._prepare_comment(
                    item,
                    aweme_id=aweme_id,
                    parent_comment_id="",
                )
                for item in root_batch
            ]
            if prepared_roots:
                await self.callback(aweme_id, prepared_roots)
            root_comments += len(prepared_roots)
            utils.logger.info(
                "[WaterAccountCommentApiFetcher] "
                "channel=water-api aweme_id=%s level=root cursor=%s "
                "page_count=%s total=%s",
                aweme_id,
                requested_cursor,
                len(prepared_roots),
                root_comments,
            )

            if self.fetch_sub_comments:
                for root_comment in root_batch:
                    root_comment_id = str(root_comment.get("cid") or "").strip()
                    if (
                        root_comment_id
                        and self._reply_count(root_comment) > 0
                    ):
                        pages, comments = await self._fetch_replies(
                            aweme_id=aweme_id,
                            root_comment_id=root_comment_id,
                        )
                        reply_pages += pages
                        reply_comments += comments

            if not root_batch or not payload.get("has_more"):
                break
            root_cursor = payload.get("cursor", 0)
            await self._sleep()

        stats = CommentFetchStats(
            aweme_id=aweme_id,
            root_pages=root_pages,
            root_comments=root_comments,
            reply_pages=reply_pages,
            reply_comments=reply_comments,
        )
        utils.logger.info(
            "[WaterAccountCommentApiFetcher] "
            "channel=water-api aweme_id=%s completed root=%s replies=%s total=%s",
            aweme_id,
            stats.root_comments,
            stats.reply_comments,
            stats.total_comments,
        )
        return stats

    async def _fetch_replies(
        self,
        *,
        aweme_id: str,
        root_comment_id: str,
    ) -> tuple[int, int]:
        pages = 0
        comments = 0
        cursor: Any = 0
        seen_cursors: set[str] = set()
        while True:
            cursor_key = str(cursor)
            if cursor_key in seen_cursors:
                utils.logger.warning(
                    "[WaterAccountCommentApiFetcher] "
                    "aweme_id=%s level=reply parent=%s repeated_cursor=%s; stop",
                    aweme_id,
                    root_comment_id,
                    cursor,
                )
                break
            seen_cursors.add(cursor_key)
            requested_cursor = cursor
            payload = await self._request_with_retry(
                aweme_id=aweme_id,
                label=(
                    f"reply parent={root_comment_id} "
                    f"cursor={requested_cursor}"
                ),
                operation=lambda current=requested_cursor: (
                    self.client.get_sub_comments(
                        aweme_id,
                        root_comment_id,
                        current,
                    )
                ),
            )
            reply_batch = self._comments_from_payload(payload)
            pages += 1
            prepared_replies = [
                self._prepare_comment(
                    item,
                    aweme_id=aweme_id,
                    parent_comment_id=root_comment_id,
                )
                for item in reply_batch
            ]
            if prepared_replies:
                await self.callback(aweme_id, prepared_replies)
            comments += len(prepared_replies)
            utils.logger.info(
                "[WaterAccountCommentApiFetcher] "
                "channel=water-api aweme_id=%s level=reply parent=%s "
                "cursor=%s page_count=%s total=%s",
                aweme_id,
                root_comment_id,
                requested_cursor,
                len(prepared_replies),
                comments,
            )
            if not reply_batch or not payload.get("has_more"):
                break
            cursor = payload.get("cursor", 0)
            await self._sleep()
        return pages, comments

    async def _request_with_retry(
        self,
        *,
        aweme_id: str,
        label: str,
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts_used = 0
        for attempt in range(1, self.max_attempts + 1):
            attempts_used = attempt
            try:
                payload = await operation()
                if not isinstance(payload, dict):
                    raise DataFetchError(
                        f"invalid comment response type: {type(payload).__name__}"
                    )
                return payload
            except Exception as exc:
                last_error = exc
                utils.logger.warning(
                    "[WaterAccountCommentApiFetcher] "
                    "channel=water-api aweme_id=%s request=%s "
                    "attempt=%s/%s failed=%s",
                    aweme_id,
                    label,
                    attempt,
                    self.max_attempts,
                    type(exc).__name__,
                )
                if attempt >= self.max_attempts:
                    break
                if self._client_already_exhausted_retries(exc):
                    break
                await self._refresh_session(aweme_id, reload=True)
                await asyncio.sleep(max(self.crawl_interval, float(attempt)))
        raise DataFetchError(
            f"water comment api failed after {attempts_used} attempts "
            f"({type(last_error).__name__ if last_error else 'unknown'})"
        ) from last_error

    async def _refresh_session(self, aweme_id: str, *, reload: bool) -> None:
        target_url = f"https://www.douyin.com/video/{aweme_id}"
        if reload and not self.page.is_closed():
            await self.page.reload(
                wait_until="domcontentloaded",
                timeout=60000,
            )
        else:
            await self.page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
        await self.client.update_cookies(self.browser_context)

    async def _sleep(self) -> None:
        if self.crawl_interval > 0:
            await asyncio.sleep(self.crawl_interval)

    @staticmethod
    def _comments_from_payload(
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        comments = payload.get("comments")
        if comments is None:
            return []
        if not isinstance(comments, list):
            raise DataFetchError(
                f"invalid comments type: {type(comments).__name__}"
            )
        return [item for item in comments if isinstance(item, dict)]

    @staticmethod
    def _prepare_comment(
        comment: dict[str, Any],
        *,
        aweme_id: str,
        parent_comment_id: str,
    ) -> dict[str, Any]:
        prepared = dict(comment)
        prepared["aweme_id"] = str(prepared.get("aweme_id") or aweme_id)
        prepared["_parent_comment_id"] = parent_comment_id
        return prepared

    @staticmethod
    def _reply_count(comment: dict[str, Any]) -> int:
        value = comment.get("reply_comment_total")
        if value is None:
            value = comment.get("reply_comment_count", 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _client_already_exhausted_retries(exc: Exception) -> bool:
        message = str(exc).casefold()
        return (
            "request failed after" in message
            or "request returned no response" in message
        )
