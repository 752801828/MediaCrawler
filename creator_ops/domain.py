from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


class Platform(str, Enum):
    XHS = "xhs"
    DOUYIN = "dy"


class TaskKind(str, Enum):
    CREATOR_METRICS = "creator_metrics"
    CONTENT_DETAIL = "content_detail"
    CREATOR_CONTENT = "creator_content"


@dataclass(frozen=True)
class AccountProfile:
    platform: Platform
    template: str
    path: Path
    is_main: bool
    is_water: bool


@dataclass(frozen=True)
class Task:
    task_id: str
    platform: Platform
    kind: TaskKind
    profile: AccountProfile
    targets: tuple[str, ...] = ()
    get_comments: bool = False
    persist_profile: bool = False


@dataclass(frozen=True)
class MetricRecord:
    platform: Platform
    profile_key: str
    content_key: str
    title: str
    published_at: datetime | None
    snapshot_date: date
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    success: bool
    records: tuple[MetricRecord, ...] = ()
    error: str = ""
