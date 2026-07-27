from datetime import date

from creator_ops.douyin_stats_comments import (
    build_douyin_stats_comment_filter,
    parse_douyin_stats_comment_targets,
)


def test_filter_uses_strict_boundary_and_required_link():
    assert build_douyin_stats_comment_filter(date(2026, 7, 1)) == (
        "AND("
        'CurrentValue.[创建时间] > "2026-07-01 00:00:00", '
        'CurrentValue.[作品链接] != ""'
        ")"
    )


def test_targets_are_strictly_filtered_and_deduplicated():
    records = [
        {
            "record_id": "boundary",
            "fields": {
                "创建时间": "2026-07-01 00:00:00",
                "作品链接": "https://www.douyin.com/video/7000000000000000001",
            },
        },
        {
            "record_id": "valid",
            "fields": {
                "创建时间": "2026-07-01 00:00:01",
                "作品链接": "https://www.douyin.com/video/7000000000000000002",
            },
        },
        {
            "record_id": "duplicate",
            "fields": {
                "创建时间": "2026-07-02 10:00:00",
                "作品链接": (
                    "https://www.douyin.com/video/7000000000000000002"
                    "?previous_page=web_code_link"
                ),
            },
        },
        {
            "record_id": "invalid",
            "fields": {
                "创建时间": "2026-07-03 10:00:00",
                "作品链接": "https://example.com/video/7000000000000000003",
            },
        },
    ]

    assert parse_douyin_stats_comment_targets(
        records,
        after=date(2026, 7, 1),
    ) == ("7000000000000000002",)
