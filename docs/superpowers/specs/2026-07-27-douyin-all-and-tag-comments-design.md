# Douyin All Comments and Tag Comment Isolation Design

## Goal

Upload every Douyin root and child comment, replace the conversation-chain field with a parent-comment reference, add comment collection for recent Tag videos, and keep Tag comments isolated from ordinary Douyin comments in both MySQL and Feishu.

## Scope

- Change only the Douyin comment collection and synchronization paths.
- Keep Xiaohongshu comment behavior unchanged.
- Upload both root and child Douyin comments.
- Change the official-content comment window from the fixed `2026-07-01` cutoff to a rolling two-calendar-month window.
- Collect comments for Tag videos published within the same rolling two-calendar-month window.
- Store Tag comments in a new MySQL table and sync them to Feishu table `tbl2YGN6CJszL4Ri`.
- Continue using the configured water-account browser profile for public Douyin and Tag comment collection.

## Selected Architecture

Use task-scoped comment storage routing while reusing the existing Douyin comment API, parsing, pagination, sub-comment, retry, and browser-profile logic.

The alternatives were rejected because copying Tag comments through the ordinary comment table would violate storage isolation, while a completely separate Tag comment crawler would duplicate substantial upstream behavior.

## Rolling Time Window

Both official-content comments and Tag-video comments use a cutoff calculated when the workflow starts:

```text
cutoff = current local date minus two calendar months
```

Content published on or after the cutoff is included. This replaces the fixed official-content cutoff currently used by `DOUYIN_STATS_COMMENTS`.

For Tag collection:

1. Refresh Tag works through the existing Tag API.
2. Read works belonging to the active Tag target from `douyin_tag_aweme`.
3. Select only works whose `published_at` is on or after the cutoff.
4. Run the existing Douyin detail-comment flow for the selected video IDs.

## MySQL Storage

Add a new `douyin_tag_aweme_comment` table. Its comment fields match `douyin_aweme_comment`, including raw user identifiers, nickname, content, reply relationship, image URLs, timestamps, and counts.

The unique key is:

```text
(aweme_id, comment_id)
```

The same video and comment are stored only once even if the video appears under multiple Tag targets. Tag-to-video provenance remains available through `douyin_tag_aweme`; the Tag comment table does not duplicate Tag IDs.

During an ordinary Douyin comment task, parsed comments continue to upsert into `douyin_aweme_comment`. During the Tag comment phase, the same parser and store interface route upserts exclusively to `douyin_tag_aweme_comment`. Tag comments must never be written to the ordinary comment table.

## Feishu Targets

Ordinary Douyin comments continue syncing to the configured ordinary Douyin comment table.

Tag comments use a separate outbox target:

```text
douyin_tag_comments
```

That target maps to Feishu table:

```text
tbl2YGN6CJszL4Ri
```

Add a dedicated configuration value for the Tag comment table ID, with `tbl2YGN6CJszL4Ri` as its default. The normal and Tag queues use distinct business-key namespaces so their remote record IDs and retry states cannot collide.

## Comment Payload

Every root and child comment produces one Feishu record. Map raw MySQL values without masking:

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

Do not send fields removed from the current Feishu schemas. Do not send the automatic `创建时间` field.

### Reply Reference

Replace the old full conversation-chain payload with `回复内容ID`:

- A root comment writes an empty string.
- A child comment writes its `parent_comment_id`.

No nickname/content conversation chain is constructed.

### Reply Status

NOVSIGHT matching remains trimmed and case-insensitive:

```text
lower(trim(user_unique_id)) == "novsight"
```

Write `是否回复` as follows:

- Root comment: `是` when any child under that root is a NOVSIGHT reply; otherwise `否`.
- Child comment: `是` when the child itself is a NOVSIGHT reply; otherwise `否`.

Apply these rules identically to ordinary and Tag comments.

## Workflow and Synchronization

An ordinary comment task:

1. Select official-content links within the rolling two-month window.
2. Collect root and child comments into `douyin_aweme_comment`.
3. Queue all ordinary root and child payloads.
4. Deliver them to the ordinary Douyin Feishu table.

A Tag task:

1. Refresh Tag works into `douyin_tag_aweme`.
2. Select Tag videos within the rolling two-month window.
3. Collect root and child comments into `douyin_tag_aweme_comment`.
4. Queue all Tag root and child payloads.
5. Deliver them to `tbl2YGN6CJszL4Ri`.

Existing ordinary root records are updated to the new field mapping. Ordinary child comments that were previously excluded are created as individual Feishu records. Existing stale outbox rows use the current Feishu inventory behavior so deleted remote records are recreated instead of repeatedly updated.

## Error Handling

- Comment upserts are idempotent under the `(aweme_id, comment_id)` unique key.
- If Tag work refresh succeeds but comment collection fails, retain the refreshed works and any comments already upserted; mark the task failed so a later run can retry.
- A Feishu failure never deletes MySQL data. The failed outbox row remains available for retry.
- A failure in the Tag comment target does not redirect its rows to the ordinary target.
- Existing sanitized exception reporting remains in place so tokens, cookies, and signed request data are not logged.

## Testing

- Verify the rolling cutoff is two calendar months for both official-content and Tag-video comments.
- Verify Tag videos older than the cutoff are not passed to the comment crawler.
- Verify ordinary root and child comments both produce payloads.
- Verify a root writes an empty `回复内容ID`.
- Verify a child writes its parent comment ID.
- Verify root reply status is based on NOVSIGHT children.
- Verify child reply status is based on the child's own identity.
- Verify matching is trimmed and case-insensitive.
- Verify Tag comments upsert only into `douyin_tag_aweme_comment`.
- Verify `(aweme_id, comment_id)` prevents duplicate Tag comment rows.
- Verify ordinary and Tag outbox targets and Feishu table IDs remain isolated.
- Verify raw user, nickname, content, and image URL fields are preserved.
- Verify Xiaohongshu behavior remains unchanged.
- Run the focused creator-operations tests and the full project test suite.

## Non-goals

- Do not download comment images or upload them as Feishu attachments; continue storing their source URLs.
- Do not add Tag metadata columns to the current Tag comment Feishu schema.
- Do not copy existing ordinary-comment rows into the Tag comment table.
- Do not change the Tag work unique key or Tag work Feishu control table.
- Do not push changes to `NanmiCoder/MediaCrawler`.
