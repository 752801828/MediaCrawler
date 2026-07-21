# Creator Operations Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Feishu-driven, MySQL-backed Xiaohongshu and Douyin creator-operations workflow to the current MediaCrawler upstream without restoring the legacy core or public-profile persistence.

**Architecture:** A new `creator_ops` package owns configuration, Feishu I/O, task planning, official creator-center collection, SQLAlchemy snapshots, synchronization, and CLI orchestration. Public content and comments run through an adapter over the current upstream crawlers, while browser profiles remain external under `D:\browser_data`.

**Tech Stack:** Python 3.11+, Typer, Playwright, Requests, SQLAlchemy async, MySQL/asyncmy, pytest, pytest-asyncio.

---

## File Map

- `creator_ops/__init__.py`: package metadata.
- `creator_ops/__main__.py`: `python -m creator_ops` entry point.
- `creator_ops/config.py`: typed environment configuration and validation.
- `creator_ops/domain.py`: platform, account, task, metric, and result types.
- `creator_ops/feishu/client.py`: Feishu HTTP client, pagination, batching, and retries.
- `creator_ops/feishu/schema.py`: existing table identifiers and Chinese field mappings.
- `creator_ops/planner.py`: Feishu records to ordered tasks.
- `creator_ops/platforms/base.py`: collector protocol and shared browser helpers.
- `creator_ops/platforms/xhs_creator.py`: Xiaohongshu creator-center collector.
- `creator_ops/platforms/douyin_creator.py`: Douyin creator-center collector.
- `creator_ops/crawler_bridge.py`: upstream crawler configuration adapter.
- `creator_ops/storage/models.py`: operations SQLAlchemy models.
- `creator_ops/storage/repository.py`: run, snapshot, task, and outbox persistence.
- `creator_ops/sync.py`: privacy-safe Feishu payloads and outbox delivery.
- `creator_ops/runner.py`: workflow application service.
- `creator_ops/cli.py`: Typer commands and process exit codes.
- `tests/creator_ops/`: focused unit and integration tests.
- `.env.example`: empty deployment variable template.
- `.gitignore`: runtime and credential exclusions.
- `start_creator_ops.cmd`: one-run Windows launcher.
- `docs/creator_ops_guide.md`: setup, dry-run, scheduling, and recovery guide.

## Task 1: Configuration, Domain Types, and Repository Hygiene

**Files:**
- Create: `creator_ops/__init__.py`
- Create: `creator_ops/config.py`
- Create: `creator_ops/domain.py`
- Create: `tests/creator_ops/test_config.py`
- Modify: `.gitignore`
- Create: `.env.example`

- [ ] **Step 1: Write failing configuration tests**

```python
from pathlib import Path

import pytest

from creator_ops.config import SettingsError, load_settings


def valid_env(tmp_path: Path) -> dict[str, str]:
    profile = tmp_path / "xhs_use_data_dir"
    profile.mkdir()
    return {
        "BROWSER_DATA_ROOT": str(tmp_path),
        "RELATION_DB_HOST": "127.0.0.1",
        "RELATION_DB_PORT": "3306",
        "RELATION_DB_USER": "root",
        "RELATION_DB_PWD": "secret",
        "RELATION_DB_NAME": "media_crawler",
        "FEISHU_APP_ID": "cli_xxx",
        "FEISHU_APP_SECRET": "app-secret",
        "FEISHU_APP_TOKEN": "app-token",
        "FEISHU_LINK_TABLE_ID": "tbl_link",
        "FEISHU_LINK_VIEW_ID": "vew_link",
        "FEISHU_USER_TABLE_ID": "tbl_user",
        "FEISHU_USER_VIEW_ID": "vew_user",
        "FEISHU_ACCOUNT_TABLE_ID": "tbl_account",
        "FEISHU_ACCOUNT_VIEW_ID": "vew_account",
    }


def test_load_settings_defaults_to_mysql_and_expands_profile(tmp_path):
    settings = load_settings(valid_env(tmp_path))
    assert settings.database_type == "mysql"
    assert settings.profile_path("%s_use_data_dir", "xhs") == tmp_path / "xhs_use_data_dir"


def test_load_settings_reports_missing_values_without_secret_values(tmp_path):
    env = valid_env(tmp_path)
    del env["FEISHU_APP_SECRET"]
    with pytest.raises(SettingsError) as exc:
        load_settings(env)
    assert "FEISHU_APP_SECRET" in str(exc.value)
    assert "app-secret" not in str(exc.value)
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `python -m pytest tests/creator_ops/test_config.py -q`

Expected: FAIL because `creator_ops.config` does not exist.

- [ ] **Step 3: Implement settings and domain types**

Implement immutable dataclasses for `Settings`, `FeishuSettings`, `MysqlSettings`, `AccountProfile`, `Task`, `MetricRecord`, and `TaskResult`. `load_settings(environ=None)` must load `.env`, require all control-table identifiers, force `database_type="mysql"`, default `BROWSER_DATA_ROOT` to `D:\browser_data`, reject templates that escape the configured root, and expose `redacted_summary()`.

The key profile method is:

```python
def profile_path(self, template: str, platform: str) -> Path:
    name = template % platform
    candidate = (self.browser_data_root / name).resolve()
    if self.browser_data_root.resolve() not in candidate.parents:
        raise SettingsError("browser profile escapes BROWSER_DATA_ROOT")
    return candidate
```

- [ ] **Step 4: Extend Git exclusions and environment template**

Add `.env`, `.env.*` except `.env.example`, `browser_data/`, `runtime/creator_ops/`, `creator_ops_diagnostics/`, and credential-like cookie exports to `.gitignore`. Populate `.env.example` with the current database and Feishu variable names using empty values, plus `BROWSER_DATA_ROOT=D:\browser_data`.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_config.py -q`

Expected: PASS.

Commit: `feat: add creator operations configuration`

## Task 2: Feishu Client and Existing Schema Mapping

**Files:**
- Create: `creator_ops/feishu/__init__.py`
- Create: `creator_ops/feishu/client.py`
- Create: `creator_ops/feishu/schema.py`
- Create: `tests/creator_ops/test_feishu_client.py`

- [ ] **Step 1: Write failing Feishu tests**

```python
from creator_ops.feishu.client import FeishuClient, FeishuPermissionError


def test_iter_records_follows_page_token(fake_session, feishu_settings):
    fake_session.queue_json(
        {"code": 0, "data": {"items": [{"record_id": "1", "fields": {}}], "has_more": True, "page_token": "next"}},
        {"code": 0, "data": {"items": [{"record_id": "2", "fields": {}}], "has_more": False}},
    )
    client = FeishuClient(feishu_settings, session=fake_session, sleeper=lambda _: None)
    assert [item["record_id"] for item in client.iter_records("app", "table", "view")] == ["1", "2"]


def test_permission_error_is_not_retried(fake_session, feishu_settings):
    fake_session.queue_response(status_code=403, payload={"code": 99991672, "msg": "forbidden"})
    client = FeishuClient(feishu_settings, session=fake_session, sleeper=lambda _: None)
    try:
        client.iter_records("app", "table", "view")
    except FeishuPermissionError:
        pass
    else:
        raise AssertionError("permission error was not raised")
    assert fake_session.request_count == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/creator_ops/test_feishu_client.py -q`

Expected: FAIL because the client is absent.

- [ ] **Step 3: Implement the Feishu client**

Implement token caching, 10-second timeouts, paginated reads, batch create in chunks of 500, and retry classification. Retry only timeouts, connection errors, HTTP `429`, and `5xx`, using delays of 1, 2, and 4 seconds. Raise `FeishuPermissionError` for `401/403` and `FeishuSchemaError` for Feishu field/table errors. Never include headers, tokens, or secrets in exception strings.

- [ ] **Step 4: Implement schema constants**

Define table keys matching the existing environment variables and field maps for account pool (`ID`, `平台`, `主账号`, `水号`), link tasks (`平台`, `标识`, `是否查询评论`), and user tasks. Keep comment compatibility fields but designate `user_id`, `avatar`, `ip_location`, `user_signature`, `sec_uid`, `short_user_id`, and `user_unique_id` as privacy-restricted.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_feishu_client.py -q`

Expected: PASS.

Commit: `feat: add Feishu operations client`

## Task 3: Feishu Task Planner and Browser Profile Mapping

**Files:**
- Create: `creator_ops/planner.py`
- Create: `tests/creator_ops/test_planner.py`

- [ ] **Step 1: Write failing planner tests**

```python
from creator_ops.domain import Platform, TaskKind
from creator_ops.planner import build_plan


def test_build_plan_maps_main_water_and_disabled_accounts(settings):
    accounts = [
        {"fields": {"ID": "%s_use_data_dir", "平台": "小红书", "主账号": True, "水号": False}},
        {"fields": {"ID": "%s_text_data_dir", "平台": "小红书", "主账号": False, "水号": True}},
        {"fields": {"ID": "%s_u1_data_dir", "平台": "抖音", "主账号": False, "水号": False}},
    ]
    links = [{"fields": {"平台": "小红书", "标识": "note-1", "是否查询评论": True}}]
    plan = build_plan(settings, accounts, links, [])
    assert [(task.platform, task.kind) for task in plan] == [
        (Platform.XHS, TaskKind.CREATOR_METRICS),
        (Platform.XHS, TaskKind.CONTENT_DETAIL),
    ]
    assert plan[1].profile.path.name == "xhs_text_data_dir"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/creator_ops/test_planner.py -q`

Expected: FAIL because `build_plan` is absent.

- [ ] **Step 3: Implement deterministic planning**

Normalize platform labels `小红书` and `抖音`, ignore unchecked accounts, reject missing browser directories with a task-level planning error, group link tasks by platform and comment flag, assign water profiles round-robin, and sort creator-metric tasks before public content tasks. User-page tasks use upstream creator mode but set `persist_profile=False`.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_planner.py -q`

Expected: PASS.

Commit: `feat: plan Feishu crawler tasks`

## Task 4: SQLAlchemy Operations Models and Repository

**Files:**
- Create: `creator_ops/storage/__init__.py`
- Create: `creator_ops/storage/models.py`
- Create: `creator_ops/storage/repository.py`
- Create: `tests/creator_ops/test_storage_models.py`
- Create: `tests/creator_ops/test_repository.py`

- [ ] **Step 1: Write failing model and repository tests**

```python
from datetime import date

from sqlalchemy import UniqueConstraint

from creator_ops.storage.models import CreatorContentMetricSnapshot


def test_content_snapshot_has_daily_business_key():
    constraints = [item for item in CreatorContentMetricSnapshot.__table__.constraints if isinstance(item, UniqueConstraint)]
    columns = {tuple(column.name for column in item.columns) for item in constraints}
    assert ("platform", "profile_key", "content_key", "snapshot_date") in columns
```

Add async repository tests against `TEST_MYSQL_URL` that insert the same business key twice, verify one row remains with updated metrics, verify transaction rollback, and verify outbox status transitions from `pending` to `synced`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/creator_ops/test_storage_models.py -q`

Expected: FAIL because models are absent.

- [ ] **Step 3: Implement models on the upstream Base**

Import `Base` from `database.models` and define `CreatorOpsRun`, `CreatorOpsTask`, `CreatorAccountMetricSnapshot`, `CreatorContentMetricSnapshot`, `CreatorPublicContentSnapshot`, and `CreatorOpsSyncOutbox`. Store metric payloads as `Text` containing canonical JSON for MySQL compatibility. Add the daily unique constraints described in the design.

- [ ] **Step 4: Implement repository transactions**

Provide `create_run`, `finish_run`, `start_task`, `finish_task`, `upsert_account_snapshot`, `upsert_content_snapshot`, `upsert_public_snapshot`, `enqueue_sync`, `pending_sync`, `mark_sync_succeeded`, and `mark_sync_failed`. Use SQLAlchemy `select` plus update-or-insert logic inside the upstream `get_session()` context.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_storage_models.py tests/creator_ops/test_repository.py -q`

Expected: model tests PASS; MySQL tests PASS when `TEST_MYSQL_URL` is configured and otherwise SKIP with an explicit reason.

Commit: `feat: add creator operations storage`

## Task 5: Creator-Center Normalizers and Collectors

**Files:**
- Create: `creator_ops/platforms/__init__.py`
- Create: `creator_ops/platforms/base.py`
- Create: `creator_ops/platforms/xhs_creator.py`
- Create: `creator_ops/platforms/douyin_creator.py`
- Create: `tests/creator_ops/test_xhs_creator.py`
- Create: `tests/creator_ops/test_douyin_creator.py`

- [ ] **Step 1: Write failing pure-normalizer tests**

```python
from creator_ops.platforms.xhs_creator import normalize_xhs_row


def test_normalize_xhs_row_converts_chinese_units():
    record = normalize_xhs_row(
        profile_key="%s_use_data_dir",
        row={"标题": "示例", "创建时间": "2026-07-20 10:00", "曝光": "1.2万", "点赞": "23"},
    )
    assert record.metrics["曝光"] == 12000
    assert record.metrics["点赞"] == 23
    assert record.content_key
```

Add the equivalent Douyin test for percentages, counts, title, publication time, and stable fallback keys.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/creator_ops/test_xhs_creator.py tests/creator_ops/test_douyin_creator.py -q`

Expected: FAIL because collectors are absent.

- [ ] **Step 3: Implement shared browser and normalizer helpers**

Implement `parse_metric_number`, canonical content-key generation, required-field validation, diagnostic screenshot paths, and a `CreatorCollector` protocol. Launch persistent Playwright contexts with the exact external profile path; do not copy profiles under the repository.

- [ ] **Step 4: Implement Xiaohongshu collector**

Visit `https://creator.xiaohongshu.com/statistics/data-analysis?source=official`, wait for the note-data table, parse all pages with bounded waits, normalize the current Chinese metric columns, and return `MetricRecord` objects. Use local screenshots on selector failure and never write Feishu directly.

- [ ] **Step 5: Implement Douyin collector**

Visit `https://creator.douyin.com/creator-micro/data-center/content`, open the submission list, load rows until three consecutive passes produce no new content or 50 passes complete, normalize metrics, and return `MetricRecord` objects. Use bounded waits and local screenshots.

- [ ] **Step 6: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_xhs_creator.py tests/creator_ops/test_douyin_creator.py -q`

Expected: PASS without network or real browser profiles.

Commit: `feat: collect creator center metrics`

## Task 6: Upstream Crawler Bridge Without argv or Event-Loop Mutation

**Files:**
- Create: `creator_ops/crawler_bridge.py`
- Create: `tests/creator_ops/test_crawler_bridge.py`

- [ ] **Step 1: Write failing state-restoration test**

```python
import config
import pytest

from creator_ops.crawler_bridge import crawler_config_scope


def test_crawler_config_scope_restores_globals_after_error():
    original = config.PLATFORM
    with pytest.raises(RuntimeError):
        with crawler_config_scope(platform="xhs", crawler_type="detail", user_data_dir="%s_text_data_dir"):
            assert config.PLATFORM == "xhs"
            raise RuntimeError("stop")
    assert config.PLATFORM == original
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/creator_ops/test_crawler_bridge.py -q`

Expected: FAIL because the bridge is absent.

- [ ] **Step 3: Implement scoped upstream calls**

Implement a context manager that snapshots only the upstream global settings needed by a task, applies explicit values, and restores them in `finally`. Implement `run_public_task(task)` that initializes MySQL through `database.db`, creates the existing crawler through `CrawlerFactory`, awaits `start()` in the already-running event loop, and closes browser resources. Do not modify `sys.argv` or call `asyncio.run()`.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_crawler_bridge.py -q`

Expected: PASS.

Commit: `feat: bridge operations tasks to upstream crawlers`

## Task 7: Privacy-Safe Feishu Sync and Workflow Runner

**Files:**
- Create: `creator_ops/sync.py`
- Create: `creator_ops/runner.py`
- Create: `tests/creator_ops/test_sync.py`
- Create: `tests/creator_ops/test_runner.py`

- [ ] **Step 1: Write failing privacy and continuation tests**

```python
from creator_ops.sync import sanitize_comment_fields


def test_sanitize_comment_fields_removes_public_identity():
    output = sanitize_comment_fields({
        "comment_id": "c1",
        "content": "hello",
        "creator_hash": "hash",
        "nickname": "张*三",
        "user_id": "raw-user",
        "avatar": "https://private",
        "ip_location": "北京",
        "user_signature": "secret",
    })
    assert output["creator_hash"] == "hash"
    assert output["nickname"] == "张*三"
    assert output["user_id"] == ""
    assert output["avatar"] == ""
    assert output["ip_location"] == ""
    assert output["user_signature"] == ""
```

Add a runner test with two fake tasks where the first raises and the second succeeds; assert both are attempted and the final exit status is partial failure.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/creator_ops/test_sync.py tests/creator_ops/test_runner.py -q`

Expected: FAIL because sync and runner modules are absent.

- [ ] **Step 3: Implement payload mapping and outbox delivery**

Map normalized official metrics to the existing Xiaohongshu and Douyin statistics fields. Map comments to current fields while blanking restricted identity fields. Deliver pending outbox rows in batches, mark successful rows, retain failed rows, and expose a summary with attempted, succeeded, and failed counts.

- [ ] **Step 4: Implement workflow runner**

The runner must validate settings, load all three Feishu control tables before opening browsers, create a run row, build the plan, execute tasks sequentially by profile, write MySQL before outbox delivery, continue independent tasks after failure, close resources in `finally`, and return `0`, `1`, or `2` according to the approved design. `dry_run=True` performs reads, planning, profile validation, and collector parsing without MySQL or Feishu writes.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_sync.py tests/creator_ops/test_runner.py -q`

Expected: PASS.

Commit: `feat: orchestrate creator operations workflow`

## Task 8: CLI, Windows Launcher, and Operator Guide

**Files:**
- Create: `creator_ops/cli.py`
- Create: `creator_ops/__main__.py`
- Create: `start_creator_ops.cmd`
- Create: `docs/creator_ops_guide.md`
- Create: `tests/creator_ops/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
from typer.testing import CliRunner

from creator_ops.cli import app


runner = CliRunner()


def test_cli_exposes_required_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run-all" in result.stdout
    assert "collect-only" in result.stdout
    assert "sync-only" in result.stdout
    assert "validate-config" in result.stdout
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/creator_ops/test_cli.py -q`

Expected: FAIL because the CLI is absent.

- [ ] **Step 3: Implement CLI commands**

Use Typer with commands `run-all`, `collect-only`, `sync-only`, and `validate-config`. `run-all` accepts `--dry-run`. Each command calls one `asyncio.run()` at the process boundary only and exits with the runner's numeric status.

- [ ] **Step 4: Implement portable Windows launcher**

```bat
@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m creator_ops run-all %*
) else (
  python -m creator_ops run-all %*
)
exit /b %errorlevel%
```

- [ ] **Step 5: Write operator documentation**

Document environment setup, `D:\browser_data` mapping, MySQL initialization, Feishu permissions and table variables, dry-run, normal execution, Windows Task Scheduler configuration, `sync-only` recovery, login-expired handling, and the fact that browser profiles and secrets must never be committed.

- [ ] **Step 6: Run tests and commit**

Run: `python -m pytest tests/creator_ops/test_cli.py -q`

Expected: PASS.

Commit: `feat: add creator operations CLI and launcher`

## Task 9: Migration Compatibility, Security Scan, and Full Verification

**Files:**
- Create: `creator_ops/migrate.py`
- Create: `tests/creator_ops/test_migrate.py`
- Modify: `docs/creator_ops_guide.md`

- [ ] **Step 1: Write failing legacy-filter test**

```python
from creator_ops.migrate import eligible_legacy_creator_row


def test_legacy_external_creator_is_not_eligible():
    assert not eligible_legacy_creator_row({"user_id": "external"}, owned_user_ids={"owned"})
    assert eligible_legacy_creator_row({"user_id": "owned"}, owned_user_ids={"owned"})
```

- [ ] **Step 2: Implement explicit legacy migration rules**

Provide a command that can import historical content snapshots and comments from the old MySQL schema. Creator-profile history imports require an explicit owned-user allowlist and otherwise skip every row. Never infer ownership from nickname, avatar, IP, or browser-profile name.

- [ ] **Step 3: Run targeted and full tests**

Run: `python -m pytest tests/creator_ops -q`

Expected: all unit tests PASS; MySQL/live tests may SKIP only with documented reasons.

Run: `python -m pytest tests -q`

Expected: upstream regression suite PASS.

- [ ] **Step 4: Run static and repository checks**

Run: `python -m compileall creator_ops tests/creator_ops`

Expected: success with no syntax errors.

Run: `git diff --check`

Expected: no output.

Run secret scans for `FEISHU_APP_SECRET` assignments, bearer tokens, cookies, passwords, `.env`, `browser_data`, runtime screenshots, and private HTML artifacts. Expected: only empty examples and environment lookups are tracked.

- [ ] **Step 5: Perform local acceptance checks**

Run: `python -m creator_ops validate-config`

Expected: a redacted configuration summary and success.

Run: `python -m creator_ops run-all --dry-run`

Expected: Feishu tables read successfully, profile templates map to directories under `D:\browser_data`, pages parse, and no MySQL/Feishu write occurs.

- [ ] **Step 6: Commit final migration and verification fixes**

Commit: `test: verify creator operations migration`

## Task 10: Fork, Push, and Pull Request

**Files:** none.

- [ ] **Step 1: Verify GitHub authentication**

Run: `gh auth status -h github.com`

Expected: active authenticated account is `752801828`.

- [ ] **Step 2: Create or connect the fork**

Run: `gh repo fork NanmiCoder/MediaCrawler --clone=false --remote=false`

Expected: `752801828/MediaCrawler` exists. Add it as remote `fork` while retaining `origin` as upstream.

- [ ] **Step 3: Re-run final checks**

Run: `git status --short`, `python -m pytest tests/creator_ops -q`, and the secret scan.

Expected: clean worktree, passing tests, no secrets.

- [ ] **Step 4: Push the migration branch**

Run with HTTP/1.1 because this network resets HTTP/2 connections:

`git -c http.version=HTTP/1.1 push -u fork codex/creator-ops-migration`

Expected: branch is available on the fork.

- [ ] **Step 5: Open a pull request against the fork main branch**

Create a ready pull request summarizing architecture, privacy constraints, test evidence, local acceptance steps still requiring real credentials, and the unchanged non-commercial license.
