from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from creator_ops.config import FeishuSettings, MysqlSettings, Settings
from creator_ops.domain import MetricRecord, Platform
from creator_ops.runner import CreatorOpsRunner
from creator_ops.sync import OutboxSynchronizer, SyncSummary, sanitize_comment_fields


def settings_for(tmp_path: Path) -> Settings:
    for name in ("xhs_use_data_dir", "dy_use_data_dir"):
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


def test_sanitize_comment_fields_removes_public_identity():
    output = sanitize_comment_fields(
        {
            "comment_id": "c1",
            "content": "hello",
            "creator_hash": "hash",
            "nickname": "张*三",
            "user_id": "raw-user",
            "avatar": "https://private",
            "ip_location": "北京",
            "user_signature": "secret",
        }
    )

    assert output["creator_hash"] == "hash"
    assert output["nickname"] == "张*三"
    assert output["user_id"] == ""
    assert output["avatar"] == ""
    assert output["ip_location"] == ""
    assert output["user_signature"] == ""


@pytest.mark.asyncio
async def test_outbox_synchronizer_marks_batch_success(tmp_path: Path):
    rows = [
        SimpleNamespace(
            id=1,
            target_table="xhs_stats",
            payload_json=json.dumps({"标题": "A"}, ensure_ascii=False),
        ),
        SimpleNamespace(
            id=2,
            target_table="xhs_stats",
            payload_json=json.dumps({"标题": "B"}, ensure_ascii=False),
        ),
    ]

    class Repo:
        def __init__(self):
            self.synced = []

        async def pending_sync(self, limit=500):
            return rows

        async def mark_sync_succeeded(self, row_id):
            self.synced.append(row_id)

        async def mark_sync_failed(self, row_id, error):
            raise AssertionError(error)

    class Client:
        def __init__(self):
            self.calls = []

        def batch_create_records(self, app_token, table_id, fields):
            self.calls.append((app_token, table_id, fields))

    repo = Repo()
    client = Client()
    syncer = OutboxSynchronizer(settings_for(tmp_path), client, repo)

    summary = await syncer.deliver_pending()

    assert summary == SyncSummary(attempted=2, succeeded=2, failed=0)
    assert repo.synced == [1, 2]
    assert client.calls[0][1] == "xhs-stats"


@pytest.mark.asyncio
async def test_runner_continues_after_one_creator_task_fails(tmp_path: Path):
    settings = settings_for(tmp_path)
    events: list[str] = []
    accounts = [
        {"fields": {"ID": "%s_use_data_dir", "平台": "小红书", "主账号": True}},
        {"fields": {"ID": "%s_use_data_dir", "平台": "抖音", "主账号": True}},
    ]

    class Client:
        def iter_records(self, _app, table, _view):
            events.append(f"read:{table}")
            return accounts if table == "account" else []

    class Repo:
        async def create_run(self, _uuid):
            return 10

        async def start_task(self, _run_id, task):
            events.append(f"task:{task.platform.value}")
            return len(events)

        async def finish_task(self, _task_id, *, success, error=""):
            events.append(f"finish:{success}")

        async def save_content_with_outbox(self, *args, **kwargs):
            events.append("save")
            return 1, 1

        async def finish_run(self, *args, **kwargs):
            events.append(f"run:{kwargs['status']}")

    class FailingCollector:
        async def collect(self, _profile, **_kwargs):
            raise RuntimeError("xhs failed")

    class SuccessfulCollector:
        async def collect(self, profile, **_kwargs):
            return [
                MetricRecord(
                    platform=Platform.DOUYIN,
                    profile_key=profile.template,
                    content_key="video-1",
                    title="Video",
                    published_at=None,
                    snapshot_date=date(2026, 7, 21),
                    metrics={"浏览": 1},
                )
            ]

    class Syncer:
        async def deliver_pending(self):
            events.append("sync")
            return SyncSummary(attempted=1, succeeded=1, failed=0)

    async def init_db(_db_type):
        events.append("db")

    runner = CreatorOpsRunner(
        settings,
        client=Client(),
        repository=Repo(),
        collectors={
            Platform.XHS: FailingCollector(),
            Platform.DOUYIN: SuccessfulCollector(),
        },
        synchronizer=Syncer(),
        init_db=init_db,
    )

    summary = await runner.run()

    assert summary.exit_code == 1
    assert summary.succeeded_tasks == 1
    assert summary.failed_tasks == 1
    assert "task:xhs" in events
    assert "task:dy" in events
    assert events.index("read:account") < events.index("db")
