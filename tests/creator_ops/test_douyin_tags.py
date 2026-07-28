from datetime import datetime

import pytest

from creator_ops.douyin_tags import (
    DouyinTagTarget,
    enrich_douyin_tag_aweme_row,
    extract_douyin_tag_aweme,
    is_excluded_douyin_tag_author_id,
    is_excluded_douyin_tag_aweme,
    is_novsight_tag_aweme,
    parse_douyin_tag_target,
)


def test_parse_standard_douyin_hashtag_url():
    target = parse_douyin_tag_target(
        "#越野射灯",
        "https://www.douyin.com/hashtag/7322391300177987638",
    )

    assert target == DouyinTagTarget(
        tag_id="7322391300177987638",
        tag_name="#越野射灯",
        tag_url="https://www.douyin.com/hashtag/7322391300177987638",
    )


def test_parse_hashtag_url_removes_query_and_fragment():
    target = parse_douyin_tag_target(
        "tag",
        "https://www.douyin.com/hashtag/7322391300177987638?from=web#top",
    )

    assert target.tag_url == "https://www.douyin.com/hashtag/7322391300177987638"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.com/hashtag/7322391300177987638",
        "https://www.douyin.com/video/7322391300177987638",
        "https://www.douyin.com/hashtag/not-a-number",
    ],
)
def test_parse_hashtag_url_rejects_invalid_values(url):
    with pytest.raises(ValueError):
        parse_douyin_tag_target("tag", url)


def test_extract_tag_aweme_uses_author_id_fallbacks():
    target = DouyinTagTarget("tag-1", "Tag", "https://www.douyin.com/hashtag/tag-1")
    base = {
        "aweme_id": "aweme-1",
        "author": {"uid": "uid-1", "sec_uid": "sec-1"},
    }

    assert extract_douyin_tag_aweme(target, base, source_cursor=12)["author_id"] == "uid-1"

    base["author"]["uid"] = ""
    base["author_user_id"] = 200
    assert extract_douyin_tag_aweme(target, base, source_cursor=12)["author_id"] == "200"

    base["author_user_id"] = 0
    assert extract_douyin_tag_aweme(target, base, source_cursor=12)["author_id"] == "sec-1"


def test_extract_tag_aweme_maps_stable_fields_and_raw_json():
    target = DouyinTagTarget(
        "7322391300177987638",
        "#越野射灯",
        "https://www.douyin.com/hashtag/7322391300177987638",
    )
    aweme = {
        "aweme_id": "aweme-1",
        "item_title": "Title",
        "desc": "Description",
        "aweme_type": 4,
        "media_type": 1,
        "create_time": 1720000000,
        "region": "CN",
        "share_url": "https://www.douyin.com/video/aweme-1",
        "author": {
            "uid": "author-1",
            "sec_uid": "sec-1",
            "unique_id": "author-name",
            "nickname": "Author",
            "account_region": "CN",
            "custom_verify": "Verified",
            "enterprise_verify_reason": "",
            "follower_count": 100,
            "following_count": 10,
            "total_favorited": 1000,
        },
        "statistics": {
            "play_count": 1000,
            "digg_count": 100,
            "comment_count": 10,
            "share_count": 5,
            "collect_count": 8,
            "exposure_count": 1200,
            "recommend_count": 7,
        },
        "video": {
            "duration": 12345,
            "width": 1080,
            "height": 1920,
            "cover": {"url_list": ["https://cover"]},
            "play_addr": {"url_list": ["https://play"]},
        },
        "text_extra": [{"hashtag_id": "7322391300177987638"}],
        "video_tag": [{"tag_id": 1}],
    }

    row = extract_douyin_tag_aweme(target, aweme, source_cursor=12)

    assert row["aweme_id"] == "aweme-1"
    assert row["author_id"] == "author-1"
    assert row["author_unique_id"] == "author-name"
    assert row["published_at"] == datetime.fromtimestamp(1720000000)
    assert row["duration_ms"] == 12345
    assert row["cover_url"] == "https://cover"
    assert row["play_url"] == "https://play"
    assert row["play_count"] == 1000
    assert '"aweme_id":"aweme-1"' in row["raw_aweme_json"]
    assert "Cookie" not in row["raw_aweme_json"]


def test_identifies_novsight_tag_aweme_case_insensitively():
    assert is_novsight_tag_aweme(
        {"author": {"unique_id": "  NoVsIgHt  "}}
    )
    assert not is_novsight_tag_aweme(
        {"author": {"unique_id": "other-account"}}
    )


def test_enrich_tag_aweme_fills_missing_metrics_without_overwriting_values():
    target = DouyinTagTarget(
        "tag-1",
        "Tag",
        "https://www.douyin.com/hashtag/tag-1",
    )
    aweme = {
        "aweme_id": "aweme-1",
        "author": {
            "uid": "author-1",
            "sec_uid": "sec-1",
            "nickname": "List author",
            "follower_count": 0,
        },
        "statistics": {
            "play_count": 1234,
            "digg_count": 7,
        },
    }
    row = extract_douyin_tag_aweme(target, aweme, source_cursor=0)

    enriched = enrich_douyin_tag_aweme_row(
        row,
        creator_detail={
            "user": {
                "nickname": "Profile author",
                "follower_count": 456,
                "following_count": 23,
                "total_favorited": 7890,
            }
        },
    )

    assert enriched["play_count"] == 1234
    assert enriched["digg_count"] == 7
    assert enriched["author_follower_count"] == 456
    assert enriched["author_following_count"] == 23
    assert enriched["author_total_favorited"] == 7890
    assert enriched["author_nickname"] == "List author"
    assert '"follower_count":456' not in enriched["raw_aweme_json"]


def test_extract_tag_aweme_keeps_unavailable_public_play_count_blank():
    target = DouyinTagTarget(
        "tag-1",
        "Tag",
        "https://www.douyin.com/hashtag/tag-1",
    )
    row = extract_douyin_tag_aweme(
        target,
        {
            "aweme_id": "aweme-1",
            "author": {"uid": "author-1"},
            "statistics": {"play_count": 0},
        },
        source_cursor=0,
    )

    assert row["play_count"] is None


def test_excludes_configured_tag_author_id_from_all_known_id_fields():
    blocked = "1719260615816915"

    assert is_excluded_douyin_tag_author_id(blocked)
    assert is_excluded_douyin_tag_aweme(
        {"author": {"uid": blocked}}
    )
    assert is_excluded_douyin_tag_aweme(
        {"author_user_id": blocked, "author": {}}
    )
    assert not is_excluded_douyin_tag_aweme(
        {"author": {"uid": "other-author", "unique_id": "customer"}}
    )
