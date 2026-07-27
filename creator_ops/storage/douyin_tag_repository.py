from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_session import get_session

from .models import DouyinTagAweme

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_UPDATABLE_COLUMNS = tuple(
    column.name
    for column in DouyinTagAweme.__table__.columns
    if column.name not in {"id", "created_at", "updated_at", "fetched_at"}
)


class DouyinTagRepository:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self.session_factory = session_factory or get_session

    async def upsert_many(self, rows: list[dict[str, Any]]) -> list[int]:
        saved_ids: list[int] = []
        async with self.session_factory() as session:
            for values in rows:
                row = await session.scalar(
                    select(DouyinTagAweme).where(
                        DouyinTagAweme.tag_id == values["tag_id"],
                        DouyinTagAweme.aweme_id == values["aweme_id"],
                        DouyinTagAweme.author_id == values["author_id"],
                    )
                )
                now = datetime.now()
                if row is None:
                    row = DouyinTagAweme(
                        **{
                            name: values.get(name)
                            for name in _UPDATABLE_COLUMNS
                        },
                        fetched_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                else:
                    for name in _UPDATABLE_COLUMNS:
                        setattr(row, name, values.get(name))
                    row.fetched_at = now
                    row.updated_at = now
                await session.flush()
                saved_ids.append(int(row.id))
        return saved_ids

    async def list_recent_aweme_ids(
        self,
        tag_ids: tuple[str, ...],
        *,
        published_after: date,
    ) -> tuple[str, ...]:
        if not tag_ids:
            return ()
        boundary = datetime.combine(published_after, time.min)
        async with self.session_factory() as session:
            result = await session.scalars(
                select(DouyinTagAweme.aweme_id)
                .where(
                    DouyinTagAweme.tag_id.in_(tag_ids),
                    DouyinTagAweme.published_at >= boundary,
                )
                .distinct()
            )
            return tuple(sorted(set(result.all())))
