from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from creator_ops.config import FeishuSettings, MysqlSettings, Settings
from creator_ops.domain import MetricRecord, Platform, TaskKind
from creator_ops.feishu.client import FeishuError
from creator_ops.runner import CreatorOpsRunner, WorkflowSummary
from creator_ops.sync import (
    OutboxSynchronizer,
    SyncSummary,
    _comment_feishu_payload,
    metric_feishu_payload,
)


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
            douyin_comment_table_id="dy-comments",
        ),
    )


def test_comment_feishu_payload_preserves_douyin_raw_identity():
    output = _comment_feishu_payload(
        {
            "comment_id": "c1",
            "creator_hash": "hash",
            "user_id": "raw-user",
            "sec_uid": "raw-sec-uid",
            "short_user_id": "12345",
            "user_unique_id": "unique-user",
            "nickname": "完整昵称",
            "avatar": "https://private",
            "ip_location": "北京",
            "user_signature": "secret",
        },
        Platform.DOUYIN,
    )

    assert "creator_hash" not in output
    assert output["user_id"] == "raw-user"
    assert output["sec_uid"] == "raw-sec-uid"
    assert output["short_user_id"] == "12345"
    assert output["user_unique_id"] == "unique-user"
    assert output["nickname"] == "完整昵称"
    assert output["avatar"] == "https://private"
    assert output["ip_location"] == "北京"
    assert output["user_signature"] == "secret"


def test_comment_feishu_payload_preserves_xhs_raw_identity():
    output = _comment_feishu_payload(
        {
            "comment_id": "c1",
            "creator_hash": "hash",
            "nickname": "小红书原名",
            "user_id": "xhs-user",
            "avatar": "https://xhs/avatar",
            "ip_location": "广东",
        },
        Platform.XHS,
    )

    assert "creator_hash" not in output
    assert output["nickname"] == "小红书原名"
    assert output["user_id"] == "xhs-user"
    assert output["avatar"] == "https://xhs/avatar"
    assert output["ip_location"] == "广东"


@pytest.mark.asyncio
async def test_queue_douyin_roots_updates_existing_and_skips_children(
    tmp_path: Path,
):
    class Client:
        def iter_records(self, *_args, **_kwargs):
            return [{"fields": {"评论ID": "existing-root"}}]

    class Repo:
        def __init__(self):
            self.queued = []

        async def list_comment_payloads(self, _platform):
            return [
                {
                    "id": "1",
                    "comment_id": "existing-root",
                    "parent_comment_id": "0",
                    "user_id": "raw-user",
                    "nickname": "已有一级评论",
                },
                {
                    "id": "2",
                    "comment_id": "existing-child",
                    "parent_comment_id": "existing-root",
                    "nickname": "二级评论",
                },
                {
                    "id": "3",
                    "comment_id": "new-root",
                    "parent_comment_id": "0",
                    "user_id": "new-user",
                    "nickname": "新一级评论",
                },
            ]

        async def enqueue_sync(self, **kwargs):
            self.queued.append(kwargs)
            return 1

    repo = Repo()
    syncer = OutboxSynchronizer(settings_for(tmp_path), Client(), repo)

    queued = await syncer.queue_platform_comments(Platform.DOUYIN)

    assert queued == 2
    by_key = {row["business_key"]: row for row in repo.queued}
    assert set(by_key) == {
        "comment:dy:existing-root",
        "comment:dy:new-root",
    }
    assert by_key["comment:dy:existing-root"]["force_create"] is False
    assert by_key["comment:dy:new-root"]["force_create"] is True
    assert (
        by_key["comment:dy:existing-root"]["payload"]["用户ID"]
        == "raw-user"
    )
    assert (
        by_key["comment:dy:existing-root"]["payload"]["用户昵称"]
        == "已有一级评论"
    )


@pytest.mark.asyncio
async def test_queue_comments_does_not_force_create_when_inventory_fails(
    tmp_path: Path,
):
    class Client:
        def iter_records(self, *_args, **_kwargs):
            raise FeishuError("inventory unavailable")

    class Repo:
        def __init__(self):
            self.queued = []

        async def list_comment_payloads(self, _platform):
            return [
                {
                    "id": "1",
                    "comment_id": "comment-1",
                    "parent_comment_id": "0",
                    "nickname": "name",
                }
            ]

        async def enqueue_sync(self, **kwargs):
            self.queued.append(kwargs)
            return 1

    repo = Repo()
    syncer = OutboxSynchronizer(settings_for(tmp_path), Client(), repo)

    queued = await syncer.queue_platform_comments(Platform.DOUYIN)

    assert queued == 1
    assert repo.queued[0]["force_create"] is False


@pytest.mark.asyncio
async def test_queue_xhs_comments_keeps_existing_skip_behavior(tmp_path: Path):
    class Client:
        def iter_records(self, *_args, **_kwargs):
            return [{"fields": {"comment_id": "existing-xhs"}}]

    class Repo:
        def __init__(self):
            self.queued = []

        async def list_comment_payloads(self, _platform):
            return [
                {"comment_id": "existing-xhs", "nickname": "existing"},
                {"comment_id": "new-xhs", "nickname": "new"},
            ]

        async def enqueue_sync(self, **kwargs):
            self.queued.append(kwargs)
            return 1

    repo = Repo()
    syncer = OutboxSynchronizer(settings_for(tmp_path), Client(), repo)

    queued = await syncer.queue_platform_comments(Platform.XHS)

    assert queued == 1
    assert repo.queued[0]["business_key"] == "comment:xhs:new-xhs"
    assert repo.queued[0]["payload"]["nickname"] == "new"


def test_metric_feishu_payload_includes_content_url():
    record = MetricRecord(
        platform=Platform.DOUYIN,
        profile_key="%s_use_data_dir",
        content_key="7665675303762968305",
        title="Video",
        content_url="https://www.douyin.com/video/7665675303762968305",
        published_at=None,
        snapshot_date=date(2026, 7, 24),
        metrics={"浏览": 10, "评论": 0, "完播率": 31.2},
    )

    payload = metric_feishu_payload(record)

    assert payload["作品链接"] == record.content_url
    assert payload["浏览"] == "10"
    assert payload["评论"] == "0"
    assert payload["完播率_"] == "31.2%"
    assert "完播率" not in payload


@pytest.mark.asyncio
async def test_outbox_synchronizer_marks_batch_success(tmp_path: Path):
    rows = [
        SimpleNamespace(
            id=1,
            target_table="xhs_stats",
            payload_json=json.dumps({"标题": "A"}, ensure_ascii=False),
            remote_record_id="",
        ),
        SimpleNamespace(
            id=2,
            target_table="xhs_stats",
            payload_json=json.dumps({"标题": "B"}, ensure_ascii=False),
            remote_record_id="",
        ),
    ]

    class Repo:
        def __init__(self):
            self.synced = []
            self.requested_limit = 500

        async def pending_sync(self, limit=None):
            self.requested_limit = limit
            return rows

        async def mark_sync_succeeded(self, row_id, remote_record_id=""):
            self.synced.append((row_id, remote_record_id))

        async def mark_sync_failed(self, row_id, error):
            raise AssertionError(error)

    class Client:
        def __init__(self):
            self.calls = []

        def batch_create_records(self, app_token, table_id, fields):
            self.calls.append((app_token, table_id, fields))
            return [
                {
                    "data": {
                        "records": [
                            {"record_id": "rec-1"},
                            {"record_id": "rec-2"},
                        ]
                    }
                }
            ]

    repo = Repo()
    client = Client()
    syncer = OutboxSynchronizer(settings_for(tmp_path), client, repo)

    summary = await syncer.deliver_pending()

    assert summary == SyncSummary(attempted=2, succeeded=2, failed=0)
    assert repo.requested_limit is None
    assert repo.synced == [(1, "rec-1"), (2, "rec-2")]
    assert client.calls[0][1] == "xhs-stats"


@pytest.mark.asyncio
async def test_outbox_synchronizer_updates_existing_remote_record(tmp_path: Path):
    rows = [
        SimpleNamespace(
            id=3,
            target_table="douyin_stats",
            payload_json=json.dumps(
                {"标题": "Video", "浏览": "20"},
                ensure_ascii=False,
            ),
            remote_record_id="rec-existing",
        )
    ]

    class Repo:
        def __init__(self):
            self.synced = []

        async def pending_sync(self, limit=500):
            return rows

        async def mark_sync_succeeded(self, row_id, remote_record_id=""):
            self.synced.append((row_id, remote_record_id))

        async def mark_sync_failed(self, row_id, error):
            raise AssertionError((row_id, error))

    class Client:
        def __init__(self):
            self.updates = []

        def batch_update_records(self, app_token, table_id, records):
            self.updates.append((app_token, table_id, records))
            return [{"data": {"records": [{"record_id": "rec-existing"}]}}]

    repo = Repo()
    client = Client()
    syncer = OutboxSynchronizer(settings_for(tmp_path), client, repo)

    summary = await syncer.deliver_pending()

    assert summary == SyncSummary(attempted=1, succeeded=1, failed=0)
    assert repo.synced == [(3, "")]
    assert client.updates[0][1] == "dy-stats"
    assert client.updates[0][2] == [
        ("rec-existing", {"标题": "Video", "浏览": "20"})
    ]


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

        def query_records(self, *_args, **_kwargs):
            events.append("read:stats-comments")
            return []

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


@pytest.mark.asyncio
async def test_tag_task_does_not_queue_comment_or_feishu_sync(tmp_path: Path):
    settings = settings_for(tmp_path)
    events = []
    accounts = [
        {
            "fields": {
                "ID": "%s_use_data_dir",
                "平台": "抖音",
                "主账号": False,
                "水号": True,
            }
        }
    ]
    tags = [
        {
            "fields": {
                "tag": "#越野射灯",
                "链接": "https://www.douyin.com/hashtag/7322391300177987638",
            }
        }
    ]

    class Client:
        def iter_records(self, _app, table, _view):
            if table == "account":
                return accounts
            if table == settings.feishu.douyin_tag_table_id:
                return tags
            return []

        def query_records(self, *_args, **_kwargs):
            return []

    class Repo:
        async def create_run(self, _uuid):
            return 1

        async def start_task(self, _run_id, task):
            events.append(f"task:{task.kind.value}")
            return 1

        async def finish_task(self, _task_id, *, success, error=""):
            events.append(f"finish:{success}")

        async def finish_run(self, *args, **kwargs):
            events.append(f"run:{kwargs['status']}")

    class Syncer:
        async def queue_platform_comments(self, _platform):
            raise AssertionError("Tag task must not queue comment sync")

        async def deliver_pending(self):
            raise AssertionError("collect-only must not write Feishu")

    async def public_task_runner(task):
        events.append(f"public:{task.kind.value}")

    async def init_db(_db_type):
        events.append("db")

    runner = CreatorOpsRunner(
        settings,
        client=Client(),
        repository=Repo(),
        synchronizer=Syncer(),
        public_task_runner=public_task_runner,
        init_db=init_db,
    )

    summary = await runner.run(collect_only=True)

    assert summary.exit_code == 0
    assert summary.total_tasks == 1
    assert events == [
        "db",
        "task:douyin_tag_content",
        "public:douyin_tag_content",
        "finish:True",
        "run:succeeded",
    ]


@pytest.mark.asyncio
async def test_stats_comment_task_runs_and_queues_douyin_comments(
    tmp_path: Path,
):
    settings = settings_for(tmp_path)
    events = []
    accounts = [
        {
            "fields": {
                "ID": "%s_text_data_dir",
                "平台": "抖音",
                "水号": True,
            }
        }
    ]
    stats_records = [
        {
            "fields": {
                "创建时间": "2026-07-02 10:00:00",
                "作品链接": "https://www.douyin.com/video/7000000000000000001",
            }
        }
    ]

    class Client:
        def iter_records(self, _app, table, _view):
            return accounts if table == "account" else []

        def query_records(
            self,
            _app,
            table,
            *,
            filter_formula,
            field_names,
        ):
            events.append(
                (
                    "query",
                    table,
                    filter_formula,
                    tuple(field_names),
                )
            )
            return stats_records

    class Repo:
        async def create_run(self, _uuid):
            return 1

        async def start_task(self, _run_id, task):
            events.append(("task", task.kind, task.targets))
            return 1

        async def finish_task(self, _task_id, *, success, error=""):
            events.append(("finish", success))

        async def finish_run(self, *args, **kwargs):
            events.append(("run", kwargs["status"]))

    class Syncer:
        async def queue_platform_comments(self, platform):
            events.append(("queue", platform))
            return 1

        async def deliver_pending(self):
            events.append(("sync",))
            return SyncSummary(attempted=1, succeeded=1, failed=0)

    async def public_task_runner(task):
        events.append(("public", task.kind, task.get_comments))

    async def init_db(_db_type):
        events.append(("db",))

    runner = CreatorOpsRunner(
        settings,
        client=Client(),
        repository=Repo(),
        synchronizer=Syncer(),
        public_task_runner=public_task_runner,
        init_db=init_db,
    )

    summary = await runner.run()

    assert summary == WorkflowSummary(
        exit_code=0,
        total_tasks=1,
        succeeded_tasks=1,
        failed_tasks=0,
        sync=SyncSummary(attempted=1, succeeded=1, failed=0),
    )
    assert (
        "task",
        TaskKind.DOUYIN_STATS_COMMENTS,
        ("7000000000000000001",),
    ) in events
    assert ("public", TaskKind.DOUYIN_STATS_COMMENTS, True) in events
    assert ("queue", Platform.DOUYIN) in events
