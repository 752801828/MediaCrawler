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

from creator_ops.runner import WorkflowSummary


logger = logging.getLogger(__name__)


class NotificationConfigError(ValueError):
    pass


def make_signature(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(string_to_sign, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def build_text_payload(text: str, *, mention_all: bool = False) -> dict[str, Any]:
    if mention_all:
        text = f'<at user_id="all">所有人</at>\n{text}'
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

    def send(self, text: str, *, mention_all: bool = False) -> None:
        timestamp = int(self.clock())
        payload = build_text_payload(text, mention_all=mention_all)
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
            mention_all=True,
        )
        raise

    elapsed = _format_duration(clock() - started)
    failed = bool(summary.exit_code or summary.failed_tasks or summary.sync.failed)
    status = "存在错误" if failed else "成功"
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
        mention_all=failed,
    )
    return summary


def _send_safely(notifier: Any, text: str, *, mention_all: bool = False) -> None:
    try:
        notifier.send(text, mention_all=mention_all)
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
