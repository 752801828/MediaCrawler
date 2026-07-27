from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import config
from playwright.async_api import Error as PlaywrightError

from creator_ops.douyin_tags import extract_douyin_tag_aweme
from creator_ops.domain import Platform, Task, TaskKind
from tools import utils
from var import douyin_comment_store_var


_SCOPED_CONFIG_NAMES = (
    "PLATFORM",
    "CRAWLER_TYPE",
    "USER_DATA_DIR",
    "SAVE_DATA_OPTION",
    "ENABLE_GET_COMMENTS",
    "ENABLE_GET_SUB_COMMENTS",
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
        config.ENABLE_GET_SUB_COMMENTS = True
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
    tag_repository: Any | None = None,
) -> None:
    if task.kind in {
        TaskKind.CONTENT_DETAIL,
        TaskKind.DOUYIN_STATS_COMMENTS,
    }:
        crawler_type = "detail"
    elif task.kind is TaskKind.CREATOR_CONTENT:
        crawler_type = "creator"
    elif task.kind is TaskKind.DOUYIN_TAG_CONTENT:
        crawler_type = "tag"
    else:
        raise ValueError(f"unsupported public crawler task: {task.kind.value}")

    if crawler_factory is None:
        from main import CrawlerFactory

        crawler_factory = CrawlerFactory.create_crawler
    if init_db is None:
        from database.db import init_db as upstream_init_db

        init_db = upstream_init_db
    if task.kind is TaskKind.DOUYIN_TAG_CONTENT and tag_repository is None:
        from creator_ops.storage import DouyinTagRepository

        tag_repository = DouyinTagRepository()

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
        if task.kind is TaskKind.DOUYIN_TAG_CONTENT:
            crawler.tag_targets = task.tag_targets

            async def save_tag_page(target, cursor, aweme_list):
                rows = []
                for aweme in aweme_list:
                    try:
                        rows.append(
                            extract_douyin_tag_aweme(
                                target,
                                aweme,
                                source_cursor=cursor,
                            )
                        )
                    except ValueError as exc:
                        utils.logger.warning(
                            "[creator_ops.run_public_task] Skip Tag aweme %s: %s",
                            aweme.get("aweme_id", "unknown"),
                            exc,
                        )
                if rows:
                    await tag_repository.upsert_many(rows)

            crawler.tag_page_callback = save_tag_page
        try:
            await crawler.start()
            if task.kind is TaskKind.DOUYIN_TAG_CONTENT:
                if task.published_after is None:
                    raise ValueError(
                        "douyin tag comment task is missing published cutoff"
                    )
                aweme_ids = await tag_repository.list_recent_aweme_ids(
                    tuple(target.tag_id for target in task.tag_targets),
                    published_after=task.published_after,
                )
                utils.logger.info(
                    "[creator_ops.run_public_task] Tag近两个月视频=%s，"
                    "开始抓取父评论和子评论",
                    len(aweme_ids),
                )
                token = douyin_comment_store_var.set("tag")
                try:
                    await crawler.batch_get_note_comments(list(aweme_ids))
                finally:
                    douyin_comment_store_var.reset(token)
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
    elif task.kind is TaskKind.DOUYIN_STATS_COMMENTS:
        task_label = "作品表评论刷新"
    elif task.kind is TaskKind.CREATOR_CONTENT:
        task_label = "创作者作品"
    elif task.kind is TaskKind.DOUYIN_TAG_CONTENT:
        task_label = "抖音 Tag 作品"
    else:
        task_label = task.kind.value

    roles: list[str] = []
    if task.profile.is_main:
        roles.append("主账号")
    if task.profile.is_water:
        roles.append("水号")
    role_label = " / ".join(roles) if roles else "未标记"
    sub_comments_enabled = config.is_get_sub_comments_enabled(
        task.platform.value,
        comments_enabled=task.get_comments,
    )

    display_targets = list(task.targets)
    if task.kind is TaskKind.DOUYIN_TAG_CONTENT:
        display_targets = [
            f"{target.tag_name} | {target.tag_id} | {target.tag_url}"
            for target in task.tag_targets
        ]

    lines = [
        "=" * 60,
        "【即将执行任务】",
        f"平台：{platform_label}",
        f"任务：{task_label}",
        f"账号类型：{role_label}",
        f"账号模板：{task.profile.template}",
        f"账号目录：{task.profile.path.resolve()}",
        f"目标数量：{len(display_targets)}",
        "目标：",
    ]
    if display_targets:
        lines.extend(
            f"  {index}. {_sanitize_display_target(target)}"
            for index, target in enumerate(display_targets, start=1)
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
    if task.kind is TaskKind.DOUYIN_TAG_CONTENT:
        lines.insert(
            -1,
            "数据表：douyin_tag_aweme + douyin_tag_aweme_comment",
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
