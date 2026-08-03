from datetime import date

from creator_ops.douyin_stats_comments import (
    build_douyin_stats_comment_filter,
    parse_douyin_stats_comment_targets,
    rolling_month_cutoff,
)


def test_filter_includes_boundary_and_requires_link():
    assert build_douyin_stats_comment_filter(date(2026, 7, 1)) == (
        "AND("
        'CurrentValue.[创建时间] >= "2026-07-01 00:00:00", '
        'CurrentValue.[作品链接] != ""'
        ")"
    )


def test_targets_include_boundary_and_are_deduplicated():
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
    ) == (
        "7000000000000000001",
        "7000000000000000002",
    )


def test_rolling_cutoff_uses_calendar_months_and_clamps_day():
    assert rolling_month_cutoff(date(2026, 7, 27)) == date(2026, 5, 27)
    assert rolling_month_cutoff(date(2026, 3, 31)) == date(2026, 1, 31)
    assert rolling_month_cutoff(date(2026, 5, 31), months=3) == date(
        2026,
        2,
        28,
    )
