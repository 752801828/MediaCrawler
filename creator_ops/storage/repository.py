from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from creator_ops.domain import MetricRecord, Task
from database.db_session import get_session

from .models import (
    CreatorAccountMetricSnapshot,
    CreatorContentMetricSnapshot,
    CreatorOpsRun,
    CreatorOpsSyncOutbox,
    CreatorOpsTask,
    CreatorPublicContentSnapshot,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class CreatorOpsRepository:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self.session_factory = session_factory or get_session

    async def create_run(self, run_uuid: str) -> int:
        async with self.session_factory() as session:
            row = CreatorOpsRun(
                run_uuid=run_uuid,
                status="running",
                started_at=datetime.now(),
            )
            session.add(row)
            await session.flush()
            return int(row.id)

    async def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        total_tasks: int,
        succeeded_tasks: int,
        failed_tasks: int,
    ) -> None:
        async with self.session_factory() as session:
            row = await session.get(CreatorOpsRun, run_id)
            if row is None:
                raise LookupError(f"creator operations run not found: {run_id}")
            row.status = status
            row.finished_at = datetime.now()
            row.total_tasks = total_tasks
            row.succeeded_tasks = succeeded_tasks
            row.failed_tasks = failed_tasks

    async def start_task(self, run_id: int, task: Task) -> int:
        async with self.session_factory() as session:
            row = CreatorOpsTask(
                run_id=run_id,
                task_key=task.task_id,
                platform=task.platform.value,
                kind=task.kind.value,
                profile_key=task.profile.template,
                status="running",
                started_at=datetime.now(),
            )
            session.add(row)
            await session.flush()
            return int(row.id)

    async def finish_task(self, task_row_id: int, *, success: bool, error: str = "") -> None:
        async with self.session_factory() as session:
            row = await session.get(CreatorOpsTask, task_row_id)
            if row is None:
                raise LookupError(f"creator operations task not found: {task_row_id}")
            row.status = "succeeded" if success else "failed"
            row.error_message = error[:4000]
            row.finished_at = datetime.now()

    async def upsert_content_snapshot(self, record: MetricRecord) -> int:
        async with self.session_factory() as session:
            return await _upsert_content_snapshot(session, record)

    async def save_content_with_outbox(
        self,
        record: MetricRecord,
        *,
        target_table: str,
        business_key: str,
        payload: dict[str, Any],
    ) -> tuple[int, int]:
        async with self.session_factory() as session:
            snapshot_id = await _upsert_content_snapshot(session, record)
            outbox_id = await _enqueue_sync(
                session,
                target_table=target_table,
                business_key=business_key,
                payload=payload,
            )
            return snapshot_id, outbox_id

    async def upsert_account_snapshot(
        self,
        *,
        platform: str,
        profile_key: str,
        snapshot_date: date,
        metrics: dict[str, Any],
    ) -> int:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(CreatorAccountMetricSnapshot).where(
                    CreatorAccountMetricSnapshot.platform == platform,
                    CreatorAccountMetricSnapshot.profile_key == profile_key,
                    CreatorAccountMetricSnapshot.snapshot_date == snapshot_date,
                )
            )
            now = datetime.now()
            if row is None:
                row = CreatorAccountMetricSnapshot(
                    platform=platform,
                    profile_key=profile_key,
                    snapshot_date=snapshot_date,
                    metrics_json=_canonical_json(metrics),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.metrics_json = _canonical_json(metrics)
                row.updated_at = now
            await session.flush()
            return int(row.id)

    async def upsert_public_snapshot(
        self,
        *,
        platform: str,
        content_key: str,
        creator_hash: str,
        masked_nickname: str,
        snapshot_date: date,
        metrics: dict[str, Any],
    ) -> int:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(CreatorPublicContentSnapshot).where(
                    CreatorPublicContentSnapshot.platform == platform,
                    CreatorPublicContentSnapshot.content_key == content_key,
                    CreatorPublicContentSnapshot.snapshot_date == snapshot_date,
                )
            )
            now = datetime.now()
            if row is None:
                row = CreatorPublicContentSnapshot(
                    platform=platform,
                    content_key=content_key,
                    creator_hash=creator_hash,
                    masked_nickname=masked_nickname,
                    snapshot_date=snapshot_date,
                    metrics_json=_canonical_json(metrics),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.creator_hash = creator_hash
                row.masked_nickname = masked_nickname
                row.metrics_json = _canonical_json(metrics)
                row.updated_at = now
            await session.flush()
            return int(row.id)

    async def enqueue_sync(
        self,
        *,
        target_table: str,
        business_key: str,
        payload: dict[str, Any],
    ) -> int:
        async with self.session_factory() as session:
            return await _enqueue_sync(
                session,
                target_table=target_table,
                business_key=business_key,
                payload=payload,
            )

    async def pending_sync(self, limit: int = 500) -> list[CreatorOpsSyncOutbox]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(CreatorOpsSyncOutbox)
                .where(CreatorOpsSyncOutbox.status.in_(("pending", "failed")))
                .order_by(CreatorOpsSyncOutbox.id)
                .limit(limit)
            )
            return list(rows)

    async def mark_sync_succeeded(
        self,
        outbox_id: int,
        remote_record_id: str = "",
    ) -> None:
        async with self.session_factory() as session:
            row = await session.get(CreatorOpsSyncOutbox, outbox_id)
            if row is None:
                raise LookupError(f"sync outbox row not found: {outbox_id}")
            row.status = "synced"
            if remote_record_id:
                row.remote_record_id = remote_record_id
            row.last_error = ""
            row.synced_at = datetime.now()
            row.updated_at = row.synced_at

    async def mark_sync_failed(self, outbox_id: int, error: str) -> None:
        async with self.session_factory() as session:
            row = await session.get(CreatorOpsSyncOutbox, outbox_id)
            if row is None:
                raise LookupError(f"sync outbox row not found: {outbox_id}")
            row.status = "failed"
            row.attempts += 1
            row.last_error = error[:4000]
            row.updated_at = datetime.now()

    async def list_comment_payloads(
        self,
        platform: str,
        *,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        if platform == "xhs":
            from database.models import XhsNoteComment as CommentModel

            content_id_field = "note_id"
        elif platform == "dy":
            from database.models import DouyinAwemeComment as CommentModel

            content_id_field = "aweme_id"
        else:
            raise ValueError(f"unsupported comment platform: {platform}")

        async with self.session_factory() as session:
            result = await session.scalars(
                select(CommentModel).order_by(CommentModel.id).limit(limit)
            )
            payloads: list[dict[str, Any]] = []
            for row in result:
                payload = {
                    "id": str(row.id),
                    "creator_hash": getattr(row, "creator_hash", "") or "",
                    "nickname": getattr(row, "nickname", "") or "",
                    "add_ts": getattr(row, "add_ts", 0) or 0,
                    "last_modify_ts": getattr(row, "last_modify_ts", 0) or 0,
                    "comment_id": getattr(row, "comment_id", "") or "",
                    "content": getattr(row, "content", "") or "",
                    "create_time": getattr(row, "create_time", 0) or 0,
                    "sub_comment_count": getattr(row, "sub_comment_count", 0) or 0,
                    "parent_comment_id": getattr(row, "parent_comment_id", "") or "",
                    "like_count": getattr(row, "like_count", 0) or 0,
                    "pictures": getattr(row, "pictures", "") or "",
                    content_id_field: getattr(row, content_id_field, "") or "",
                }
                payloads.append(payload)
            return payloads


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _upsert_content_snapshot(
    session: AsyncSession,
    record: MetricRecord,
) -> int:
    row = await session.scalar(
        select(CreatorContentMetricSnapshot).where(
            CreatorContentMetricSnapshot.platform == record.platform.value,
            CreatorContentMetricSnapshot.profile_key == record.profile_key,
            CreatorContentMetricSnapshot.content_key == record.content_key,
            CreatorContentMetricSnapshot.snapshot_date == record.snapshot_date,
        )
    )
    now = datetime.now()
    payload = _canonical_json(record.metrics)
    if row is None:
        row = CreatorContentMetricSnapshot(
            platform=record.platform.value,
            profile_key=record.profile_key,
            content_key=record.content_key,
            title=record.title,
            content_url=record.content_url,
            published_at=record.published_at,
            snapshot_date=record.snapshot_date,
            metrics_json=payload,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.title = record.title
        row.content_url = record.content_url
        row.published_at = record.published_at
        row.metrics_json = payload
        row.updated_at = now
    await session.flush()
    return int(row.id)


async def _enqueue_sync(
    session: AsyncSession,
    *,
    target_table: str,
    business_key: str,
    payload: dict[str, Any],
) -> int:
    row = await session.scalar(
        select(CreatorOpsSyncOutbox).where(
            CreatorOpsSyncOutbox.target_table == target_table,
            CreatorOpsSyncOutbox.business_key == business_key,
        )
    )
    now = datetime.now()
    serialized = _canonical_json(payload)
    if row is None:
        row = CreatorOpsSyncOutbox(
            target_table=target_table,
            business_key=business_key,
            payload_json=serialized,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    elif row.payload_json != serialized:
        row.payload_json = serialized
        row.status = "pending"
        row.last_error = ""
        row.synced_at = None
        row.updated_at = now
    await session.flush()
    return int(row.id)
