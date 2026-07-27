from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


DOUYIN_COMMENT_FIELD_MAP = {
    "id": "id",
    "user_id": "用户ID",
    "sec_uid": "sec_uid",
    "short_user_id": "用户短ID",
    "user_unique_id": "user_unique_id",
    "nickname": "用户昵称",
    "avatar": "avatar",
    "user_signature": "user_signature",
    "ip_location": "ip_location",
    "comment_id": "评论ID",
    "aweme_id": "视频ID",
    "content": "评论内容",
    "like_count": "点赞数",
    "pictures": "评论图片列表",
}


def build_douyin_comment_payloads(
    comments: Iterable[Mapping[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    rows = [dict(comment) for comment in comments]
    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parent_id = _text(row.get("parent_comment_id"))
        if parent_id and parent_id != "0":
            children_by_parent[parent_id].append(row)

    payloads: list[tuple[str, dict[str, Any]]] = []
    for row in sorted(rows, key=_comment_sort_key):
        comment_id = _text(row.get("comment_id"))
        if not comment_id:
            continue
        parent_id = _text(row.get("parent_comment_id"))
        is_root = not parent_id or parent_id == "0"
        if is_root:
            replied = any(
                _is_novsight_reply(child)
                for child in children_by_parent.get(comment_id, [])
            )
        else:
            replied = _is_novsight_reply(row)
        payload = {
            target: _text(row.get(source))
            for source, target in DOUYIN_COMMENT_FIELD_MAP.items()
        }
        payload["评论时间"] = _format_timestamp(
            row.get("create_time")
        )
        payload["是否回复"] = "是" if replied else "否"
        payload["回复内容ID"] = "" if is_root else parent_id
        payloads.append((comment_id, payload))
    return payloads


def _is_novsight_reply(comment: Mapping[str, Any]) -> bool:
    return _text(comment.get("user_unique_id")).lower() == "novsight"


def _comment_sort_key(comment: Mapping[str, Any]) -> tuple[int, int]:
    return (
        _integer(comment.get("create_time")),
        _integer(comment.get("id")),
    )


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format_timestamp(value: Any) -> str:
    numeric = _integer(value)
    if not numeric:
        return ""
    if numeric > 10_000_000_000:
        numeric //= 1000
    return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d %H:%M:%S")
