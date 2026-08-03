# Douyin Root Comment Reply Sync Design

## Goal

Sync only Douyin root comments to Feishu while using child comments to calculate whether NOVSIGHT replied and to build a readable full conversation chain.

## Scope

- Change only the Douyin comment synchronization path.
- Leave Xiaohongshu behavior unchanged.
- Read all Douyin comments from MySQL, but upload only rows whose `parent_comment_id` is empty or `0`.
- Use only fields that currently exist in the configured Douyin Feishu table.

## Reply Detection

A root comment is considered replied when at least one child comment under that root satisfies:

```text
lower(trim(user_unique_id)) == "novsight"
```

Write `是否回复` as `是` when matched and `否` otherwise. When no NOVSIGHT reply exists, `回复内容` is empty.

## Conversation Chain

When a NOVSIGHT reply exists, build `回复内容` from the root comment and every child comment under the same root. Sort entries by `create_time` and then the local database ID. Include comments that occur after the NOVSIGHT reply.

Each entry occupies one line:

```text
nickname：comment content
```

Replace line breaks inside nicknames or comment content with spaces before joining the entries.

## Feishu Mapping

Map the MySQL root comment fields to the current Feishu fields:

- `id` -> `id`
- `user_id` -> `用户ID`
- `sec_uid` -> `sec_uid`
- `short_user_id` -> `用户短ID`
- `user_unique_id` -> `user_unique_id`
- `nickname` -> `用户昵称`
- `avatar` -> `avatar`
- `user_signature` -> `user_signature`
- `ip_location` -> `ip_location`
- `comment_id` -> `评论ID`
- `aweme_id` -> `视频ID`
- `content` -> `评论内容`
- `create_time` -> `评论时间`
- `like_count` -> `点赞数`
- `pictures` -> `评论图片列表`
- reply status -> `是否回复`
- conversation chain -> `回复内容`

Do not send removed fields or the Feishu automatic `创建时间` field.

## Synchronization Behavior

The current Feishu table is empty, so the first run recreates the 364 root comments. The expected current classification is 10 replied and 354 not replied. Eleven NOVSIGHT child replies currently belong to those ten root threads.

On later runs, queue every root payload through the outbox. An unchanged payload remains synced. A newly collected child reply changes the root payload, which marks the existing outbox row pending and updates the existing Feishu root record. Child-comment outbox rows are not queued or delivered by this workflow.

## Error Handling

- If the Feishu record inventory is unavailable, do not clear stored remote record IDs.
- If a root record was deleted from Feishu after a successful inventory read, clear its stale remote ID and recreate it.
- Report Feishu schema or write failures through the existing outbox failure summary.

## Testing

- Verify only root comments produce Feishu payloads.
- Verify NOVSIGHT matching is trimmed and case-insensitive.
- Verify a replied chain contains the root and every time-ordered child, including later replies.
- Verify internal line breaks are normalized to spaces.
- Verify an unreplied root writes `是否回复=否` and an empty `回复内容`.
- Verify Chinese field mapping contains only current Feishu fields.
- Verify a later child reply updates the existing root outbox row.
- Verify Xiaohongshu synchronization remains unchanged.

## Non-goals

- Do not upload individual Douyin child comments.
- Do not change Douyin collection or MySQL storage.
- Do not change Xiaohongshu comment synchronization.
