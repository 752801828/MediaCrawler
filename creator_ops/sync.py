from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from creator_ops.config import Settings
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
        target = (
            "douyin_comments"
            if platform is Platform.DOUYIN
            and self.settings.feishu.douyin_comment_table_id
            else "comments"
        )
        table_id = self._table_id(target)
        existing_ids: set[str] = set()
        try:
            existing = await asyncio.to_thread(
                self.client.iter_records,
                self.settings.feishu.app_token,
                table_id,
                self.settings.feishu.comment_view_id,
            )
            existing_ids = {
                str((record.get("fields") or {}).get("comment_id") or "")
                for record in existing
            }
        except FeishuError:
            pass

        queued = 0
        comments = await self.repository.list_comment_payloads(platform.value)
        for comment in comments:
            comment_id = str(comment.get("comment_id") or "")
            if not comment_id or comment_id in existing_ids:
                continue
            payload = _comment_feishu_payload(comment, platform)
            await self.repository.enqueue_sync(
                target_table=target,
                business_key=f"comment:{platform.value}:{comment_id}",
                payload=payload,
            )
            queued += 1
        return queued

    def _table_id(self, target: str) -> str:
        mapping = {
            "xhs_stats": self.settings.feishu.xhs_stats_table_id,
            "douyin_stats": self.settings.feishu.douyin_stats_table_id,
            "comments": self.settings.feishu.comment_table_id,
            "douyin_comments": self.settings.feishu.douyin_comment_table_id,
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
