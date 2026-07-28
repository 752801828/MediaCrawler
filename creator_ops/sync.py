from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from creator_ops.config import Settings
from creator_ops.douyin_comment_threads import (
    build_douyin_comment_payloads,
)
from creator_ops.douyin_tags import is_excluded_douyin_tag_author_id
from creator_ops.domain import MetricRecord, Platform
from creator_ops.feishu.client import FeishuClient, FeishuError

DOUYIN_FEISHU_METRIC_FIELDS = {
    "完播率": "完播率_",
    "5S完播率": "5S完播放率_",
    "封面点击率": "封面点击率_",
    "2S跳出率": "2S跳出率_",
}
DOUYIN_PERCENTAGE_METRICS = frozenset(DOUYIN_FEISHU_METRIC_FIELDS)


@dataclass(frozen=True)
class SyncSummary:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0


def metric_feishu_payload(record: MetricRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "标题": record.title,
        "创建时间": (
            record.published_at.strftime("%Y-%m-%d %H:%M:%S")
            if record.published_at
            else ""
        ),
    }
    if record.content_url:
        payload["作品链接"] = record.content_url
    if record.platform is Platform.DOUYIN:
        for key, value in record.metrics.items():
            target_key = DOUYIN_FEISHU_METRIC_FIELDS.get(key, key)
            payload[target_key] = _douyin_metric_text(key, value)
    else:
        payload.update(record.metrics)
    return payload


def _douyin_metric_text(key: str, value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if key in DOUYIN_PERCENTAGE_METRICS and text and not text.endswith("%"):
        text = f"{text}%"
    return text


def metric_business_key(record: MetricRecord) -> str:
    return ":".join(
        (
            record.platform.value,
            record.profile_key,
            record.content_key,
            record.snapshot_date.isoformat(),
        )
    )


class OutboxSynchronizer:
    def __init__(self, settings: Settings, client: FeishuClient, repository: Any) -> None:
        self.settings = settings
        self.client = client
        self.repository = repository

    async def deliver_pending(self, limit: int | None = None) -> SyncSummary:
        rows = await self.repository.pending_sync(limit=limit)
        grouped: dict[str, list[Any]] = defaultdict(list)
        for row in rows:
            grouped[row.target_table].append(row)

        succeeded = 0
        failed = 0
        for target, target_rows in grouped.items():
            table_id = self._table_id(target)
            create_rows = [
                row
                for row in target_rows
                if not str(getattr(row, "remote_record_id", "") or "").strip()
            ]
            update_rows = [
                row
                for row in target_rows
                if str(getattr(row, "remote_record_id", "") or "").strip()
            ]

            if create_rows:
                try:
                    responses = await asyncio.to_thread(
                        self.client.batch_create_records,
                        self.settings.feishu.app_token,
                        table_id,
                        [json.loads(row.payload_json) for row in create_rows],
                    )
                    record_ids = _created_record_ids(responses)
                    if len(record_ids) != len(create_rows):
                        raise FeishuError(
                            "Feishu create response record count mismatch"
                        )
                except Exception as exc:
                    failed += len(create_rows)
                    error = type(exc).__name__
                    for row in create_rows:
                        await self.repository.mark_sync_failed(row.id, error)
                else:
                    succeeded += len(create_rows)
                    for row, record_id in zip(
                        create_rows,
                        record_ids,
                        strict=True,
                    ):
                        await self.repository.mark_sync_succeeded(
                            row.id,
                            remote_record_id=record_id,
                        )

            if update_rows:
                try:
                    await asyncio.to_thread(
                        self.client.batch_update_records,
                        self.settings.feishu.app_token,
                        table_id,
                        [
                            (
                                str(row.remote_record_id),
                                json.loads(row.payload_json),
                            )
                            for row in update_rows
                        ],
                    )
                except Exception as exc:
                    failed += len(update_rows)
                    error = type(exc).__name__
                    for row in update_rows:
                        await self.repository.mark_sync_failed(row.id, error)
                else:
                    succeeded += len(update_rows)
                    for row in update_rows:
                        await self.repository.mark_sync_succeeded(row.id)
        return SyncSummary(
            attempted=len(rows),
            succeeded=succeeded,
            failed=failed,
        )

    async def queue_platform_comments(self, platform: Platform) -> int:
        is_douyin = platform is Platform.DOUYIN
        if is_douyin:
            comments = await self.repository.list_comment_payloads(
                platform.value
            )
            return await self._queue_douyin_comments(
                comments,
                target="douyin_comments",
                business_key_prefix="comment:dy:",
                view_id=self.settings.feishu.comment_view_id,
            )

        target = "comments"
        table_id = self._table_id(target)
        existing_ids: set[str] = set()
        inventory_loaded = False
        try:
            existing = await asyncio.to_thread(
                self.client.iter_records,
                self.settings.feishu.app_token,
                table_id,
                self.settings.feishu.comment_view_id,
            )
            existing_ids = {
                str(
                    (record.get("fields") or {}).get("comment_id")
                    or ""
                )
                for record in existing
            }
            inventory_loaded = True
        except FeishuError:
            pass

        queued = 0
        comments = await self.repository.list_comment_payloads(platform.value)
        prepared = [
            (
                str(comment.get("comment_id") or ""),
                _comment_feishu_payload(comment, platform),
            )
            for comment in comments
        ]
        for comment_id, payload in prepared:
            if not comment_id:
                continue
            if comment_id in existing_ids:
                continue
            await self.repository.enqueue_sync(
                target_table=target,
                business_key=f"comment:xhs:{comment_id}",
                payload=payload,
                force_create=(
                    inventory_loaded and comment_id not in existing_ids
                ),
            )
            queued += 1
        return queued

    async def queue_douyin_tag_comments(self) -> int:
        comments = (
            await self.repository.list_douyin_tag_comment_payloads()
        )
        return await self._queue_douyin_comments(
            comments,
            target="douyin_tag_comments",
            business_key_prefix="tag-comment:dy:",
            view_id="",
            include_aweme_in_identity=True,
        )

    async def queue_douyin_tag_awemes(self) -> int:
        target = "douyin_tag_awemes"
        table_id = self._table_id(target)
        existing_keys: set[str] = set()
        inventory_loaded = False
        try:
            existing = await asyncio.to_thread(
                self.client.iter_records,
                self.settings.feishu.app_token,
                table_id,
                "",
            )
            existing_keys = {
                _douyin_tag_aweme_remote_key(
                    record.get("fields") or {}
                )
                for record in existing
            }
            inventory_loaded = True
        except FeishuError:
            pass

        rows = await self.repository.list_douyin_tag_aweme_payloads()
        queued = 0
        for row in rows:
            if is_excluded_douyin_tag_author_id(row.get("author_id")):
                continue
            payload = _douyin_tag_aweme_feishu_payload(row)
            remote_key = _douyin_tag_aweme_remote_key(payload)
            await self.repository.enqueue_sync(
                target_table=target,
                business_key=(
                    "tag-aweme:"
                    f"{row.get('tag_id')}:"
                    f"{row.get('aweme_id')}:"
                    f"{row.get('author_id')}"
                ),
                payload=payload,
                force_create=(
                    inventory_loaded and remote_key not in existing_keys
                ),
            )
            queued += 1
        return queued

    async def _queue_douyin_comments(
        self,
        comments: list[dict[str, Any]],
        *,
        target: str,
        business_key_prefix: str,
        view_id: str,
        include_aweme_in_identity: bool = False,
    ) -> int:
        table_id = self._table_id(target)
        existing_ids: set[str] = set()
        inventory_loaded = False
        try:
            existing = await asyncio.to_thread(
                self.client.iter_records,
                self.settings.feishu.app_token,
                table_id,
                view_id,
            )
            existing_ids = {
                _douyin_comment_identity(
                    record.get("fields") or {},
                    include_aweme=include_aweme_in_identity,
                )
                for record in existing
            }
            inventory_loaded = True
        except FeishuError:
            pass

        queued = 0
        for comment_id, payload in build_douyin_comment_payloads(comments):
            identity = _douyin_comment_identity(
                payload,
                include_aweme=include_aweme_in_identity,
            )
            await self.repository.enqueue_sync(
                target_table=target,
                business_key=f"{business_key_prefix}{identity}",
                payload=payload,
                force_create=(
                    inventory_loaded and identity not in existing_ids
                ),
            )
            queued += 1
        return queued

    def _table_id(self, target: str) -> str:
        mapping = {
            "xhs_stats": self.settings.feishu.xhs_stats_table_id,
            "douyin_stats": self.settings.feishu.douyin_stats_table_id,
            "comments": self.settings.feishu.comment_table_id,
            "douyin_comments": self.settings.feishu.douyin_comment_table_id,
            "douyin_tag_comments": (
                self.settings.feishu.douyin_tag_comment_table_id
            ),
            "douyin_tag_awemes": (
                self.settings.feishu.douyin_tag_result_table_id
            ),
            "xhs_creator": self.settings.feishu.xhs_creator_table_id,
            "douyin_creator": self.settings.feishu.douyin_creator_table_id,
        }
        table_id = mapping.get(target, "")
        if not table_id:
            raise ValueError(f"unknown or unconfigured Feishu target: {target}")
        return table_id


def _comment_feishu_payload(
    fields: dict[str, Any],
    _platform: Platform,
) -> dict[str, Any]:
    cleaned = dict(fields)
    cleaned.pop("creator_hash", None)
    cleaned["add_ts"] = _format_timestamp(cleaned.get("add_ts"))
    cleaned["last_modify_ts"] = _format_timestamp(cleaned.get("last_modify_ts"))
    cleaned["create_time"] = _format_timestamp(cleaned.get("create_time"))
    return cleaned


def _douyin_comment_identity(
    fields: dict[str, Any],
    *,
    include_aweme: bool,
) -> str:
    comment_id = str(fields.get("评论ID") or "")
    if not include_aweme:
        return comment_id
    aweme_id = str(fields.get("视频ID") or "")
    return f"{aweme_id}:{comment_id}"


def _douyin_tag_aweme_feishu_payload(
    fields: dict[str, Any],
) -> dict[str, str]:
    aweme_id = _text_value(fields.get("aweme_id"))
    share_url = _text_value(fields.get("share_url"))
    if not share_url and aweme_id:
        share_url = f"https://www.douyin.com/video/{aweme_id}"
    return {
        "tag_id": _text_value(fields.get("tag_id")),
        "tag名称": _text_value(fields.get("tag_name")),
        "作者id": _text_value(fields.get("author_id")),
        "sec_uid": _text_value(fields.get("sec_uid")),
        "作品标题": _text_value(fields.get("title")),
        "作品文案": _text_value(fields.get("description")),
        "媒体类型": _text_value(fields.get("media_type")),
        "作品发布时间": _datetime_text(fields.get("published_at")),
        "作品分享链接": share_url,
        "作品播放数": _text_value(fields.get("play_count")),
        "作品点赞数": _text_value(fields.get("digg_count")),
        "作品评论数": _text_value(fields.get("comment_count")),
        "作品分享数": _text_value(fields.get("share_count")),
        "作品收藏数": _text_value(fields.get("collect_count")),
        "作品推荐数": _text_value(fields.get("recommend_count")),
        "作品tag": _douyin_tag_names(fields),
        "封面图片地址": _text_value(fields.get("cover_url")),
        "作者昵称": _text_value(fields.get("author_nickname")),
        "作者粉丝数": _text_value(fields.get("author_follower_count")),
        "作者关注数": _text_value(fields.get("author_following_count")),
    }


def _douyin_tag_aweme_remote_key(fields: dict[str, Any]) -> str:
    return ":".join(
        (
            _text_value(fields.get("tag_id")),
            _text_value(fields.get("作品分享链接")),
        )
    )


def _douyin_tag_names(fields: dict[str, Any]) -> str:
    names: list[str] = []
    for source, key in (
        (fields.get("text_extra_json"), "hashtag_name"),
        (fields.get("video_tag_json"), "tag_name"),
    ):
        try:
            items = (
                json.loads(source)
                if isinstance(source, str)
                else source
            )
        except (TypeError, ValueError):
            items = []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _text_value(item.get(key))
            if name and name not in names:
                names.append(name)
    return " ".join(f"#{name}" for name in names)


def _text_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _datetime_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return _text_value(value)


def _created_record_ids(responses: list[dict[str, Any]]) -> list[str]:
    record_ids: list[str] = []
    for response in responses:
        records = (response.get("data") or {}).get("records") or []
        for record in records:
            record_id = str(
                record.get("record_id") or record.get("id") or ""
            ).strip()
            if record_id:
                record_ids.append(record_id)
    return record_ids


def _format_timestamp(value: Any) -> str:
    if not value:
        return ""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric > 10_000_000_000:
        numeric //= 1000
    return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d %H:%M:%S")
