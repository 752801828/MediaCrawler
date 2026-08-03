from __future__ import annotations

from typing import Any

from sqlalchemy import select

from database.db_session import get_session
from tools import utils


async def upsert_creator(model: Any, creator_item: dict[str, Any]) -> None:
    """Insert or update a creator ORM row by its original platform user ID."""

    user_id = str(creator_item.get("user_id") or "").strip()
    if not user_id:
        utils.logger.warning(
            f"[upsert_creator] missing user_id for {model.__tablename__}, skipped"
        )
        return
    creator_item["user_id"] = user_id
    async with get_session() as session:
        result = await session.execute(
            select(model).where(model.user_id == user_id)
        )
        creator = result.scalar_one_or_none()
        if creator is None:
            creator_item.setdefault("add_ts", utils.get_current_timestamp())
            session.add(model(**creator_item))
        else:
            for key, value in creator_item.items():
                setattr(creator, key, value)
        await session.commit()
