from __future__ import annotations

from dataclasses import dataclass

import pytest

from creator_ops.runner import WorkflowSummary
from creator_ops.scheduled import (
    FeishuBotNotifier,
    NotificationConfigError,
    build_text_payload,
    load_notifier,
    make_signature,
    run_and_notify,
)
from creator_ops.sync import SyncSummary


def test_make_signature_matches_feishu_algorithm() -> None:
    assert make_signature(1_600_000_000, "test-secret") == (
        "BwqgZGo8lGLJAUAc/kiJR0TDtnLVnsITtszoHeRuXV0="
    )


def test_build_text_payload_mentions_everyone_only_for_errors() -> None:
    normal = build_text_payload("任务完成")
    error = build_text_payload("任务失败", mention_all=True)

    assert normal["content"]["text"] == "任务完成"
    assert "<at user_id=\"all\">所有人</at>" not in normal["content"]["text"]
    assert error["content"]["text"].startswith(
        '<at user_id="all">所有人</at>\n'
    )


def test_notifier_posts_signed_payload() -> None:
    calls: list[tuple[str, dict, float]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"code": 0}

    def post(url: str, *, json: dict, timeout: float) -> Response:
        calls.append((url, json, timeout))
        return Response()

    notifier = FeishuBotNotifier(
        "https://example.invalid/hook",
        "test-secret",
        post=post,
        clock=lambda: 1_600_000_000,
    )

    notifier.send("任务失败", mention_all=True)

    assert calls[0][0] == "https://example.invalid/hook"
    assert calls[0][1]["timestamp"] == "1600000000"
    assert calls[0][1]["sign"] == make_signature(1_600_000_000, "test-secret")
    assert '<at user_id="all">所有人</at>' in calls[0][1]["content"]["text"]
    assert calls[0][2] == 10


def test_load_notifier_reports_missing_names_without_values() -> None:
    with pytest.raises(NotificationConfigError) as exc_info:
        load_notifier({"FEISHU_ALERT_WEBHOOK_URL": "private-url"})

    message = str(exc_info.value)
    assert "FEISHU_ALERT_SECRET" in message
    assert "private-url" not in message


@dataclass
class FakeRunner:
    summary: WorkflowSummary | None = None
    error: Exception | None = None

    async def run(self) -> WorkflowSummary:
        if self.error is not None:
            raise self.error
        assert self.summary is not None
        return self.summary


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []

    def send(self, text: str, *, mention_all: bool = False) -> None:
        self.messages.append((text, mention_all))


@pytest.mark.asyncio
async def test_run_and_notify_sends_start_and_success_summary() -> None:
    notifier = FakeNotifier()
    runner = FakeRunner(
        summary=WorkflowSummary(
            exit_code=0,
            total_tasks=4,
            succeeded_tasks=4,
            failed_tasks=0,
            sync=SyncSummary(attempted=20, succeeded=20, failed=0),
        )
    )

    times = iter((10.0, 75.0))
    summary = await run_and_notify(runner, notifier, clock=lambda: next(times))

    assert summary.exit_code == 0
    assert len(notifier.messages) == 2
    assert "开始" in notifier.messages[0][0]
    assert notifier.messages[0][1] is False
    assert "成功：4" in notifier.messages[1][0]
    assert "多维表同步成功：20" in notifier.messages[1][0]
    assert "耗时：1分5秒" in notifier.messages[1][0]
    assert notifier.messages[1][1] is False


@pytest.mark.asyncio
async def test_run_and_notify_mentions_everyone_for_partial_failure() -> None:
    notifier = FakeNotifier()
    runner = FakeRunner(
        summary=WorkflowSummary(
            exit_code=1,
            total_tasks=4,
            succeeded_tasks=3,
            failed_tasks=1,
            sync=SyncSummary(attempted=20, succeeded=18, failed=2),
        )
    )

    times = iter((10.0, 20.0))
    await run_and_notify(runner, notifier, clock=lambda: next(times))

    assert "失败：1" in notifier.messages[-1][0]
    assert "多维表同步失败：2" in notifier.messages[-1][0]
    assert notifier.messages[-1][1] is True


@pytest.mark.asyncio
async def test_run_and_notify_mentions_everyone_for_unhandled_error() -> None:
    notifier = FakeNotifier()
    runner = FakeRunner(error=RuntimeError("database unavailable"))

    with pytest.raises(RuntimeError, match="database unavailable"):
        times = iter((10.0, 20.0))
        await run_and_notify(runner, notifier, clock=lambda: next(times))

    assert "RuntimeError" in notifier.messages[-1][0]
    assert notifier.messages[-1][1] is True
