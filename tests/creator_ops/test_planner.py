from pathlib import Path

from creator_ops.config import FeishuSettings, MysqlSettings, Settings
from creator_ops.domain import Platform, TaskKind
from creator_ops.planner import build_plan


def settings_for(tmp_path: Path) -> Settings:
    for name in (
        "xhs_use_data_dir",
        "xhs_text_data_dir",
        "xhs_text_2_data_dir",
        "dy_use_data_dir",
    ):
        (tmp_path / name).mkdir()
    return Settings(
        browser_data_root=tmp_path,
        mysql=MysqlSettings("localhost", 3306, "root", "secret", "media_crawler"),
        feishu=FeishuSettings(
            app_id="app-id",
            app_secret="secret",
            app_token="app-token",
            link_table_id="link",
            link_view_id="link-view",
            user_table_id="user",
            user_view_id="user-view",
            account_table_id="account",
            account_view_id="account-view",
            xhs_stats_table_id="xhs-stats",
            douyin_stats_table_id="dy-stats",
            comment_table_id="comments",
            comment_view_id="comment-view",
            douyin_creator_table_id="dy-creator",
            xhs_creator_table_id="xhs-creator",
            history_view_id="history-view",
        ),
    )


def test_build_plan_maps_main_water_and_disabled_accounts(tmp_path: Path):
    accounts = [
        {
            "record_id": "account-1",
            "fields": {
                "ID": [{"text": "%s_use_data_dir"}],
                "平台": "小红书",
                "主账号": True,
                "水号": False,
            },
        },
        {
            "record_id": "account-2",
            "fields": {
                "ID": "%s_text_data_dir",
                "平台": "小红书",
                "主账号": False,
                "水号": True,
            },
        },
        {
            "record_id": "account-3",
            "fields": {
                "ID": "%s_u1_data_dir",
                "平台": "抖音",
                "主账号": False,
                "水号": False,
            },
        },
    ]
    links = [
        {
            "record_id": "link-1",
            "fields": {
                "平台": "小红书",
                "是否查询": True,
                "链接": [{"link": "https://www.xiaohongshu.com/explore/note-1"}],
                "是否查询评论": True,
            },
        }
    ]

    plan = build_plan(settings_for(tmp_path), accounts, links, [])

    assert [(task.platform, task.kind) for task in plan] == [
        (Platform.XHS, TaskKind.CREATOR_METRICS),
        (Platform.XHS, TaskKind.CONTENT_DETAIL),
    ]
    assert plan[0].profile.path.name == "xhs_use_data_dir"
    assert plan[1].profile.path.name == "xhs_text_data_dir"
    assert plan[1].targets == ("https://www.xiaohongshu.com/explore/note-1",)
    assert plan[1].get_comments is True


def test_link_groups_rotate_across_water_profiles(tmp_path: Path):
    accounts = [
        {"fields": {"ID": "%s_text_data_dir", "平台": "小红书", "水号": True}},
        {"fields": {"ID": "%s_text_2_data_dir", "平台": "小红书", "水号": True}},
    ]
    links = [
        {
            "fields": {
                "平台": "小红书",
                "是否查询": True,
                "链接": [{"link": "note-with-comments"}],
                "是否查询评论": True,
            }
        },
        {
            "fields": {
                "平台": "小红书",
                "是否查询": True,
                "链接": [{"link": "note-without-comments"}],
                "是否查询评论": False,
            }
        },
    ]

    plan = build_plan(settings_for(tmp_path), accounts, links, [])

    assert [task.profile.path.name for task in plan] == [
        "xhs_text_data_dir",
        "xhs_text_2_data_dir",
    ]


def test_user_task_never_persists_public_profile(tmp_path: Path):
    accounts = [
        {"fields": {"ID": "%s_text_data_dir", "平台": "小红书", "水号": True}}
    ]
    users = [
        {
            "fields": {
                "平台": "小红书",
                "是否查询": True,
                "ID": [{"text": "public-user-id"}],
            }
        }
    ]

    plan = build_plan(settings_for(tmp_path), accounts, [], users)

    assert len(plan) == 1
    assert plan[0].kind is TaskKind.CREATOR_CONTENT
    assert plan[0].targets == ("public-user-id",)
    assert plan[0].persist_profile is False


def test_tag_records_are_deduplicated_and_use_douyin_water_account(tmp_path: Path):
    accounts = [
        {
            "fields": {
                "ID": "%s_use_data_dir",
                "平台": "抖音",
                "主账号": True,
                "水号": False,
            }
        },
        {
            "fields": {
                "ID": "%s_use_data_dir",
                "平台": "抖音",
                "主账号": False,
                "水号": True,
            }
        },
    ]
    tags = [
        {
            "record_id": "tag-1",
            "fields": {
                "tag": "#越野射灯",
                "链接": "https://www.douyin.com/hashtag/7322391300177987638",
            },
        },
        {
            "record_id": "tag-2",
            "fields": {
                "tag": "duplicate",
                "链接": "https://www.douyin.com/hashtag/7322391300177987638?from=web",
            },
        },
    ]

    plan = build_plan(settings_for(tmp_path), accounts, [], [], tags)
    tag_tasks = [task for task in plan if task.kind is TaskKind.DOUYIN_TAG_CONTENT]

    assert len(tag_tasks) == 1
    assert tag_tasks[0].profile.is_water is True
    assert tag_tasks[0].profile.is_main is False
    assert tag_tasks[0].tag_targets[0].tag_id == "7322391300177987638"
    assert tag_tasks[0].get_comments is True
    assert tag_tasks[0].published_after is not None


def test_tag_task_never_falls_back_to_main_account(tmp_path: Path):
    accounts = [
        {
            "fields": {
                "ID": "%s_use_data_dir",
                "平台": "抖音",
                "主账号": True,
                "水号": False,
            }
        }
    ]
    tags = [
        {
            "fields": {
                "tag": "tag",
                "链接": "https://www.douyin.com/hashtag/7322391300177987638",
            }
        }
    ]

    import pytest
    from creator_ops.planner import PlanningError

    with pytest.raises(PlanningError, match="water account"):
        build_plan(settings_for(tmp_path), accounts, [], [], tags)


def test_stats_comment_task_deduplicates_and_uses_douyin_water_account(
    tmp_path: Path,
):
    accounts = [
        {
            "fields": {
                "ID": "%s_use_data_dir",
                "平台": "抖音",
                "主账号": True,
            }
        },
        {
            "fields": {
                "ID": "%s_text_data_dir",
                "平台": "抖音",
                "水号": True,
            }
        },
    ]
    stats_records = [
        {
            "fields": {
                "创建时间": "2026-07-02 10:00:00",
                "作品链接": "https://www.douyin.com/video/7000000000000000001",
            }
        },
        {
            "fields": {
                "创建时间": "2026-07-03 10:00:00",
                "作品链接": "https://www.douyin.com/video/7000000000000000001",
            }
        },
    ]

    plan = build_plan(
        settings_for(tmp_path),
        accounts,
        [],
        [],
        [],
        stats_records,
    )
    task = next(
        task
        for task in plan
        if task.kind is TaskKind.DOUYIN_STATS_COMMENTS
    )

    assert task.targets == ("7000000000000000001",)
    assert task.profile.path.name == "dy_text_data_dir"
    assert task.profile.is_water is True
    assert task.get_comments is True
