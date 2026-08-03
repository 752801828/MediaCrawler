from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from creator_ops.domain import DouyinTagTarget


NOVSIGHT_UNIQUE_ID = "novsight"
EXCLUDED_DOUYIN_TAG_AUTHOR_IDS = frozenset({"1719260615816915"})

_TAG_AUTHOR_INTEGER_FIELDS = {
    "author_follower_count": ("max_follower_count", "follower_count"),
    "author_following_count": ("following_count",),
    "author_total_favorited": ("total_favorited",),
}

_TAG_AUTHOR_TEXT_FIELDS = {
    "author_nickname": "nickname",
    "author_unique_id": "unique_id",
    "author_account_region": "account_region",
    "author_custom_verify": "custom_verify",
    "author_enterprise_verify_reason": "enterprise_verify_reason",
    "sec_uid": "sec_uid",
}


def parse_douyin_tag_target(tag_name: Any, value: Any) -> DouyinTagTarget:
    url = _field_text(value)
    if not url:
        raise ValueError("douyin tag URL is empty")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc.lower() != "www.douyin.com":
        raise ValueError("unsupported douyin tag URL")
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) != 2 or segments[0] != "hashtag" or not segments[1].isdigit():
        raise ValueError("invalid douyin hashtag path")
    tag_id = segments[1]
    return DouyinTagTarget(
        tag_id=tag_id,
        tag_name=_field_text(tag_name),
        tag_url=f"https://www.douyin.com/hashtag/{tag_id}",
    )


def extract_douyin_tag_aweme(
    target: DouyinTagTarget,
    aweme: dict[str, Any],
    *,
    source_cursor: int,
) -> dict[str, Any]:
    author = aweme.get("author") or {}
    statistics = aweme.get("statistics") or {}
    video = aweme.get("video") or {}
    author_id = douyin_tag_author_id(aweme)
    if not aweme.get("aweme_id") or not author_id:
        raise ValueError("douyin tag aweme is missing unique identifiers")
    create_time = _int_or_none(aweme.get("create_time"))
    return {
        "tag_id": target.tag_id,
        "tag_name": target.tag_name,
        "tag_url": target.tag_url,
        "aweme_id": str(aweme["aweme_id"]),
        "author_id": author_id,
        "sec_uid": _field_text(author.get("sec_uid")),
        "source_cursor": int(source_cursor),
        "title": _field_text(aweme.get("item_title") or aweme.get("caption")),
        "description": _field_text(aweme.get("desc")),
        "aweme_type": _int_or_none(aweme.get("aweme_type")),
        "media_type": _int_or_none(aweme.get("media_type")),
        "published_at": datetime.fromtimestamp(create_time) if create_time else None,
        "region": _field_text(aweme.get("region")),
        "share_url": _field_text(
            aweme.get("share_url")
            or (aweme.get("share_info") or {}).get("share_url")
        ),
        "duration_ms": _int_or_none(video.get("duration")),
        "width": _int_or_none(video.get("width")),
        "height": _int_or_none(video.get("height")),
        "cover_url": _first_url(video.get("cover")),
        "play_url": _first_url(video.get("play_addr")),
        "author_nickname": _field_text(author.get("nickname")),
        "author_unique_id": _field_text(author.get("unique_id")),
        "author_account_region": _field_text(author.get("account_region")),
        "author_custom_verify": _field_text(author.get("custom_verify")),
        "author_enterprise_verify_reason": _field_text(
            author.get("enterprise_verify_reason")
        ),
        "author_follower_count": _positive_int_or_none(
            author.get("follower_count")
        ),
        "author_following_count": _positive_int_or_none(
            author.get("following_count")
        ),
        "author_total_favorited": _positive_int_or_none(
            author.get("total_favorited")
        ),
        "play_count": _positive_int_or_none(
            statistics.get("play_count")
        ),
        "digg_count": _int_or_none(statistics.get("digg_count")),
        "comment_count": _int_or_none(statistics.get("comment_count")),
        "share_count": _int_or_none(statistics.get("share_count")),
        "collect_count": _int_or_none(statistics.get("collect_count")),
        "exposure_count": _int_or_none(statistics.get("exposure_count")),
        "recommend_count": _int_or_none(statistics.get("recommend_count")),
        "text_extra_json": _json(aweme.get("text_extra") or []),
        "video_tag_json": _json(aweme.get("video_tag") or []),
        "raw_aweme_json": _json(aweme),
    }


def enrich_douyin_tag_aweme_row(
    row: dict[str, Any],
    *,
    creator_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = dict(row)
    creator = creator_detail if isinstance(creator_detail, dict) else {}
    creator_author = creator.get("user") or creator.get("user_info") or {}

    for destination, source_fields in _TAG_AUTHOR_INTEGER_FIELDS.items():
        if not _is_missing_count(enriched.get(destination)):
            continue
        candidate = _first_positive_count(
            creator_author,
            source_fields=source_fields,
        )
        if candidate is not None:
            enriched[destination] = candidate

    for destination, source in _TAG_AUTHOR_TEXT_FIELDS.items():
        if _field_text(enriched.get(destination)):
            continue
        candidate = _field_text(creator_author.get(source))
        if candidate:
            enriched[destination] = candidate

    return enriched


def douyin_tag_author_id(aweme: dict[str, Any]) -> str:
    author = aweme.get("author") or {}
    return (
        _field_text(author.get("uid"))
        or _nonzero_text(aweme.get("author_user_id"))
        or _field_text(author.get("sec_uid"))
    )


def is_excluded_douyin_tag_author_id(value: Any) -> bool:
    return _field_text(value) in EXCLUDED_DOUYIN_TAG_AUTHOR_IDS


def is_excluded_douyin_tag_aweme(aweme: dict[str, Any]) -> bool:
    return (
        is_excluded_douyin_tag_author_id(douyin_tag_author_id(aweme))
        or is_novsight_tag_aweme(aweme)
    )


def is_novsight_tag_aweme(aweme: dict[str, Any]) -> bool:
    author = aweme.get("author") or {}
    return (
        _field_text(author.get("unique_id")).casefold()
        == NOVSIGHT_UNIQUE_ID
    )


def _field_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            for key in ("link", "text", "value"):
                if first.get(key):
                    return str(first[key]).strip()
        return str(first).strip()
    if value is None:
        return ""
    return str(value).strip()


def _nonzero_text(value: Any) -> str:
    text = _field_text(value)
    return "" if text in {"", "0"} else text


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive_int_or_none(value: Any) -> int | None:
    parsed = _int_or_none(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _is_missing_count(value: Any) -> bool:
    parsed = _int_or_none(value)
    return parsed is None or parsed == 0


def _first_positive_count(
    *sources: dict[str, Any],
    source_fields: tuple[str, ...],
) -> int | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for field in source_fields:
            value = _positive_int_or_none(source.get(field))
            if value is not None:
                return value
    return None


def _first_url(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    urls = value.get("url_list") or []
    return _field_text(urls[0]) if urls else ""


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "DouyinTagTarget",
    "EXCLUDED_DOUYIN_TAG_AUTHOR_IDS",
    "douyin_tag_author_id",
    "enrich_douyin_tag_aweme_row",
    "extract_douyin_tag_aweme",
    "is_excluded_douyin_tag_author_id",
    "is_excluded_douyin_tag_aweme",
    "is_novsight_tag_aweme",
    "parse_douyin_tag_target",
]
