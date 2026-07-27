from creator_ops.douyin_comment_threads import (
    DOUYIN_COMMENT_FIELD_MAP,
    build_douyin_comment_payloads,
)


def test_builds_root_and_child_payloads_with_reply_references():
    comments = [
        {
            "id": "1",
            "comment_id": "root-1",
            "parent_comment_id": "0",
            "aweme_id": "video-1",
            "user_id": "user-1",
            "nickname": "客户\n甲",
            "content": "第一行\n第二行",
            "create_time": 100,
            "like_count": "3",
        },
        {
            "id": "2",
            "comment_id": "child-before",
            "parent_comment_id": "root-1",
            "nickname": "用户B",
            "content": "先回复",
            "create_time": 200,
            "user_unique_id": "other",
        },
        {
            "id": "3",
            "comment_id": "child-brand",
            "parent_comment_id": "root-1",
            "nickname": "NOVSIGHT户外越野",
            "content": "品牌\n回复",
            "create_time": 300,
            "user_unique_id": "  NoVsIgHt  ",
        },
        {
            "id": "4",
            "comment_id": "child-after",
            "parent_comment_id": "root-1",
            "nickname": "用户C",
            "content": "后续回复",
            "create_time": 400,
            "user_unique_id": "other-2",
        },
        {
            "id": "5",
            "comment_id": "root-2",
            "parent_comment_id": "",
            "aweme_id": "video-2",
            "nickname": "未回复用户",
            "content": "还没回复",
            "create_time": 500,
        },
        {
            "id": "6",
            "comment_id": "orphan-child",
            "parent_comment_id": "missing-root",
            "nickname": "孤立回复",
            "content": "仍然上传",
            "create_time": 600,
        },
    ]

    payloads = dict(build_douyin_comment_payloads(comments))

    assert set(payloads) == {
        "root-1",
        "child-before",
        "child-brand",
        "child-after",
        "root-2",
        "orphan-child",
    }
    replied = payloads["root-1"]
    assert replied["是否回复"] == "是"
    assert replied["回复内容ID"] == ""
    assert replied["用户ID"] == "user-1"
    assert replied["评论ID"] == "root-1"
    assert replied["视频ID"] == "video-1"
    assert replied["评论内容"] == "第一行\n第二行"
    expected_fields = set(DOUYIN_COMMENT_FIELD_MAP.values()) | {
        "评论时间",
        "是否回复",
        "回复内容ID",
    }
    assert set(replied) == expected_fields
    assert payloads["root-2"]["是否回复"] == "否"
    assert payloads["root-2"]["回复内容ID"] == ""
    assert payloads["child-before"]["是否回复"] == "否"
    assert payloads["child-before"]["回复内容ID"] == "root-1"
    assert payloads["child-brand"]["是否回复"] == "是"
    assert payloads["child-brand"]["回复内容ID"] == "root-1"
    assert payloads["child-after"]["是否回复"] == "否"
    assert payloads["orphan-child"]["是否回复"] == "否"
    assert payloads["orphan-child"]["回复内容ID"] == "missing-root"
