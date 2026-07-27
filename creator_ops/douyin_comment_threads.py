from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


DOUYIN_ROOT_FIELD_MAP = {
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


def build_douyin_root_comment_payloads(
    comments: Iterable[Mapping[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    rows = [dict(comment) for comment in comments]
    roots: list[dict[str, Any]] = []
    children_by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parent_id = _text(row.get("parent_comment_id"))
        if not parent_id or parent_id == "0":
            roots.append(row)
        else:
            children_by_root[parent_id].append(row)

    payloads: list[tuple[str, dict[str, Any]]] = []
    for root in sorted(roots, key=_comment_sort_key):
        comment_id = _text(root.get("comment_id"))
        if not comment_id:
            continue
        children = sorted(
            children_by_root.get(comment_id, []),
            key=_comment_sort_key,
        )
        replied = any(_is_novsight_reply(child) for child in children)
        payload = {
            target: _text(root.get(source))
            for source, target in DOUYIN_ROOT_FIELD_MAP.items()
        }
        payload["评论时间"] = _format_timestamp(
            root.get("create_time")
        )
        payload["是否回复"] = "是" if replied else "否"
        payload["回复内容"] = (
            _build_conversation_chain(root, children) if replied else ""
        )
        payloads.append((comment_id, payload))
    return payloads


def _is_novsight_reply(comment: Mapping[str, Any]) -> bool:
    return _text(comment.get("user_unique_id")).lower() == "novsight"


def _build_conversation_chain(
    root: Mapping[str, Any],
    children: list[Mapping[str, Any]],
) -> str:
    entries = sorted([root, *children], key=_comment_sort_key)
    return "\n".join(
        f"{_line_text(entry.get('nickname'))}：{_line_text(entry.get('content'))}"
        for entry in entries
    )


def _comment_sort_key(comment: Mapping[str, Any]) -> tuple[int, int]:
    return (
        _integer(comment.get("create_time")),
        _integer(comment.get("id")),
    )


def _line_text(value: Any) -> str:
    return re.sub(r"[\r\n]+", " ", _text(value)).strip()


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
