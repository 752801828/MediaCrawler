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
from creator_ops.feishu.schema import PRIVACY_RESTRICTED_COMMENT_FIELDS


@dataclass(frozen=True)
class SyncSummary:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0


def sanitize_comment_fields(fields: dict[str, Any]) -> dict[str, Any]:
    output = dict(fields)
    for key in PRIVACY_RESTRICTED_COMMENT_FIELDS:
        if key in output:
            output[key] = ""
    return output


def metric_feishu_payload(record: MetricRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "标题": record.title,
        "创建时间": (
            record.published_at.strftime("%Y-%m-%d %H:%M:%S")
            if record.published_at
            else ""
        ),
    }
    payload.update(record.metrics)
    return payload


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

    async def deliver_pending(self, limit: int = 500) -> SyncSummary:
        rows = await self.repository.pending_sync(limit=limit)
        grouped: dict[str, list[Any]] = defaultdict(list)
        for row in rows:
            grouped[row.target_table].append(row)

        succeeded = 0
        failed = 0
        for target, target_rows in grouped.items():
            try:
                payloads = [json.loads(row.payload_json) for row in target_rows]
                await asyncio.to_thread(
                    self.client.batch_create_records,
                    self.settings.feishu.app_token,
                    self._table_id(target),
                    payloads,
                )
            except Exception as exc:
                failed += len(target_rows)
                error = type(exc).__name__
                for row in target_rows:
                    await self.repository.mark_sync_failed(row.id, error)
            else:
                succeeded += len(target_rows)
                for row in target_rows:
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
    platform: Platform,
) -> dict[str, Any]:
    cleaned = sanitize_comment_fields(fields)
    creator_hash = str(cleaned.pop("creator_hash", "") or "")
    cleaned["user_id"] = f"anon:{creator_hash}" if creator_hash else ""
    cleaned["add_ts"] = _format_timestamp(cleaned.get("add_ts"))
    cleaned["last_modify_ts"] = _format_timestamp(cleaned.get("last_modify_ts"))
    cleaned["create_time"] = _format_timestamp(cleaned.get("create_time"))
    if platform is Platform.DOUYIN:
        cleaned.update(
            {
                "sec_uid": "",
                "short_user_id": "",
                "user_unique_id": "",
                "avatar": "",
                "user_signature": "",
                "ip_location": "",
            }
        )
    else:
        cleaned.update({"avatar": "", "ip_location": ""})
    return cleaned


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
