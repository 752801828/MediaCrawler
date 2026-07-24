from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from creator_ops.storage import DouyinTagAweme, DouyinTagRepository
from database.models import Base


def test_douyin_tag_aweme_has_three_field_unique_key():
    constraints = [
        item
        for item in DouyinTagAweme.__table__.constraints
        if isinstance(item, UniqueConstraint)
    ]
    columns = {tuple(column.name for column in item.columns) for item in constraints}

    assert ("tag_id", "aweme_id", "author_id") in columns


@pytest_asyncio.fixture
async def tag_repository(tmp_path: Path):
    database_path = tmp_path / "douyin-tag.db"
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

    yield DouyinTagRepository(session_factory=session_factory), session_maker
    await engine.dispose()


def tag_row(**overrides):
    row = {
        "tag_id": "tag-1",
        "tag_name": "Tag",
        "tag_url": "https://www.douyin.com/hashtag/1",
        "aweme_id": "aweme-1",
        "author_id": "author-1",
        "sec_uid": "sec-1",
        "source_cursor": 0,
        "title": "First",
        "description": "",
        "aweme_type": 4,
        "media_type": 1,
        "published_at": None,
        "region": "",
        "share_url": "",
        "duration_ms": 1000,
        "width": 1080,
        "height": 1920,
        "cover_url": "",
        "play_url": "",
        "author_nickname": "Author",
        "author_account_region": "",
        "author_custom_verify": "",
        "author_enterprise_verify_reason": "",
        "author_follower_count": 10,
        "author_following_count": 2,
        "author_total_favorited": 50,
        "play_count": 100,
        "digg_count": 10,
        "comment_count": 2,
        "share_count": 1,
        "collect_count": 3,
        "exposure_count": 110,
        "recommend_count": 5,
        "text_extra_json": "[]",
        "video_tag_json": "[]",
        "raw_aweme_json": '{"aweme_id":"aweme-1"}',
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_tag_repository_updates_same_three_field_key(tag_repository):
    repository, session_maker = tag_repository

    first_ids = await repository.upsert_many([tag_row()])
    second_ids = await repository.upsert_many(
        [tag_row(title="Updated", play_count=200, source_cursor=12)]
    )

    assert first_ids == second_ids
    async with session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(DouyinTagAweme))
        row = await session.scalar(select(DouyinTagAweme))
    assert count == 1
    assert row.title == "Updated"
    assert row.play_count == 200
    assert row.source_cursor == 12
    assert row.created_at <= row.updated_at


@pytest.mark.asyncio
async def test_tag_repository_keeps_different_authors_separate(tag_repository):
    repository, session_maker = tag_repository

    await repository.upsert_many(
        [
            tag_row(author_id="author-1"),
            tag_row(author_id="author-2"),
        ]
    )

    async with session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(DouyinTagAweme))
    assert count == 2
