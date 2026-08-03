from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Base


@dataclass(frozen=True)
class SchemaMigrationSummary:
    created_tables: tuple[str, ...] = ()
    added_columns: tuple[str, ...] = ()
    created_indexes: tuple[str, ...] = ()


async def migrate_missing_schema(engine: AsyncEngine) -> SchemaMigrationSummary:
    """Add ORM tables, nullable columns, and non-unique indexes that are missing.

    The migration is intentionally additive.  It never drops or rewrites an
    existing table, column, index, or row, so it can safely run before every
    crawler session.
    """

    async with engine.begin() as connection:
        return await connection.run_sync(_migrate_missing_schema_sync)


def _migrate_missing_schema_sync(connection: Connection) -> SchemaMigrationSummary:
    created_tables: list[str] = []
    added_columns: list[str] = []
    created_indexes: list[str] = []
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    preparer = connection.dialect.identifier_preparer

    for table in Base.metadata.sorted_tables:
        table_name = table.name
        if table_name not in existing_tables:
            table.create(connection, checkfirst=True)
            created_tables.append(table_name)
            existing_tables.add(table_name)
            continue

        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        for column in table.columns:
            if column.name in existing_columns:
                continue
            type_sql = column.type.compile(dialect=connection.dialect)
            statement = (
                f"ALTER TABLE {preparer.quote(table_name)} "
                f"ADD COLUMN {preparer.quote(column.name)} {type_sql} NULL"
            )
            connection.exec_driver_sql(statement)
            added_columns.append(f"{table_name}.{column.name}")
            existing_columns.add(column.name)

        # Do not introduce new unique constraints into a legacy database.  A
        # normal lookup index is safe and keeps restored user identifiers and
        # creator_hash queries usable.
        inspector = inspect(connection)
        existing_index_columns = {
            tuple(index.get("column_names") or ())
            for index in inspector.get_indexes(table_name)
        }
        for index in table.indexes:
            index_columns = tuple(column.name for column in index.columns)
            if index.unique or not index_columns:
                continue
            if index_columns in existing_index_columns:
                continue
            index.create(connection, checkfirst=True)
            created_indexes.append(index.name or f"{table_name}:{','.join(index_columns)}")
            existing_index_columns.add(index_columns)

    return SchemaMigrationSummary(
        created_tables=tuple(created_tables),
        added_columns=tuple(added_columns),
        created_indexes=tuple(created_indexes),
    )
