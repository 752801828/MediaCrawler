from datetime import date

from typer.testing import CliRunner

from creator_ops import cli
from creator_ops.domain import TaskKind
from creator_ops.runner import WorkflowSummary


runner = CliRunner()


def test_cli_exposes_required_commands():
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "run-all" in result.stdout
    assert "collect-only" in result.stdout
    assert "sync-only" in result.stdout
    assert "douyin-stats-comments" in result.stdout
    assert "validate-config" in result.stdout


def test_run_all_forwards_dry_run_and_exit_code(monkeypatch):
    calls = []

    class FakeSettings:
        def redacted_summary(self):
            return "{}"

    class FakeRunner:
        def __init__(self, settings):
            calls.append(settings)

        async def run(self, **kwargs):
            calls.append(kwargs)
            return WorkflowSummary(exit_code=1, total_tasks=2, failed_tasks=1)

    monkeypatch.setattr(cli, "load_settings", lambda: FakeSettings())
    monkeypatch.setattr(cli, "CreatorOpsRunner", FakeRunner)

    result = runner.invoke(cli.app, ["run-all", "--dry-run"])

    assert result.exit_code == 1
    assert calls[1] == {"dry_run": True}
    assert "failed=1" in result.stdout


def test_validate_config_prints_only_redacted_summary(monkeypatch):
    class FakeSettings:
        def redacted_summary(self):
            return '{"database_name":"media_crawler"}'

    monkeypatch.setattr(cli, "load_settings", lambda: FakeSettings())

    result = runner.invoke(cli.app, ["validate-config"])

    assert result.exit_code == 0
    assert "media_crawler" in result.stdout


def test_douyin_stats_comments_forwards_date_and_task_filter(monkeypatch):
    calls = []

    class FakeSettings:
        pass

    class FakeRunner:
        def __init__(self, settings):
            calls.append(settings)

        async def run(self, **kwargs):
            calls.append(kwargs)
            return WorkflowSummary(exit_code=0, total_tasks=1)

    monkeypatch.setattr(cli, "load_settings", lambda: FakeSettings())
    monkeypatch.setattr(cli, "CreatorOpsRunner", FakeRunner)

    result = runner.invoke(
        cli.app,
        [
            "douyin-stats-comments",
            "--after",
            "2026-07-10",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls[1] == {
        "dry_run": True,
        "task_kinds": {TaskKind.DOUYIN_STATS_COMMENTS},
        "douyin_comments_after": date(2026, 7, 10),
    }


def test_douyin_stats_comments_rejects_invalid_date():
    result = runner.invoke(
        cli.app,
        ["douyin-stats-comments", "--after", "2026/07/01"],
    )

    assert result.exit_code == 2
    assert "expected YYYY-MM-DD" in result.stderr
