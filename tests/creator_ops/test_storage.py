from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from creator_ops.domain import MetricRecord, Platform
from creator_ops.storage.models import (
    CreatorContentMetricSnapshot,
    CreatorOpsSyncOutbox,
)
from creator_ops.storage.repository import CreatorOpsRepository
from database.models import Base


def test_content_snapshot_has_daily_business_key():
    constraints = [
        item
        for item in CreatorContentMetricSnapshot.__table__.constraints
        if isinstance(item, UniqueConstraint)
    ]
    columns = {tuple(column.name for column in item.columns) for item in constraints}

    assert ("platform", "profile_key", "content_key", "snapshot_date") in columns


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    database_path = tmp_path / "creator-ops.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_factory():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    yield CreatorOpsRepository(session_factory=session_factory), session_maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_content_snapshot_updates_same_daily_key(repository):
    repo, session_maker = repository
    first = MetricRecord(
        platform=Platform.XHS,
        profile_key="%s_use_data_dir",
        content_key="note-1",
        title="Title",
        content_url="https://www.xiaohongshu.com/explore/note-1",
        published_at=datetime(2026, 7, 20, 10, 0),
        snapshot_date=date(2026, 7, 21),
        metrics={"浏览": 10},
    )
    second = MetricRecord(
        platform=first.platform,
        profile_key=first.profile_key,
        content_key=first.content_key,
        title=first.title,
        content_url="https://www.xiaohongshu.com/explore/note-1-updated",
        published_at=first.published_at,
        snapshot_date=first.snapshot_date,
        metrics={"浏览": 20},
    )

    first_id = await repo.upsert_content_snapshot(first)
    second_id = await repo.upsert_content_snapshot(second)

    assert first_id == second_id
    async with session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(CreatorContentMetricSnapshot))
        row = await session.scalar(select(CreatorContentMetricSnapshot))
    assert count == 1
    assert row.content_url == "https://www.xiaohongshu.com/explore/note-1-updated"
    assert json.loads(row.metrics_json) == {"浏览": 20}


@pytest.mark.asyncio
async def test_outbox_transitions_from_pending_to_synced(repository):
    repo, session_maker = repository

    outbox_id = await repo.enqueue_sync(
        target_table="xhs_stats",
        business_key="xhs:%s_use_data_dir:note-1:2026-07-21",
        payload={"标题": "Title", "浏览": 20},
    )
    pending = await repo.pending_sync()

    assert [row.id for row in pending] == [outbox_id]
    await repo.mark_sync_succeeded(outbox_id, remote_record_id="rec-1")
    assert await repo.pending_sync() == []
    async with session_maker() as session:
        row = await session.get(CreatorOpsSyncOutbox, outbox_id)
    assert row.status == "synced"
    assert row.remote_record_id == "rec-1"
    assert row.synced_at is not None


@pytest.mark.asyncio
async def test_save_content_with_outbox_is_atomic(repository):
    repo, session_maker = repository
    record = MetricRecord(
        platform=Platform.DOUYIN,
        profile_key="%s_use_data_dir",
        content_key="video-1",
        title="Video",
        published_at=datetime(2026, 7, 20, 10, 0),
        snapshot_date=date(2026, 7, 21),
        metrics={"浏览": 30},
    )

    snapshot_id, outbox_id = await repo.save_content_with_outbox(
        record,
        target_table="douyin_stats",
        business_key="dy:%s_use_data_dir:video-1:2026-07-21",
        payload={"标题": "Video", "浏览": 30},
    )

    async with session_maker() as session:
        snapshot = await session.get(CreatorContentMetricSnapshot, snapshot_id)
        outbox = await session.get(CreatorOpsSyncOutbox, outbox_id)
    assert snapshot is not None
    assert outbox.status == "pending"
