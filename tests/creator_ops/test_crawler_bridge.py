from pathlib import Path

import pytest
from playwright._impl._errors import TargetClosedError

import config
from creator_ops.crawler_bridge import crawler_config_scope, run_public_task
from creator_ops.domain import AccountProfile, Platform, Task, TaskKind


def test_crawler_config_scope_restores_globals_after_error():
    original = {
        "PLATFORM": config.PLATFORM,
        "CRAWLER_TYPE": config.CRAWLER_TYPE,
        "USER_DATA_DIR": config.USER_DATA_DIR,
        "SAVE_DATA_OPTION": config.SAVE_DATA_OPTION,
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
            assert config.XHS_SPECIFIED_NOTE_URL_LIST == ["note-1"]
            raise RuntimeError("stop")

    for name, value in original.items():
        assert getattr(config, name) == value


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
