from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time
from typing import Any

from tools import utils


DEFAULT_DOUYIN_COMMENTS_AFTER = date(2026, 7, 1)
DOUYIN_VIDEO_ID_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?douyin\.com/video/(\d+)",
    re.IGNORECASE,
)


def build_douyin_stats_comment_filter(after: date) -> str:
    boundary = datetime.combine(after, time.min).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return (
        "AND("
        f'CurrentValue.[创建时间] > "{boundary}", '
        'CurrentValue.[作品链接] != ""'
        ")"
    )


def parse_douyin_stats_comment_targets(
    records: Iterable[Mapping[str, Any]],
    *,
    after: date,
) -> tuple[str, ...]:
    boundary = datetime.combine(after, time.min)
    targets: list[str] = []
    seen: set[str] = set()
    for record in records:
        fields = record.get("fields") or {}
        published_at = _parse_datetime(fields.get("创建时间"))
        if published_at is None or published_at <= boundary:
            continue
        content_url = _field_text(fields.get("作品链接"))
        match = DOUYIN_VIDEO_ID_PATTERN.search(content_url)
        if not match:
            if content_url:
                utils.logger.warning(
                    "[creator_ops.douyin_stats_comments] "
                    "Ignore invalid Douyin work URL record_id=%s",
                    record.get("record_id") or record.get("id") or "unknown",
                )
            continue
        work_id = match.group(1)
        if work_id in seen:
            continue
        seen.add(work_id)
        targets.append(work_id)
    return tuple(targets)


def _parse_datetime(value: Any) -> datetime | None:
    text = _field_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _field_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, Mapping):
            for key in ("link", "text", "value"):
                if first.get(key):
                    return str(first[key]).strip()
        return str(first).strip()
    if value is None:
        return ""
    return str(value).strip()
