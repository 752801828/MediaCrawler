from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from creator_ops.config import Settings
from creator_ops.crawler_bridge import run_public_task
from creator_ops.douyin_stats_comments import (
    DEFAULT_DOUYIN_COMMENTS_AFTER,
    build_douyin_stats_comment_filter,
)
from creator_ops.domain import Platform, TaskKind
from creator_ops.feishu.client import FeishuClient, FeishuError
from creator_ops.planner import PlanningError, build_plan
from creator_ops.platforms import DouyinCreatorCollector, XhsCreatorCollector
from creator_ops.storage import CreatorOpsRepository
from creator_ops.sync import (
    OutboxSynchronizer,
    SyncSummary,
    metric_business_key,
    metric_feishu_payload,
)


@dataclass(frozen=True)
class WorkflowSummary:
    exit_code: int
    total_tasks: int = 0
    succeeded_tasks: int = 0
    failed_tasks: int = 0
    sync: SyncSummary = SyncSummary()


class CreatorOpsRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        repository: Any | None = None,
        collectors: dict[Platform, Any] | None = None,
        synchronizer: Any | None = None,
        public_task_runner: Any = run_public_task,
        init_db: Any | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or FeishuClient(settings.feishu)
        self.repository = repository or CreatorOpsRepository()
        self.collectors = collectors or {
            Platform.XHS: XhsCreatorCollector(),
            Platform.DOUYIN: DouyinCreatorCollector(),
        }
        self.synchronizer = synchronizer or OutboxSynchronizer(
            settings,
            self.client,
            self.repository,
        )
        self.public_task_runner = public_task_runner
        if init_db is None:
            from database.db import init_db as upstream_init_db

            init_db = upstream_init_db
        self.init_db = init_db

    async def run(
        self,
        *,
        dry_run: bool = False,
        collect_only: bool = False,
        sync_only: bool = False,
        task_kinds: set[TaskKind] | None = None,
        douyin_comments_after: date = DEFAULT_DOUYIN_COMMENTS_AFTER,
    ) -> WorkflowSummary:
        if sync_only:
            self._configure_upstream_mysql()
            await self.init_db("db")
            sync_summary = await self.synchronizer.deliver_pending()
            return WorkflowSummary(
                exit_code=1 if sync_summary.failed else 0,
                sync=sync_summary,
            )

        try:
            accounts, links, users, tags, stats_comments = (
                self._load_control_records(
                    douyin_comments_after,
                    include_stats_comments=(
                        task_kinds is None
                        or TaskKind.DOUYIN_STATS_COMMENTS in task_kinds
                    ),
                )
            )
            plan = build_plan(
                self.settings,
                accounts,
                links,
                users,
                tags,
                stats_comments,
                douyin_comments_after,
            )
            if task_kinds is not None:
                plan = [
                    task for task in plan if task.kind in task_kinds
                ]
        except (FeishuError, PlanningError, ValueError):
            return WorkflowSummary(exit_code=2)

        if dry_run:
            return await self._run_dry(plan)

        self._configure_upstream_mysql()
        await self.init_db("db")
        run_id = await self.repository.create_run(str(uuid.uuid4()))
        succeeded = 0
        failed = 0
        for task in plan:
            task_row_id = await self.repository.start_task(run_id, task)
            try:
                if task.kind is TaskKind.CREATOR_METRICS:
                    records = await self.collectors[task.platform].collect(task.profile)
                    target = (
                        "xhs_stats"
                        if task.platform is Platform.XHS
                        else "douyin_stats"
                    )
                    for record in records:
                        await self.repository.save_content_with_outbox(
                            record,
                            target_table=target,
                            business_key=metric_business_key(record),
                            payload=metric_feishu_payload(record),
                        )
                else:
                    await self.public_task_runner(task)
                    if task.kind is not TaskKind.DOUYIN_TAG_CONTENT:
                        await self.synchronizer.queue_platform_comments(task.platform)
            except Exception as exc:
                failed += 1
                await self.repository.finish_task(
                    task_row_id,
                    success=False,
                    error=type(exc).__name__,
                )
            else:
                succeeded += 1
                await self.repository.finish_task(task_row_id, success=True)

        sync_summary = SyncSummary()
        if not collect_only:
            sync_summary = await self.synchronizer.deliver_pending()
        status = "succeeded"
        if failed or sync_summary.failed:
            status = "partial"
        await self.repository.finish_run(
            run_id,
            status=status,
            total_tasks=len(plan),
            succeeded_tasks=succeeded,
            failed_tasks=failed,
        )
        return WorkflowSummary(
            exit_code=1 if status == "partial" else 0,
            total_tasks=len(plan),
            succeeded_tasks=succeeded,
            failed_tasks=failed,
            sync=sync_summary,
        )

    def _load_control_records(
        self,
        douyin_comments_after: date,
        *,
        include_stats_comments: bool,
    ) -> tuple[
        list[dict],
        list[dict],
        list[dict],
        list[dict],
        list[dict],
    ]:
        feishu = self.settings.feishu
        accounts = self.client.iter_records(
            feishu.app_token,
            feishu.account_table_id,
            feishu.account_view_id,
        )
        links = self.client.iter_records(
            feishu.app_token,
            feishu.link_table_id,
            feishu.link_view_id,
        )
        users = self.client.iter_records(
            feishu.app_token,
            feishu.user_table_id,
            feishu.user_view_id,
        )
        tags = self.client.iter_records(
            feishu.app_token,
            feishu.douyin_tag_table_id,
            "",
        )
        stats_comments: list[dict] = []
        if include_stats_comments:
            stats_comments = self.client.query_records(
                feishu.app_token,
                feishu.douyin_stats_table_id,
                filter_formula=build_douyin_stats_comment_filter(
                    douyin_comments_after
                ),
                field_names=("创建时间", "作品链接"),
            )
        return accounts, links, users, tags, stats_comments

    async def _run_dry(self, plan: list[Any]) -> WorkflowSummary:
        succeeded = 0
        failed = 0
        for task in plan:
            if not task.profile.path.is_dir():
                failed += 1
                continue
            if task.kind is TaskKind.CREATOR_METRICS:
                try:
                    await self.collectors[task.platform].collect(task.profile)
                except Exception:
                    failed += 1
                    continue
            succeeded += 1
        return WorkflowSummary(
            exit_code=1 if failed else 0,
            total_tasks=len(plan),
            succeeded_tasks=succeeded,
            failed_tasks=failed,
        )

    def _configure_upstream_mysql(self) -> None:
        import config
        from config.db_config import mysql_db_config

        mysql_db_config.clear()
        mysql_db_config.update(
            {
                "user": self.settings.mysql.user,
                "password": self.settings.mysql.password,
                "host": self.settings.mysql.host,
                "port": self.settings.mysql.port,
                "db_name": self.settings.mysql.database,
            }
        )
        config.SAVE_DATA_OPTION = "db"
