from __future__ import annotations

from collections import OrderedDict, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from creator_ops.config import Settings
from creator_ops.douyin_stats_comments import (
    DEFAULT_DOUYIN_COMMENTS_AFTER,
    parse_douyin_stats_comment_targets,
)
from creator_ops.douyin_tags import parse_douyin_tag_target
from creator_ops.domain import AccountProfile, Platform, Task, TaskKind
from creator_ops.feishu.schema import PLATFORM_LABELS
from tools import utils


class PlanningError(ValueError):
    """Raised when active Feishu tasks cannot be assigned safely."""


def build_plan(
    settings: Settings,
    account_records: Iterable[Mapping[str, Any]],
    link_records: Iterable[Mapping[str, Any]],
    user_records: Iterable[Mapping[str, Any]],
    tag_records: Iterable[Mapping[str, Any]] = (),
    stats_comment_records: Iterable[Mapping[str, Any]] = (),
    stats_comment_after: date = DEFAULT_DOUYIN_COMMENTS_AFTER,
) -> list[Task]:
    profiles = _parse_profiles(settings, account_records)
    main_profiles: dict[Platform, list[AccountProfile]] = defaultdict(list)
    water_profiles: dict[Platform, list[AccountProfile]] = defaultdict(list)
    for profile in profiles:
        if profile.is_main:
            main_profiles[profile.platform].append(profile)
        if profile.is_water:
            water_profiles[profile.platform].append(profile)

    plan: list[Task] = []
    for profile in profiles:
        if profile.is_main:
            plan.append(
                Task(
                    task_id=f"creator-metrics:{profile.platform.value}:{profile.template}",
                    platform=profile.platform,
                    kind=TaskKind.CREATOR_METRICS,
                    profile=profile,
                    persist_profile=True,
                )
            )

    profile_positions: dict[Platform, int] = defaultdict(int)
    link_groups: OrderedDict[tuple[Platform, bool], list[str]] = OrderedDict()
    for record in link_records:
        fields = record.get("fields") or {}
        if not _as_bool(fields.get("是否查询")):
            continue
        platform = _platform(fields.get("平台"))
        if platform is None:
            continue
        target = _link_target(fields, platform)
        if not target:
            continue
        key = (platform, _as_bool(fields.get("是否查询评论")))
        link_groups.setdefault(key, []).append(target)

    for (platform, get_comments), targets in link_groups.items():
        profile = _next_water_profile(water_profiles, profile_positions, platform)
        plan.append(
            Task(
                task_id=f"content-detail:{platform.value}:{int(get_comments)}:{len(plan)}",
                platform=platform,
                kind=TaskKind.CONTENT_DETAIL,
                profile=profile,
                targets=tuple(targets),
                get_comments=get_comments,
                persist_profile=False,
            )
        )

    user_groups: OrderedDict[Platform, list[str]] = OrderedDict()
    for record in user_records:
        fields = record.get("fields") or {}
        if not _as_bool(fields.get("是否查询")):
            continue
        platform = _platform(fields.get("平台"))
        if platform is None:
            continue
        target = _field_text(fields.get("ID") or fields.get("标识"))
        if target:
            user_groups.setdefault(platform, []).append(target)

    for platform, targets in user_groups.items():
        profile = _next_water_profile(water_profiles, profile_positions, platform)
        plan.append(
            Task(
                task_id=f"creator-content:{platform.value}:{len(plan)}",
                platform=platform,
                kind=TaskKind.CREATOR_CONTENT,
                profile=profile,
                targets=tuple(targets),
                get_comments=False,
                persist_profile=False,
            )
        )

    seen_tag_ids: set[str] = set()
    for record in tag_records:
        fields = record.get("fields") or {}
        try:
            target = parse_douyin_tag_target(
                fields.get("tag"),
                fields.get("链接"),
            )
        except ValueError:
            utils.logger.warning(
                "[creator_ops.build_plan] Ignore invalid Douyin Tag record_id=%s",
                record.get("record_id") or record.get("id") or "unknown",
            )
            continue
        if target.tag_id in seen_tag_ids:
            continue
        seen_tag_ids.add(target.tag_id)
        profile = _next_water_profile(
            water_profiles,
            profile_positions,
            Platform.DOUYIN,
        )
        plan.append(
            Task(
                task_id=f"douyin-tag:{target.tag_id}",
                platform=Platform.DOUYIN,
                kind=TaskKind.DOUYIN_TAG_CONTENT,
                profile=profile,
                get_comments=True,
                persist_profile=False,
                tag_targets=(target,),
                published_after=stats_comment_after,
            )
        )

    stats_comment_targets = parse_douyin_stats_comment_targets(
        stats_comment_records,
        after=stats_comment_after,
    )
    if stats_comment_targets:
        profile = _next_water_profile(
            water_profiles,
            profile_positions,
            Platform.DOUYIN,
        )
        plan.append(
            Task(
                task_id=(
                    "douyin-stats-comments:"
                    f"{stats_comment_after.isoformat()}"
                ),
                platform=Platform.DOUYIN,
                kind=TaskKind.DOUYIN_STATS_COMMENTS,
                profile=profile,
                targets=stats_comment_targets,
                get_comments=True,
                persist_profile=False,
            )
        )

    return plan


def _parse_profiles(
    settings: Settings,
    records: Iterable[Mapping[str, Any]],
) -> list[AccountProfile]:
    profiles: list[AccountProfile] = []
    for record in records:
        fields = record.get("fields") or {}
        platform = _platform(fields.get("平台"))
        template = _field_text(fields.get("ID"))
        if platform is None or not template:
            continue
        has_flags = "主账号" in fields or "水号" in fields
        is_main = _as_bool(fields.get("主账号"))
        is_water = _as_bool(fields.get("水号")) if has_flags else True
        if not is_main and not is_water:
            continue
        profiles.append(
            AccountProfile(
                platform=platform,
                template=template,
                path=settings.profile_path(template, platform.value),
                is_main=is_main,
                is_water=is_water,
            )
        )
    return profiles


def _next_water_profile(
    profiles: Mapping[Platform, list[AccountProfile]],
    positions: dict[Platform, int],
    platform: Platform,
) -> AccountProfile:
    options = profiles.get(platform) or []
    if not options:
        raise PlanningError(f"no active water account for platform {platform.value}")
    position = positions[platform]
    positions[platform] += 1
    return options[position % len(options)]


def _platform(value: Any) -> Platform | None:
    normalized = PLATFORM_LABELS.get(str(value), str(value))
    try:
        return Platform(normalized)
    except ValueError:
        return None


def _link_target(fields: Mapping[str, Any], platform: Platform) -> str:
    if "标识" in fields:
        return _field_text(fields.get("标识"))
    if platform is Platform.XHS:
        return _field_text(fields.get("链接"))
    return _field_text(fields.get("ID"))


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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}
