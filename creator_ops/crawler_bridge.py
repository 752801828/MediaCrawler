from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import config

from creator_ops.domain import Platform, Task, TaskKind


_SCOPED_CONFIG_NAMES = (
    "PLATFORM",
    "CRAWLER_TYPE",
    "USER_DATA_DIR",
    "SAVE_DATA_OPTION",
    "ENABLE_GET_COMMENTS",
    "ENABLE_CDP_MODE",
    "HEADLESS",
    "CDP_HEADLESS",
    "XHS_SPECIFIED_NOTE_URL_LIST",
    "DY_SPECIFIED_ID_LIST",
    "XHS_CREATOR_ID_LIST",
    "DY_CREATOR_ID_LIST",
)


@contextmanager
def crawler_config_scope(
    *,
    platform: Platform,
    crawler_type: str,
    user_data_dir: str,
    targets: tuple[str, ...] = (),
    get_comments: bool = False,
) -> Iterator[None]:
    original = {name: getattr(config, name) for name in _SCOPED_CONFIG_NAMES}
    try:
        config.PLATFORM = platform.value
        config.CRAWLER_TYPE = crawler_type
        config.USER_DATA_DIR = user_data_dir
        config.SAVE_DATA_OPTION = "db"
        config.ENABLE_GET_COMMENTS = get_comments
        config.ENABLE_CDP_MODE = False
        config.HEADLESS = False
        config.CDP_HEADLESS = False
        if crawler_type == "detail":
            if platform is Platform.XHS:
                config.XHS_SPECIFIED_NOTE_URL_LIST = list(targets)
            else:
                config.DY_SPECIFIED_ID_LIST = list(targets)
        elif crawler_type == "creator":
            if platform is Platform.XHS:
                config.XHS_CREATOR_ID_LIST = list(targets)
            else:
                config.DY_CREATOR_ID_LIST = list(targets)
        yield
    finally:
        for name, value in original.items():
            setattr(config, name, value)


async def run_public_task(
    task: Task,
    *,
    crawler_factory: Callable[[str], Any] | None = None,
    init_db: Callable[[str], Any] | None = None,
) -> None:
    if task.kind is TaskKind.CONTENT_DETAIL:
        crawler_type = "detail"
    elif task.kind is TaskKind.CREATOR_CONTENT:
        crawler_type = "creator"
    else:
        raise ValueError(f"unsupported public crawler task: {task.kind.value}")

    if crawler_factory is None:
        from main import CrawlerFactory

        crawler_factory = CrawlerFactory.create_crawler
    if init_db is None:
        from database.db import init_db as upstream_init_db

        init_db = upstream_init_db

    profile_template = _absolute_profile_template(
        task.profile.path.parent,
        task.profile.template,
    )
    with crawler_config_scope(
        platform=task.platform,
        crawler_type=crawler_type,
        user_data_dir=profile_template,
        targets=task.targets,
        get_comments=task.get_comments,
    ):
        await init_db("db")
        crawler = crawler_factory(task.platform.value)
        try:
            await crawler.start()
        finally:
            await _close_crawler(crawler)


def _absolute_profile_template(parent: Path, template: str) -> str:
    candidate = str(parent / template)
    if "%s" not in candidate:
        candidate += "%.0s"
    return candidate


async def _close_crawler(crawler: Any) -> None:
    close = getattr(crawler, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result
