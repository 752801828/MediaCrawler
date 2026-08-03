from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from database.schema_migrations import migrate_missing_schema


@pytest.mark.asyncio
async def test_migration_adds_full_fields_without_rewriting_existing_rows(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            """
            CREATE TABLE douyin_aweme_comment (
                id INTEGER PRIMARY KEY,
                comment_id VARCHAR(255),
                aweme_id VARCHAR(255),
                content TEXT
            )
            """
        )
        await connection.exec_driver_sql(
            """
            INSERT INTO douyin_aweme_comment (id, comment_id, aweme_id, content)
            VALUES (1, 'legacy-comment', 'legacy-aweme', 'keep me')
            """
        )

    first = await migrate_missing_schema(engine)

    async with engine.connect() as connection:
        columns, tables, row = await connection.run_sync(
            lambda sync_connection: (
                {
                    item["name"]
                    for item in inspect(sync_connection).get_columns(
                        "douyin_aweme_comment"
                    )
                },
                set(inspect(sync_connection).get_table_names()),
                sync_connection.exec_driver_sql(
                    """
                    SELECT id, comment_id, aweme_id, content
                    FROM douyin_aweme_comment
                    WHERE id = 1
                    """
                ).one(),
            )
        )

    assert {
        "user_id",
        "sec_uid",
        "short_user_id",
        "user_unique_id",
        "nickname",
        "avatar",
        "user_signature",
        "ip_location",
        "creator_hash",
    }.issubset(columns)
    assert {
        "dy_creator",
        "xhs_creator",
        "kuaishou_creator",
        "weibo_creator",
        "tieba_creator",
        "zhihu_creator",
        "bilibili_up_info",
        "bilibili_contact_info",
    }.issubset(tables)
    assert tuple(row) == (1, "legacy-comment", "legacy-aweme", "keep me")
    assert "douyin_aweme_comment.user_id" in first.added_columns

    second = await migrate_missing_schema(engine)
    assert second.created_tables == ()
    assert second.added_columns == ()
    assert second.created_indexes == ()
    await engine.dispose()
