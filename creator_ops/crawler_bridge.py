from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import config
from playwright.async_api import Error as PlaywrightError

from creator_ops.domain import Platform, Task, TaskKind
from tools import utils


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

_PLATFORM_LABELS = {
    Platform.DOUYIN: "抖音",
    Platform.XHS: "小红书",
}

_SENSITIVE_QUERY_MARKERS = (
    "token",
    "cookie",
    "auth",
    "sign",
    "secret",
    "session",
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
        _emit_task_banner(task)
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


def _emit_task_banner(task: Task) -> None:
    utils.logger.info("\n%s", _format_task_banner(task))


def _format_task_banner(task: Task) -> str:
    platform_label = _PLATFORM_LABELS[task.platform]
    if task.kind is TaskKind.CONTENT_DETAIL:
        task_label = "作品详情 + 评论" if task.get_comments else "作品详情"
    elif task.kind is TaskKind.CREATOR_CONTENT:
        task_label = "创作者作品"
    else:
        task_label = task.kind.value

    roles: list[str] = []
    if task.profile.is_main:
        roles.append("主账号")
    if task.profile.is_water:
        roles.append("水号")
    role_label = " / ".join(roles) if roles else "未标记"
    sub_comments_enabled = bool(
        task.get_comments and config.ENABLE_GET_SUB_COMMENTS
    )

    lines = [
        "=" * 60,
        "【即将执行任务】",
        f"平台：{platform_label}",
        f"任务：{task_label}",
        f"账号类型：{role_label}",
        f"账号模板：{task.profile.template}",
        f"账号目录：{task.profile.path.resolve()}",
        f"目标数量：{len(task.targets)}",
        "目标：",
    ]
    if task.targets:
        lines.extend(
            f"  {index}. {_sanitize_display_target(target)}"
            for index, target in enumerate(task.targets, start=1)
        )
    else:
        lines.append("  （无）")
    lines.extend(
        [
            f"一级评论：{'开启' if task.get_comments else '关闭'}",
            f"二级评论：{'开启' if sub_comments_enabled else '关闭'}",
            "提示：如出现二维码，请使用与上述账号目录对应的账号扫码",
            "=" * 60,
        ]
    )
    return "\n".join(lines)


def _sanitize_display_target(target: str) -> str:
    parts = urlsplit(str(target))
    if not parts.scheme or not parts.netloc or not parts.query:
        return str(target)
    safe_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not any(marker in key.lower() for marker in _SENSITIVE_QUERY_MARKERS)
    ]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(safe_query, doseq=True),
            parts.fragment,
        )
    )


async def _close_crawler(crawler: Any) -> None:
    close = getattr(crawler, "close", None)
    if close is None:
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except PlaywrightError as exc:
        if type(exc).__name__ != "TargetClosedError":
            raise
