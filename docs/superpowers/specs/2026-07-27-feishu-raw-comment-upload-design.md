# Feishu Raw Comment Upload Design

## Goal

All future comment records uploaded to Feishu must preserve the original user fields stored in MySQL. No nickname masking, anonymous user ID substitution, or deliberate field clearing remains in the upload path.

## Scope

- Apply to Douyin and Xiaohongshu comment uploads handled by `OutboxSynchronizer`.
- Preserve raw identity and profile fields when present in the platform model, including user IDs, nickname, avatar, signature, and IP location.
- Keep timestamp formatting required by the Feishu field types.
- Keep `comment_id` as the idempotency key and continue preventing duplicate records.
- Leave creator metrics, work metrics, tag storage, and other uploads unchanged because they do not currently apply comment identity masking.

## Historical Data Boundary

This change is forward-only. Existing Feishu records are not rewritten. `queue_platform_comments` continues reading existing Feishu `comment_id` values and skips those records, so previously masked rows remain unchanged.

## Data Flow

1. Read comment rows from the existing MySQL platform comment table.
2. Build a complete platform-specific comment dictionary rather than the previous restricted subset.
3. Convert only timestamp values to Feishu-compatible date-time strings.
4. Enqueue the raw payload in the existing outbox.
5. Create only comment IDs not already present in the configured Feishu comment table.

## Error Handling

The uploader does not silently discard fields. If a configured Feishu table lacks a field contained in the raw payload, the existing Feishu schema error path marks the outbox row as failed and reports the failure type. Existing retry and batch behavior remains unchanged.

## Testing

- Verify Douyin payloads preserve raw IDs, nickname, avatar, signature, and IP location.
- Verify Xiaohongshu payloads preserve raw IDs, nickname, avatar, and IP location.
- Verify timestamps remain formatted.
- Verify existing Feishu comment IDs are skipped and therefore historical records are not overwritten.
- Run the creator-ops suite and the full suite excluding local Redis integration tests.

## Non-goals

- Do not backfill or restore existing masked Feishu records.
- Do not change collection behavior or MySQL schemas.
- Do not introduce a privacy toggle because raw upload is the required permanent behavior.
