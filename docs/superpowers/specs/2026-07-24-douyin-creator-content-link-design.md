# Douyin Creator Content Link Design

## Goal

Collect each work's public Douyin URL from the creator-platform submission
table without opening the per-work analysis page. Persist the URL to MySQL and
send it to the existing Feishu `作品链接` text field.

## Scope

- Douyin creator metrics only.
- Read the work identity from the submission row's DOM and its bound frontend
  data.
- Build the public URL as `https://www.douyin.com/video/{aweme_id}`.
- Store the URL in `creator_content_metric_snapshot.content_url`.
- Include the URL in the Douyin metrics Feishu payload.
- Do not change Xiaohongshu collection or public-content crawler tables.

## Collection Flow

1. Wait until the Douyin creator submission table is visible.
2. Ignore table rows that contain no `td` cells, including the header row.
3. Read title, publication time, and metrics from each visible data row.
4. Inspect the row element and its bound frontend data for an aweme/work ID.
   The extractor accepts numeric IDs from known ID-shaped keys and creator
   work-detail/public-video URL paths.
5. Generate the public URL from the extracted ID.
6. Deduplicate virtualized rows by work ID when present, otherwise by
   title plus publication time.
7. Normalize and persist the metric record, then enqueue its Feishu payload.

## Data Model and Sync

`MetricRecord` gains an optional `content_url` field. The content key uses the
extracted work ID when available, preserving the existing title-and-time hash
fallback when it is not.

`CreatorContentMetricSnapshot` gains a nullable `content_url` column. The
existing additive schema migration will add it to an existing MySQL table.
Upserts update the URL so previously stored daily rows can be enriched by a
later successful extraction.

The Feishu metrics payload includes `作品链接` as a plain URL string because
the configured Feishu field is Text. Douyin metrics are written to the table's
writable text input fields. Percentage metrics use the corresponding
underscore-suffixed source fields and retain the `%` suffix; the table's
formula fields remain read-only.

The sync outbox stores the Feishu `record_id` returned by the first create
request. A later payload change for the same business key uses batch update
against that record ID instead of creating a duplicate row.

## Error Handling

- Header and other non-data rows are skipped.
- A malformed row does not terminate the whole creator task.
- If a row has metrics but no discoverable work ID, save the metrics with the
  existing fallback content key and an empty URL, and emit a warning.
- The implementation never logs cookies, tokens, or the bound frontend data
  contents.

## Verification

- Unit tests cover ID extraction from DOM-bound data and URL-shaped values.
- Collector tests cover header skipping and malformed-row isolation.
- Normalization tests cover content key and public URL behavior.
- Storage tests cover insertion and update of `content_url`.
- Feishu payload tests cover the `作品链接` field.
- Sync tests cover first-time create ID capture and later batch update.
- Run the Douyin creator-metrics-only command and verify a successful workflow,
  non-empty MySQL URLs, and successful Feishu outbox delivery.
