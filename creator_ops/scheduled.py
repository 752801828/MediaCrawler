from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from dotenv import load_dotenv

from creator_ops.domain import (
    Platform,
    PlatformExecutionReport,
    Task,
    TaskKind,
)
from creator_ops.runner import WorkflowSummary


logger = logging.getLogger(__name__)


class NotificationConfigError(ValueError):
    pass


def make_signature(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(string_to_sign, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def build_text_payload(text: str) -> dict[str, Any]:
    return {"msg_type": "text", "content": {"text": text}}


class FeishuBotNotifier:
    def __init__(
        self,
        webhook_url: str,
        secret: str,
        *,
        post: Callable[..., Any] = httpx.post,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.webhook_url = webhook_url
        self.secret = secret
        self.post = post
        self.clock = clock

    def send(self, text: str) -> None:
        timestamp = int(self.clock())
        payload = build_text_payload(text)
        payload.update(
            {
                "timestamp": str(timestamp),
                "sign": make_signature(timestamp, self.secret),
            }
        )
        response = self.post(self.webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        code = result.get("code", result.get("StatusCode", 0))
        if code != 0:
            raise RuntimeError(f"Feishu bot returned code {code}")


def load_notifier(
    environ: Mapping[str, str] | None = None,
) -> FeishuBotNotifier:
    if environ is None:
        load_dotenv()
        environ = os.environ
    required = ("FEISHU_ALERT_WEBHOOK_URL", "FEISHU_ALERT_SECRET")
    missing = [name for name in required if not environ.get(name, "").strip()]
    if missing:
        raise NotificationConfigError(
            "missing notification settings: " + ", ".join(missing)
        )
    return FeishuBotNotifier(
        environ["FEISHU_ALERT_WEBHOOK_URL"].strip(),
        environ["FEISHU_ALERT_SECRET"].strip(),
    )


async def run_and_notify(
    runner: Any,
    notifier: Any,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> WorkflowSummary:
    started = clock()
    _send_safely(
        notifier,
        "MediaCrawler 定时任务开始\n"
        "平台：抖音、小红书\n"
        "模式：顺序执行，完成后同步多维表",
    )
    try:
        summary = await runner.run()
    except Exception as exc:
        elapsed = _format_duration(clock() - started)
        _send_safely(
            notifier,
            "MediaCrawler 定时任务异常终止\n"
            f"错误类型：{type(exc).__name__}\n"
            f"耗时：{elapsed}",
        )
        raise

    elapsed = _format_duration(clock() - started)
    status = (
        "存在错误"
        if summary.exit_code or summary.failed_tasks or summary.sync.failed
        else "成功"
    )
    _send_safely(
        notifier,
        f"MediaCrawler 定时任务完成\n"
        f"状态：{status}\n"
        f"任务总数：{summary.total_tasks}\n"
        f"成功：{summary.succeeded_tasks}\n"
        f"失败：{summary.failed_tasks}\n"
        f"多维表同步成功：{summary.sync.succeeded}\n"
        f"多维表同步失败：{summary.sync.failed}\n"
        f"耗时：{elapsed}",
    )
    return summary


def format_platform_report(report: PlatformExecutionReport) -> str:
    platform_label = "小红书" if report.platform is Platform.XHS else "抖音"
    failed = any(not task.success for task in report.tasks)
    lines = [
        f"【{platform_label}任务完成】",
        f"状态：{'存在失败' if failed else '成功'}",
        f"平台耗时：{_format_duration(report.elapsed_seconds)}",
        f"任务数量：{len(report.tasks)}",
    ]
    for index, task_report in enumerate(report.tasks, start=1):
        lines.extend(
            (
                "",
                f"{index}. {_task_label(task_report.task)}",
                f"状态：{'成功' if task_report.success else '失败'}",
                f"耗时：{_format_duration(task_report.elapsed_seconds)}",
                f"内容：{_task_details(task_report.task)}",
            )
        )
        if task_report.error:
            lines.append(f"错误类型：{task_report.error}")
        if task_report.changes:
            lines.append("数据：")
            lines.extend(
                f"- {change.label}：新增 {change.created}，"
                f"更新 {change.updated}，共 {change.total}"
                for change in task_report.changes
            )
        else:
            lines.append("数据：本任务未产生数据库新增或更新")
    return "\n".join(lines)


def notify_platform_report(notifier: Any, report: PlatformExecutionReport) -> None:
    _send_safely(notifier, format_platform_report(report))


def _task_label(task: Task) -> str:
    labels = {
        TaskKind.CREATOR_METRICS: "创作者后台作品指标",
        TaskKind.CONTENT_DETAIL: "指定作品详情与评论",
        TaskKind.CREATOR_CONTENT: "指定创作者作品",
        TaskKind.DOUYIN_TAG_CONTENT: "抖音 Tag 作品与评论",
        TaskKind.DOUYIN_STATS_COMMENTS: "官号作品评论",
    }
    return labels[task.kind]


def _task_details(task: Task) -> str:
    comments = "一级、二级评论" if task.get_comments else "不抓取评论"
    if task.kind is TaskKind.CREATOR_METRICS:
        return f"账号 {task.profile.template} 的创作者后台作品指标"
    if task.kind is TaskKind.DOUYIN_TAG_CONTENT:
        tags = "、".join(
            f"{target.tag_name}（{target.tag_id}）" for target in task.tag_targets
        )
        cutoff = task.published_after.isoformat() if task.published_after else "不限"
        return f"Tag {tags}；{cutoff} 之后发布的作品；{comments}"
    targets = _target_summary(task.targets)
    if task.kind is TaskKind.DOUYIN_STATS_COMMENTS:
        cutoff = task.published_after.isoformat() if task.published_after else "不限"
        return f"作品 {targets}；{cutoff} 之后发布；{comments}"
    if task.kind is TaskKind.CREATOR_CONTENT:
        return f"创作者 {targets}；抓取其作品"
    return f"作品 {targets}；{comments}"


def _target_summary(targets: tuple[str, ...]) -> str:
    if not targets:
        return "0 个"
    visible = "、".join(targets[:5])
    if len(targets) > 5:
        visible += f" 等 {len(targets)} 个"
    return visible


def _send_safely(notifier: Any, text: str) -> None:
    try:
        notifier.send(text)
    except Exception as exc:
        logger.warning("Feishu task notification failed: %s", type(exc).__name__)


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes}分{seconds}秒"
    if minutes:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"
