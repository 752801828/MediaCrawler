# MediaCrawler Creator Operations Migration Design

Status: Approved on 2026-07-21

## Context

The custom repository at commit `7cab7fe` combines an older MediaCrawler core with a Feishu-driven operations workflow. The target repository is the current upstream baseline at commit `0625e01`. The upstream project now uses Typer, SQLAlchemy, a modern database package, CDP browser support, a WebUI, and privacy-preserving storage. Directly copying the custom repository would overwrite those improvements and restore legacy database and event-loop code.

This migration keeps the upstream core authoritative and adds an isolated operations layer for the user's own Xiaohongshu and Douyin creator accounts.

## Goals

- Fork `NanmiCoder/MediaCrawler` under GitHub account `752801828`.
- Preserve the existing Feishu-driven task workflow and current Feishu table schemas.
- Collect the user's own Xiaohongshu and Douyin creator-platform metrics.
- Run targeted link and comment tasks with the existing main-account/water-account pool.
- Store operational history in MySQL through the upstream SQLAlchemy stack.
- Reuse browser profiles from `D:\browser_data` without copying them into Git.
- Provide both a native CLI and a one-click Windows launcher.
- Run one complete workflow and exit so Windows Task Scheduler can schedule it.
- Keep the upstream privacy model for public creators, content authors, and commenters.

## Non-Goals

- Persisting identifiable profiles for external creators.
- Uploading browser profiles, cookies, local storage, secrets, runtime screenshots, or logs.
- Migrating unrelated experiments such as `sph/`, `media_platform/texct/`, search demos, one-off database repair scripts, or screenshots.
- Replacing the upstream crawler, WebUI, database layer, or browser utilities with the legacy versions.
- Adding an internal long-running scheduler.

## Architecture

Add a `creator_ops/` package alongside the upstream code. The package owns Feishu orchestration, creator-platform collectors, MySQL snapshots, synchronization state, and its CLI. Upstream platform crawlers remain responsible for public content and comments.

The primary flow is:

```text
Feishu task tables and account pool
                |
                v
          Task planner
                |
                v
     Sequential account runner
          /             \
         v               v
Creator-platform      Upstream public
collectors            content crawlers
          \             /
           v           v
           MySQL snapshots
                  |
                  v
          Feishu sync outbox
                  |
                  v
       Existing Feishu tables
```

Two entry points call the same application service:

- `python -m creator_ops run-all`
- `start_creator_ops.cmd`

Additional operational commands are `validate-config`, `collect-only`, and `sync-only`. A `--dry-run` option validates task reading, profile mapping, and page parsing without writing MySQL or Feishu.

## Components

### Configuration

`creator_ops/config.py` loads typed settings from environment variables and `.env`. It validates Feishu identifiers, MySQL settings, and the external browser-data root before work starts. `BROWSER_DATA_ROOT` defaults to `D:\browser_data` on this installation but is configurable.

Secrets are never logged. `.env.example` documents variable names with empty values. `.env`, `browser_data/`, runtime diagnostics, and logs are ignored by Git.

### Feishu Adapter

`creator_ops/feishu/client.py` provides token acquisition, paginated reads, batched writes, timeouts, and bounded retries. `creator_ops/feishu/schema.py` contains all existing Chinese field names and target-table mappings so platform collectors do not depend on Feishu.

The adapter reads the existing link table, user table, and account-pool table. It writes to the existing Xiaohongshu statistics, Douyin statistics, creator-history, and comment tables without requiring field or table changes.

### Task Planner

`creator_ops/planner.py` converts Feishu records into typed tasks:

- A checked `主账号` record creates a creator-platform collection task.
- A checked `水号` record can receive targeted link, comment, or public creator-content tasks.
- A record with neither checkbox enabled is ignored.
- The account-pool `ID` is a browser-directory template such as `%s_use_data_dir`; `%s` becomes `xhs` or `dy`.

The known profile mappings are:

- `%s_use_data_dir` to `xhs_use_data_dir` or `dy_use_data_dir`
- `%s_text_data_dir` to `xhs_text_data_dir` or `dy_text_data_dir`
- `%s_u1_data_dir` to `dy_u1_data_dir`

Tasks sharing a browser profile are serialized.

### Creator-Platform Collectors

`creator_ops/platforms/xhs_creator.py` and `creator_ops/platforms/douyin_creator.py` visit the official creator centers with the assigned persistent browser profile. They return normalized domain records and never write directly to Feishu or MySQL.

Collectors use bounded waits, multiple stable selectors where practical, row validation, and platform-specific normalizers. A stable content key uses the platform content ID or URL when available and falls back to a hash of platform, account profile, title, and publication time.

### Upstream Crawler Bridge

`creator_ops/crawler_bridge.py` invokes current upstream crawler services for targeted links and public creator content. It passes explicit task configuration and does not mutate `sys.argv`, create nested event loops, or copy the legacy platform cores.

Public creator profiles are not persisted. Public content and comments retain upstream creator hashes and masked nicknames. Raw public IDs, avatars, IP locations, signatures, and genders are not reintroduced.

### Storage

`creator_ops/storage/` registers SQLAlchemy models on the upstream database metadata and uses the upstream async session factory. MySQL migrations create:

- `creator_ops_run`: one row per workflow execution with timestamps, counts, and final status.
- `creator_ops_task`: task status, platform, profile key, attempts, and sanitized error details.
- `creator_account_metric_snapshot`: daily snapshots for the user's own creator accounts.
- `creator_content_metric_snapshot`: daily official creator-platform content metrics with normalized keys and a JSON metric payload.
- `creator_public_content_snapshot`: privacy-preserving daily public content metric snapshots.
- `creator_ops_sync_outbox`: pending, synced, or failed Feishu deliveries with attempt metadata.

Daily snapshot uniqueness is enforced by platform, profile/account key, content key, and snapshot date. Re-running the workflow on the same day updates the snapshot instead of inserting a duplicate.

Existing upstream content and comment tables remain authoritative for crawler output.

### Synchronization

`creator_ops/sync/` converts committed MySQL records to current Feishu fields and creates outbox entries. Feishu delivery happens only after the MySQL transaction commits.

The old row-count comparison is removed because it cannot identify missing or reordered records. Local business keys and outbox state provide idempotence. Existing Feishu comment IDs can be read during initial reconciliation to avoid resending known comments.

Creator-history targets receive only the user's main-account data. Public comment compatibility fields remain present in Feishu, but identifiable values are empty or anonymized.

## Data Flow

1. Validate environment variables, MySQL connectivity, Feishu access, and browser-profile directories.
2. Read the three Feishu control tables and build an ordered task plan.
3. Execute creator-platform tasks for main accounts and upstream content/comment tasks for water accounts.
4. Normalize and validate results.
5. Commit snapshots and crawler output to MySQL in transactions.
6. Create Feishu outbox records in the same transaction as the operational data.
7. Deliver pending outbox records in batches and record success or failure.
8. Close every browser and database session.
9. Print a sanitized summary and exit.

Exit codes are:

- `0`: all tasks and required synchronization succeeded.
- `1`: one or more tasks or deliveries failed, but the workflow completed.
- `2`: configuration, Feishu task loading, or initialization failed before task execution.

## Error Handling

- If Feishu control-table reads fail, no browser tasks start.
- A missing browser profile fails only tasks assigned to that profile.
- An expired login opens a visible browser for manual login and then times out as `login_required` if unresolved.
- Missing required page fields prevent that row from being stored.
- Page-structure failures create local, Git-ignored diagnostic screenshots.
- MySQL errors roll back the current transaction and prevent matching Feishu writes.
- Feishu `429`, timeout, and `5xx` responses use bounded exponential backoff.
- Feishu permission and schema `4xx` errors fail immediately with a sanitized message.
- Task failures do not prevent independent later tasks from running.
- Browser contexts and database sessions close in `finally` blocks.

## Testing

Automated tests cover:

- Configuration validation and secret redaction.
- Account-pool and task-table planning.
- Disabled account records and browser-template expansion.
- Feishu pagination, batching, retry classification, and schema errors.
- Xiaohongshu and Douyin normalization using synthetic page/locator fixtures.
- MySQL daily upsert constraints, rollback, and outbox state transitions.
- Public author/comment anonymization.
- Partial failure continuation and process exit codes.
- CLI help, validation, dry-run behavior, and Windows launcher invocation.
- Repository secret and ignored-file checks.

MySQL integration tests use a dedicated `TEST_MYSQL_URL` database and are skipped when it is absent. Live creator-platform tests are explicitly marked and never run in GitHub Actions.

Manual acceptance is:

1. Run `validate-config`.
2. Run `run-all --dry-run` and verify Feishu reads, task planning, browser profiles, and page parsing without writes.
3. Run one Xiaohongshu main account and one Douyin main account.
4. Verify MySQL snapshots and existing Feishu-table output.
5. Repeat the run and verify same-day deduplication.
6. Force a Feishu delivery failure and verify `sync-only` completes the pending delivery later.

## Security and Repository Hygiene

The migration copies no credential values or browser data. Before every push, tracked files and commit history are scanned for Feishu secrets, tokens, cookies, database passwords, and private browser artifacts. Any finding blocks the push. The original project's non-commercial learning license and usage restrictions remain unchanged.

## Delivery

Work is performed on `codex/creator-ops-migration`. After implementation and verification, the branch is pushed to the `752801828` fork and opened as a pull request against that fork's `main` branch. The upstream remote remains configured for future updates.
