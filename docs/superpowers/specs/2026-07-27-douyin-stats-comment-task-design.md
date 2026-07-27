# Douyin Stats Table Comment Task Design

## Goal

Add a recurring Douyin comment task driven by Feishu table
`tblIvCULqR10ZywX`. The task collects all first-level and second-level comments
for works published strictly after `2026-07-01 00:00:00`.

## Source Selection

The Feishu records API applies this filter on the server:

```text
AND(
  CurrentValue.[创建时间] > "2026-07-01 00:00:00",
  CurrentValue.[作品链接] != ""
)
```

Only `创建时间` and `作品链接` are requested. The current table returns 51
matching snapshot rows and 13 unique works. Work IDs are parsed from
`https://www.douyin.com/video/{id}` URLs and deduplicated by ID. Empty,
malformed, and non-Douyin links are skipped with sanitized warnings.

## Planning and Execution

A new task kind represents the stats-table comment refresh. `run-all`
automatically includes one task when matching works exist. The planner assigns
the active Douyin water profile; it never falls back to a main account.

The public crawler bridge executes the task as a Douyin detail crawl with both
first-level and second-level comments enabled. It re-fetches all comments on
every run so comments added after an earlier run are discovered. Existing
MySQL comment rows are updated by `comment_id`, avoiding duplicates.

## Standalone Command

The CLI adds a dedicated command for this task. It defaults to
`2026-07-01`, accepts an `--after YYYY-MM-DD` override, and runs only the new
task kind. The normal `run-all` command continues to use the default boundary.

## Feishu Comment Sync

After the crawler completes, newly discovered Douyin comments are queued to the
existing Douyin comment table and delivered through the existing outbox.
Already-synced comment IDs are not enqueued again. Comment field handling and
privacy behavior remain unchanged.

## Error Handling

- A missing active Douyin water profile raises a planning error.
- Invalid date input exits with a configuration-style error before opening a
  browser.
- Invalid source rows do not fail the task.
- A fatal crawler or Feishu error follows the existing per-task failure and
  workflow summary behavior.
- The task banner identifies the stats-table comment task, selected water
  profile, target count, and first-/second-level comment status before browser
  interaction.

## Verification

- Feishu client tests cover filter and selected-field pagination parameters.
- Source parsing tests cover the strict date boundary, URL validation, and
  work-ID deduplication.
- Planner tests cover automatic inclusion and water-profile assignment.
- Crawler bridge tests cover detail mode and both comment levels.
- CLI tests cover the standalone command and `--after` validation.
- Runner tests cover comment queueing and Feishu delivery.
- A live dry run verifies the current 13 unique works before the first full
  collection.

