from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import typer

from creator_ops.config import Settings, SettingsError, load_settings
from creator_ops.domain import TaskKind
from creator_ops.douyin_stats_comments import (
    rolling_month_cutoff,
)
from creator_ops.migrate import migrate_legacy_creator_history
from creator_ops.runner import CreatorOpsRunner, WorkflowSummary

app = typer.Typer(
    add_completion=False,
    help="Feishu-driven Xiaohongshu and Douyin creator operations.",
)


@app.command("run-all")
def run_all(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Read tasks and parse creator pages without MySQL or Feishu writes.",
    ),
) -> None:
    _run(dry_run=dry_run)


@app.command("collect-only")
def collect_only(
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    _run(dry_run=dry_run, collect_only=True)


@app.command("sync-only")
def sync_only() -> None:
    _run(sync_only=True)


@app.command("douyin-stats-comments")
def douyin_stats_comments(
    after_date: str = typer.Option(
        "",
        "--after",
        help=(
            "Include works published on or after this date (YYYY-MM-DD). "
            "Defaults to two calendar months ago."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Read, filter, and plan targets without opening the crawler.",
    ),
) -> None:
    if after_date:
        try:
            parsed_after = date.fromisoformat(after_date)
        except ValueError as exc:
            typer.echo(
                "Invalid --after date; expected YYYY-MM-DD.",
                err=True,
            )
            raise typer.Exit(2) from exc
    else:
        parsed_after = rolling_month_cutoff()
    _run(
        dry_run=dry_run,
        task_kinds={TaskKind.DOUYIN_STATS_COMMENTS},
        douyin_comments_after=parsed_after,
    )


@app.command("validate-config")
def validate_config() -> None:
    settings = _load_or_exit()
    typer.echo(settings.redacted_summary())


@app.command("migrate-legacy")
def migrate_legacy(
    owned_user_id: list[str] = typer.Option(
        [],
        "--owned-user-id",
        help="A creator user ID owned by you; repeat for multiple accounts.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write eligible snapshots. Without this flag the command is a dry-run.",
    ),
) -> None:
    settings = _load_or_exit()
    try:
        summary = asyncio.run(
            migrate_legacy_creator_history(
                settings,
                owned_user_ids=set(owned_user_id),
                apply=apply,
            )
        )
    except ValueError as exc:
        typer.echo(f"Migration error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        "Legacy migration finished: "
        f"scanned={summary.scanned}, "
        f"eligible={summary.eligible}, "
        f"imported={summary.imported}, "
        f"dry_run={not apply}"
    )


def _run(**kwargs: Any) -> None:
    settings = _load_or_exit()
    summary = asyncio.run(CreatorOpsRunner(settings).run(**kwargs))
    _print_summary(summary)
    if summary.exit_code:
        raise typer.Exit(summary.exit_code)


def _load_or_exit() -> Settings:
    try:
        return load_settings()
    except SettingsError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(2) from exc


def _print_summary(summary: WorkflowSummary) -> None:
    typer.echo(
        "Creator operations finished: "
        f"tasks={summary.total_tasks}, "
        f"succeeded={summary.succeeded_tasks}, "
        f"failed={summary.failed_tasks}, "
        f"sync_succeeded={summary.sync.succeeded}, "
        f"sync_failed={summary.sync.failed}"
    )
