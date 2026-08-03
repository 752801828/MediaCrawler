from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from creator_ops.config import Settings
from creator_ops.domain import Platform
from creator_ops.platforms.base import parse_metric_number
from creator_ops.storage import CreatorOpsRepository
from database import db
from database.db_session import get_session


@dataclass(frozen=True)
class LegacyAccountSnapshot:
    platform: Platform
    profile_key: str
    snapshot_date: date
    metrics: dict[str, int | float]


@dataclass(frozen=True)
class LegacyMigrationSummary:
    scanned: int = 0
    eligible: int = 0
    imported: int = 0


def eligible_legacy_creator_row(
    row: Mapping[str, Any],
    *,
    owned_user_ids: set[str],
) -> bool:
    user_id = str(row.get("user_id") or "").strip()
    return bool(user_id and user_id in owned_user_ids)


def legacy_row_to_snapshot(
    platform: Platform,
    row: Mapping[str, Any],
    *,
    owned_user_ids: set[str],
) -> LegacyAccountSnapshot | None:
    if not eligible_legacy_creator_row(row, owned_user_ids=owned_user_ids):
        return None
    user_id = str(row["user_id"])
    allowed_fields = ["follows", "fans", "interaction"]
    if platform is Platform.DOUYIN:
        allowed_fields.append("videos_count")
    metrics = {field: _numeric(row.get(field)) for field in allowed_fields}
    digest = hashlib.sha256(
        f"{platform.value}:{user_id}".encode("utf-8")
    ).hexdigest()[:20]
    return LegacyAccountSnapshot(
        platform=platform,
        profile_key=f"legacy-{platform.value}-{digest}",
        snapshot_date=_record_date(row.get("record_date")),
        metrics=metrics,
    )


async def migrate_legacy_creator_history(
    settings: Settings,
    *,
    owned_user_ids: set[str],
    apply: bool = False,
    repository: CreatorOpsRepository | None = None,
) -> LegacyMigrationSummary:
    normalized_ids = {item.strip() for item in owned_user_ids if item.strip()}
    if not normalized_ids:
        raise ValueError("at least one --owned-user-id is required")
    _configure_mysql(settings)
    await db.init_db("db")
    repository = repository or CreatorOpsRepository()

    scanned = 0
    eligible = 0
    imported = 0
    for platform, query in (
        (
            Platform.XHS,
            "SELECT user_id, record_date, follows, fans, interaction "
            "FROM xhs_creator_history",
        ),
        (
            Platform.DOUYIN,
            "SELECT user_id, record_date, follows, fans, interaction, videos_count "
            "FROM dy_creator_history",
        ),
    ):
        rows = await _legacy_rows(query)
        scanned += len(rows)
        for row in rows:
            snapshot = legacy_row_to_snapshot(
                platform,
                row,
                owned_user_ids=normalized_ids,
            )
            if snapshot is None:
                continue
            eligible += 1
            if apply:
                await repository.upsert_account_snapshot(
                    platform=snapshot.platform.value,
                    profile_key=snapshot.profile_key,
                    snapshot_date=snapshot.snapshot_date,
                    metrics=snapshot.metrics,
                )
                imported += 1
    return LegacyMigrationSummary(
        scanned=scanned,
        eligible=eligible,
        imported=imported,
    )


async def _legacy_rows(query: str) -> list[Mapping[str, Any]]:
    try:
        async with get_session() as session:
            result = await session.execute(text(query))
            return list(result.mappings())
    except SQLAlchemyError:
        return []


def _configure_mysql(settings: Settings) -> None:
    import config
    from config.db_config import mysql_db_config

    mysql_db_config.clear()
    mysql_db_config.update(
        {
            "user": settings.mysql.user,
            "password": settings.mysql.password,
            "host": settings.mysql.host,
            "port": settings.mysql.port,
            "db_name": settings.mysql.database,
        }
    )
    config.SAVE_DATA_OPTION = "db"


def _numeric(value: Any) -> int | float:
    parsed = parse_metric_number(value)
    return parsed if isinstance(parsed, (int, float)) else 0


def _record_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("legacy creator row has invalid record_date") from exc
