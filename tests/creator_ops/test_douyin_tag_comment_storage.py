from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import (
    Base,
    DouyinAwemeComment,
    DouyinTagAwemeComment,
)
from store.douyin import _store_impl
from store.douyin._store_impl import DouyinDbStoreImplement
from var import douyin_comment_store_var


@pytest.mark.asyncio
async def test_tag_scope_routes_comments_to_isolated_table(
    tmp_path,
    monkeypatch,
):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'comments.db'}"
    )
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

    monkeypatch.setattr(_store_impl, "get_session", session_factory)
    store = DouyinDbStoreImplement()
    base = {
        "comment_id": "comment-1",
        "aweme_id": "video-1",
        "content": "ordinary",
        "parent_comment_id": "0",
    }
    await store.store_comment(dict(base))

    token = douyin_comment_store_var.set("tag")
    try:
        await store.store_comment({**base, "content": "tag-updated"})
        await store.store_comment({**base, "content": "tag-updated-again"})
        await store.store_comment(
            {
                **base,
                "aweme_id": "video-2",
                "content": "same-comment-id-other-video",
            }
        )
    finally:
        douyin_comment_store_var.reset(token)

    async with session_maker() as session:
        ordinary_count = await session.scalar(
            select(func.count()).select_from(DouyinAwemeComment)
        )
        tag_count = await session.scalar(
            select(func.count()).select_from(DouyinTagAwemeComment)
        )
        first_tag = await session.scalar(
            select(DouyinTagAwemeComment).where(
                DouyinTagAwemeComment.aweme_id == "video-1"
            )
        )

    await engine.dispose()

    assert ordinary_count == 1
    assert tag_count == 2
    assert first_tag.content == "tag-updated-again"
