from pathlib import Path

import pytest
from playwright._impl._errors import TargetClosedError

import config
from creator_ops.crawler_bridge import (
    _format_task_banner,
    crawler_config_scope,
    run_public_task,
)
from creator_ops.domain import AccountProfile, Platform, Task, TaskKind


def test_crawler_config_scope_restores_globals_after_error():
    original = {
        "PLATFORM": config.PLATFORM,
        "CRAWLER_TYPE": config.CRAWLER_TYPE,
        "USER_DATA_DIR": config.USER_DATA_DIR,
        "SAVE_DATA_OPTION": config.SAVE_DATA_OPTION,
        "ENABLE_GET_SUB_COMMENTS": config.ENABLE_GET_SUB_COMMENTS,
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
