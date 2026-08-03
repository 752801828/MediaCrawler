from datetime import date
from pathlib import Path

import pytest
from playwright._impl._errors import TargetClosedError

import config
from creator_ops.crawler_bridge import (
    _format_task_banner,
    crawler_config_scope,
    run_public_task,
)
from creator_ops.domain import (
    AccountProfile,
    DouyinTagTarget,
    Platform,
    Task,
    TaskKind,
)
from var import douyin_comment_store_var


def test_crawler_config_scope_restores_globals_after_error():
    original = {
        "PLATFORM": config.PLATFORM,
        "CRAWLER_TYPE": config.CRAWLER_TYPE,
        "USER_DATA_DIR": config.USER_DATA_DIR,
        "SAVE_DATA_OPTION": config.SAVE_DATA_OPTION,
        "ENABLE_GET_SUB_COMMENTS": config.ENABLE_GET_SUB_COMMENTS,
        "DOUYIN_COMMENT_FETCH_MODE": config.DOUYIN_COMMENT_FETCH_MODE,
        "XHS_SPECIFIED_NOTE_URL_LIST": list(config.XHS_SPECIFIED_NOTE_URL_LIST),
    }

    with pytest.raises(RuntimeError, match="stop"):
        with crawler_config_scope(
            platform=Platform.XHS,
            crawler_type="detail",
            user_data_dir="%s_text_data_dir",
            targets=("note-1",),
            get_comments=True,
        ):
            assert config.PLATFORM == "xhs"
            assert config.CRAWLER_TYPE == "detail"
            assert config.SAVE_DATA_OPTION == "db"
            assert config.is_get_sub_comments_enabled("xhs") is True
            assert config.DOUYIN_COMMENT_FETCH_MODE == "legacy"
            assert config.XHS_SPECIFIED_NOTE_URL_LIST == ["note-1"]
            raise RuntimeError("stop")

    for name, value in original.items():
        assert getattr(config, name) == value


@pytest.mark.parametrize(
    ("platform", "expected"),
    [(Platform.XHS, True), (Platform.DOUYIN, True)],
)
def test_crawler_scope_enables_sub_comments_for_supported_platforms(
    platform, expected
):
    with crawler_config_scope(
        platform=platform,
        crawler_type="detail",
        user_data_dir="%s_text_data_dir",
        targets=("target-1",),
        get_comments=True,
    ):
        assert config.is_get_sub_comments_enabled(platform.value) is expected


def test_crawler_scope_disables_sub_comments_when_comments_are_disabled():
    with crawler_config_scope(
        platform=Platform.DOUYIN,
        crawler_type="detail",
        user_data_dir="%s_text_data_dir",
        targets=("target-1",),
        get_comments=False,
    ):
        assert config.is_get_sub_comments_enabled("dy") is False
        assert config.DOUYIN_COMMENT_FETCH_MODE == "legacy"


def test_douyin_comment_scope_uses_water_api_mode():
    with crawler_config_scope(
        platform=Platform.DOUYIN,
        crawler_type="detail",
        user_data_dir="%s_text_data_dir",
        targets=("target-1",),
        get_comments=True,
    ):
        assert config.DOUYIN_COMMENT_FETCH_MODE == "water_api"


@pytest.mark.asyncio
async def test_run_public_task_uses_existing_loop_and_closes_crawler():
    events: list[str] = []

    class FakeCrawler:
        async def start(self):
            events.append("start")

        async def close(self):
            events.append("close")

    async def fake_init_db(db_type: str):
        events.append(f"db:{db_type}")

    task = Task(
        task_id="detail:xhs",
        platform=Platform.XHS,
        kind=TaskKind.CONTENT_DETAIL,
        profile=AccountProfile(
            platform=Platform.XHS,
            template="%s_text_data_dir",
            path=Path("D:/browser_data/xhs_text_data_dir"),
            is_main=False,
            is_water=True,
        ),
        targets=("note-1",),
        get_comments=True,
    )

    await run_public_task(
        task,
        crawler_factory=lambda _platform: FakeCrawler(),
        init_db=fake_init_db,
    )

    assert events == ["db:db", "start", "close"]


def test_douyin_comment_task_banner_identifies_account_and_targets(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", False)
    profile_path = Path("D:/browser_data/dy_text_data_dir")
    task = Task(
        task_id="detail:dy",
        platform=Platform.DOUYIN,
        kind=TaskKind.CONTENT_DETAIL,
        profile=AccountProfile(
            platform=Platform.DOUYIN,
            template="dy_text_data_dir",
            path=profile_path,
            is_main=False,
            is_water=True,
        ),
        targets=("7518846965308820762", "7496135103426481408"),
        get_comments=True,
    )

    banner = _format_task_banner(task)

    assert "平台：抖音" in banner
    assert "任务：作品详情 + 评论" in banner
    assert "账号类型：水号" in banner
    assert "账号模板：dy_text_data_dir" in banner
    assert f"账号目录：{profile_path.resolve()}" in banner
    assert "目标数量：2" in banner
    assert "1. 7518846965308820762" in banner
    assert "2. 7496135103426481408" in banner
    assert "一级评论：开启" in banner
    assert "二级评论：关闭" in banner
    assert "评论通道：水号接口优先（失败自动回退旧方式）" in banner


def test_xhs_creator_banner_removes_sensitive_query_parameters(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)
    task = Task(
        task_id="creator:xhs",
        platform=Platform.XHS,
        kind=TaskKind.CREATOR_CONTENT,
        profile=AccountProfile(
            platform=Platform.XHS,
            template="%s_main_data_dir",
            path=Path("D:/browser_data/xhs_main_data_dir"),
            is_main=True,
            is_water=False,
        ),
        targets=(
            "https://www.xiaohongshu.com/user/profile/user-1"
            "?xsec_token=private-token&source=feishu",
        ),
        get_comments=False,
    )

    banner = _format_task_banner(task)

    assert "平台：小红书" in banner
    assert "任务：创作者作品" in banner
    assert "账号类型：主账号" in banner
    assert "xsec_token" not in banner
    assert "private-token" not in banner
    assert "source=feishu" in banner
    assert "一级评论：关闭" in banner
    assert "二级评论：关闭" in banner


def test_stats_comment_task_banner_identifies_refresh_task(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)
    task = Task(
        task_id="douyin-stats-comments:2026-07-01",
        platform=Platform.DOUYIN,
        kind=TaskKind.DOUYIN_STATS_COMMENTS,
        profile=AccountProfile(
            platform=Platform.DOUYIN,
            template="%s_text_data_dir",
            path=Path("D:/browser_data/dy_text_data_dir"),
            is_main=False,
            is_water=True,
        ),
        targets=("7000000000000000001",),
        get_comments=True,
    )

    banner = _format_task_banner(task)

    assert "任务：作品表评论刷新" in banner
    assert "一级评论：开启" in banner
    assert "二级评论：开启" in banner


@pytest.mark.asyncio
async def test_stats_comment_task_uses_detail_mode_and_comments():
    observed = {}

    class FakeCrawler:
        async def start(self):
            observed["crawler_type"] = config.CRAWLER_TYPE
            observed["targets"] = list(config.DY_SPECIFIED_ID_LIST)
            observed["comments"] = config.ENABLE_GET_COMMENTS
            observed["sub_comments"] = (
                config.is_get_sub_comments_enabled("dy")
            )
            observed["comment_fetch_mode"] = (
                config.DOUYIN_COMMENT_FETCH_MODE
            )

        async def close(self):
            return None

    async def fake_init_db(_db_type: str):
        return None

    task = Task(
        task_id="douyin-stats-comments:2026-07-01",
        platform=Platform.DOUYIN,
        kind=TaskKind.DOUYIN_STATS_COMMENTS,
        profile=AccountProfile(
            platform=Platform.DOUYIN,
            template="%s_text_data_dir",
            path=Path("D:/browser_data/dy_text_data_dir"),
            is_main=False,
            is_water=True,
        ),
        targets=("7000000000000000001",),
        get_comments=True,
    )

    await run_public_task(
        task,
        crawler_factory=lambda _platform: FakeCrawler(),
        init_db=fake_init_db,
    )

    assert observed == {
        "crawler_type": "detail",
        "targets": ["7000000000000000001"],
        "comments": True,
        "sub_comments": True,
        "comment_fetch_mode": "water_api",
    }


@pytest.mark.asyncio
async def test_task_banner_is_emitted_before_database_and_browser(monkeypatch):
    events: list[str] = []

    class FakeCrawler:
        async def start(self):
            events.append("start")

        async def close(self):
            events.append("close")

    async def fake_init_db(_db_type: str):
        events.append("db")

    monkeypatch.setattr(
        "creator_ops.crawler_bridge._emit_task_banner",
        lambda _task: events.append("banner"),
    )
    task = Task(
        task_id="detail:dy",
        platform=Platform.DOUYIN,
        kind=TaskKind.CONTENT_DETAIL,
        profile=AccountProfile(
            platform=Platform.DOUYIN,
            template="dy_text_data_dir",
            path=Path("D:/browser_data/dy_text_data_dir"),
            is_main=False,
            is_water=True,
        ),
        targets=("7518846965308820762",),
        get_comments=True,
    )

    def crawler_factory(_platform: str):
        events.append("browser")
        return FakeCrawler()

    await run_public_task(
        task,
        crawler_factory=crawler_factory,
        init_db=fake_init_db,
    )

    assert events == ["banner", "db", "browser", "start", "close"]


@pytest.mark.asyncio
async def test_run_public_task_preserves_start_error_when_browser_already_closed():
    class FakeCrawler:
        async def start(self):
            raise RuntimeError("store failed")

        async def close(self):
            raise TargetClosedError("browser already closed")

    async def fake_init_db(_db_type: str):
        return None

    task = Task(
        task_id="detail:dy",
        platform=Platform.DOUYIN,
        kind=TaskKind.CONTENT_DETAIL,
        profile=AccountProfile(
            platform=Platform.DOUYIN,
            template="dy_text_data_dir",
            path=Path("D:/browser_data/dy_text_data_dir"),
            is_main=False,
            is_water=True,
        ),
        targets=("7518846965308820762",),
        get_comments=True,
    )

    with pytest.raises(RuntimeError, match="store failed"):
        await run_public_task(
            task,
            crawler_factory=lambda _platform: FakeCrawler(),
            init_db=fake_init_db,
        )


@pytest.mark.asyncio
async def test_tag_task_uses_independent_repository_and_tag_callback():
    saved_rows = []
    events = []
    fake_clients = []

    class FakeClient:
        def __init__(self):
            self.profile_calls = []
            fake_clients.append(self)

        async def get_user_info(self, sec_uid):
            self.profile_calls.append(sec_uid)
            if sec_uid == "sec-profile-fails":
                raise RuntimeError("profile unavailable")
            return {
                "user": {
                    "uid": "author-1",
                    "sec_uid": sec_uid,
                    "follower_count": 456,
                }
            }

    class TagRepository:
        async def upsert_many(self, rows):
            saved_rows.extend(rows)

        async def list_recent_aweme_ids(
            self,
            tag_ids,
            *,
            published_after,
        ):
            events.append(
                ("recent", tag_ids, published_after)
            )
            return ("aweme-1",)

    class FakeCrawler:
        def __init__(self):
            self.dy_client = FakeClient()

        async def start(self):
            events.append("start")
            target = self.tag_targets[0]
            await self.tag_page_callback(
                target,
                0,
                [
                    {
                        "aweme_id": "official-aweme",
                        "author": {
                            "uid": "official-author",
                            "unique_id": "novsight",
                        },
                    },
                    {
                        "aweme_id": "aweme-1",
                        "author": {
                            "uid": "author-1",
                            "sec_uid": "sec-1",
                            "unique_id": "customer-account",
                        },
                        "statistics": {"play_count": 0},
                    },
                    {
                        "aweme_id": "aweme-2",
                        "author": {
                            "uid": "author-1",
                            "sec_uid": "sec-1",
                            "unique_id": "customer-account",
                        },
                        "statistics": {"play_count": 0},
                    },
                    {
                        "aweme_id": "blocked-aweme",
                        "author": {
                            "uid": "1719260615816915",
                            "sec_uid": "blocked-sec",
                        },
                    },
                    {
                        "aweme_id": "aweme-profile-fails",
                        "author": {
                            "uid": "author-2",
                            "sec_uid": "sec-profile-fails",
                            "unique_id": "customer-account",
                        },
                        "statistics": {"play_count": 0},
                    },
                ],
            )
            await self.tag_complete_callback()

        async def batch_get_note_comments(self, aweme_ids):
            events.append(
                (
                    "comments",
                    tuple(aweme_ids),
                    douyin_comment_store_var.get(),
                )
            )

        async def close(self):
            events.append("close")

    async def fake_init_db(_db_type):
        events.append("db")

    task = Task(
        task_id="douyin-tag:7322391300177987638",
        platform=Platform.DOUYIN,
        kind=TaskKind.DOUYIN_TAG_CONTENT,
        profile=AccountProfile(
            platform=Platform.DOUYIN,
            template="dy_text_data_dir",
            path=Path("D:/browser_data/dy_text_data_dir"),
            is_main=False,
            is_water=True,
        ),
        get_comments=True,
        tag_targets=(
            DouyinTagTarget(
                tag_id="7322391300177987638",
                tag_name="#越野射灯",
                tag_url="https://www.douyin.com/hashtag/7322391300177987638",
            ),
        ),
        published_after=date(2026, 5, 27),
    )

    await run_public_task(
        task,
        crawler_factory=lambda _platform: FakeCrawler(),
        init_db=fake_init_db,
        tag_repository=TagRepository(),
    )

    assert events == [
        "db",
        "start",
        (
            "recent",
            ("7322391300177987638",),
            date(2026, 5, 27),
        ),
        ("comments", ("aweme-1",), "tag"),
        "close",
    ]
    assert saved_rows[0]["tag_id"] == "7322391300177987638"
    assert saved_rows[0]["aweme_id"] == "aweme-1"
    assert saved_rows[0]["author_id"] == "author-1"
    assert saved_rows[0]["author_unique_id"] == "customer-account"
    assert [row["aweme_id"] for row in saved_rows] == [
        "aweme-1",
        "aweme-2",
        "aweme-profile-fails",
    ]
    assert [row["play_count"] for row in saved_rows] == [
        None,
        None,
        None,
    ]
    assert [row["author_follower_count"] for row in saved_rows] == [
        456,
        456,
        None,
    ]
    assert fake_clients[0].profile_calls == [
        "sec-1",
        "sec-profile-fails",
    ]


def test_tag_task_banner_identifies_water_profile_and_target():
    task = Task(
        task_id="douyin-tag:7322391300177987638",
        platform=Platform.DOUYIN,
        kind=TaskKind.DOUYIN_TAG_CONTENT,
        profile=AccountProfile(
            platform=Platform.DOUYIN,
            template="dy_text_data_dir",
            path=Path("D:/browser_data/dy_text_data_dir"),
            is_main=False,
            is_water=True,
        ),
        tag_targets=(
            DouyinTagTarget(
                tag_id="7322391300177987638",
                tag_name="#越野射灯",
                tag_url="https://www.douyin.com/hashtag/7322391300177987638",
            ),
        ),
    )

    banner = _format_task_banner(task)

    assert "抖音 Tag 作品" in banner
    assert "账号类型：水号" in banner
    assert "7322391300177987638" in banner
    assert "#越野射灯" in banner
    assert "douyin_tag_aweme" in banner
