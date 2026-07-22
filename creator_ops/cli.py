from __future__ import annotations

import asyncio

import typer

from creator_ops.config import Settings, SettingsError, load_settings
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


@app.command("validate-config")
def validate_config() -> None:
    settings = _load_or_exit()
    typer.echo(settings.redacted_summary())


def _run(**kwargs: bool) -> None:
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
