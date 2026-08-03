from __future__ import annotations

import asyncio

from database import models
from media_platform.tieba.help import TieBaExtractor
from media_platform.zhihu.help import ZhihuExtractor
from model.m_zhihu import ZhihuContent
from store import bilibili as bili_store
from store import douyin as douyin_store
from store import kuaishou as kuaishou_store
from store import weibo as weibo_store
from store import xhs as xhs_store


class CaptureStore:
    def __init__(self):
        self.content = {}
        self.comment = {}
        self.creator = {}
        self.contact = {}
        self.dynamic = {}

    async def store_content(self, content_item):
        self.content = dict(content_item)

    async def store_comment(self, comment_item):
        self.comment = dict(comment_item)

    async def store_creator(self, creator=None, creator_item=None):
        self.creator = dict(creator or creator_item or {})

    async def store_contact(self, contact_item):
        self.contact = dict(contact_item)

    async def store_dynamic(self, dynamic_item):
        self.dynamic = dict(dynamic_item)


def _use_capture(monkeypatch, factory, capture):
    monkeypatch.setattr(
        factory,
        "create_store",
        staticmethod(lambda: capture),
    )


def test_douyin_content_comment_and_creator_keep_original_user_fields(monkeypatch):
    capture = CaptureStore()
    _use_capture(monkeypatch, douyin_store.DouyinStoreFactory, capture)
    user = {
        "uid": "dy-user-1",
        "sec_uid": "dy-sec-1",
        "short_id": "123",
        "unique_id": "visible-id",
        "nickname": "完整抖音昵称",
        "signature": "完整签名",
        "gender": 1,
        "avatar_thumb": {"url_list": ["https://img/avatar.jpg"]},
        "following_count": 7,
        "follower_count": 8,
        "total_favorited": 9,
        "aweme_count": 10,
        "ip_location": "广东",
    }
    aweme = {
        "aweme_id": "aweme-1",
        "aweme_type": 0,
        "desc": "video",
        "create_time": 1,
        "author": user,
        "statistics": {},
        "ip_label": "广东",
    }
    asyncio.run(douyin_store.update_douyin_aweme(aweme))
    assert capture.content["user_id"] == "dy-user-1"
    assert capture.content["sec_uid"] == "dy-sec-1"
    assert capture.content["nickname"] == "完整抖音昵称"
    assert capture.content["avatar"] == "https://img/avatar.jpg"
    assert capture.content["user_signature"] == "完整签名"
    assert capture.content["ip_location"] == "广东"

    comment = {
        "cid": "comment-1",
        "aweme_id": "aweme-1",
        "text": "comment",
        "create_time": 2,
        "ip_label": "上海",
        "user": user,
    }
    asyncio.run(douyin_store.update_dy_aweme_comment("aweme-1", comment))
    assert capture.comment["user_id"] == "dy-user-1"
    assert capture.comment["nickname"] == "完整抖音昵称"
    assert capture.comment["ip_location"] == "上海"
    assert capture.comment["parent_comment_id"] == ""

    asyncio.run(douyin_store.save_creator("dy-user-1", {"user": user}))
    assert capture.creator["user_id"] == "dy-user-1"
    assert capture.creator["nickname"] == "完整抖音昵称"
    assert capture.creator["desc"] == "完整签名"


def test_douyin_comment_api_mapping_handles_parent_and_single_image():
    root = douyin_store.map_douyin_aweme_comment(
        "aweme-1",
        {
            "cid": "root-1",
            "reply_id": "0",
            "reply_comment_count": 2,
            "digg_count": 3,
            "image_list": [
                {
                    "origin_url": {
                        "url_list": ["https://img/root-only.jpg"],
                    }
                }
            ],
            "user": {
                "uid": "user-1",
                "nickname": "未脱敏昵称",
            },
        },
    )
    assert root["aweme_id"] == "aweme-1"
    assert root["parent_comment_id"] == ""
    assert root["sub_comment_count"] == "2"
    assert root["pictures"] == "https://img/root-only.jpg"
    assert root["nickname"] == "未脱敏昵称"

    reply = douyin_store.map_douyin_aweme_comment(
        "aweme-1",
        {
            "cid": "reply-1",
            "aweme_id": "aweme-1",
            "reply_id": "another-reply",
            "_parent_comment_id": "root-1",
            "user": None,
        },
    )
    assert reply["parent_comment_id"] == "root-1"
    assert reply["user_id"] is None
    assert reply["pictures"] == ""


def test_xhs_content_comment_and_creator_keep_original_user_fields(monkeypatch):
    capture = CaptureStore()
    _use_capture(monkeypatch, xhs_store.XhsStoreFactory, capture)
    note = {
        "note_id": "note-1",
        "type": "normal",
        "title": "note",
        "desc": "desc",
        "time": 1,
        "user": {
            "user_id": "xhs-user-1",
            "nickname": "完整小红书昵称",
            "avatar": "https://img/xhs.jpg",
        },
        "interact_info": {},
        "ip_location": "北京",
        "image_list": [],
        "tag_list": [],
    }
    asyncio.run(xhs_store.update_xhs_note(note))
    assert capture.content["user_id"] == "xhs-user-1"
    assert capture.content["nickname"] == "完整小红书昵称"
    assert capture.content["avatar"] == "https://img/xhs.jpg"
    assert capture.content["ip_location"] == "北京"

    comment = {
        "id": "xhs-comment-1",
        "content": "comment",
        "create_time": 2,
        "ip_location": "浙江",
        "user_info": {
            "user_id": "xhs-commenter",
            "nickname": "评论者原名",
            "image": "https://img/commenter.jpg",
        },
    }
    asyncio.run(xhs_store.update_xhs_note_comment("note-1", comment))
    assert capture.comment["user_id"] == "xhs-commenter"
    assert capture.comment["nickname"] == "评论者原名"
    assert capture.comment["ip_location"] == "浙江"

    creator = {
        "basicInfo": {
            "nickname": "创作者原名",
            "gender": 1,
            "images": "https://img/creator.jpg",
            "desc": "创作者简介",
            "ipLocation": "四川",
        },
        "interactions": [
            {"type": "follows", "count": 1},
            {"type": "fans", "count": 2},
            {"type": "interaction", "count": 3},
        ],
        "tags": [{"tagType": "profession", "name": "摄影"}],
    }
    asyncio.run(xhs_store.save_creator("xhs-user-1", creator))
    assert capture.creator["nickname"] == "创作者原名"
    assert capture.creator["ip_location"] == "四川"
    assert capture.creator["fans"] == "2"


def test_kuaishou_and_weibo_keep_original_user_fields(monkeypatch):
    ks_capture = CaptureStore()
    _use_capture(monkeypatch, kuaishou_store.KuaishouStoreFactory, ks_capture)
    asyncio.run(
        kuaishou_store.update_ks_video_comment(
            "video-1",
            {
                "comment_id": 99,
                "author_id": "ks-user",
                "author_name": "快手原名",
                "headurl": "https://img/ks.jpg",
                "content": "comment",
                "timestamp": 1,
            },
        )
    )
    assert ks_capture.comment["user_id"] == "ks-user"
    assert ks_capture.comment["nickname"] == "快手原名"
    assert ks_capture.comment["avatar"] == "https://img/ks.jpg"

    wb_capture = CaptureStore()
    _use_capture(monkeypatch, weibo_store.WeibostoreFactory, wb_capture)
    asyncio.run(
        weibo_store.update_weibo_note_comment(
            "weibo-1",
            {
                "id": "wb-comment",
                "created_at": "Mon Jan 01 00:00:00 +0800 2024",
                "text": "comment",
                "source": "来自广东",
                "user": {
                    "id": 123,
                    "screen_name": "微博原名",
                    "gender": "f",
                    "profile_url": "/u/123",
                    "profile_image_url": "https://img/wb.jpg",
                },
            },
        )
    )
    assert wb_capture.comment["user_id"] == "123"
    assert wb_capture.comment["nickname"] == "微博原名"
    assert wb_capture.comment["avatar"] == "https://img/wb.jpg"
    assert wb_capture.comment["ip_location"] == "广东"


def test_bilibili_keeps_original_user_and_contact_fields(monkeypatch):
    capture = CaptureStore()
    _use_capture(monkeypatch, bili_store.BiliStoreFactory, capture)
    asyncio.run(
        bili_store.update_bilibili_video_comment(
            "video-1",
            {
                "rpid": 1,
                "parent": 0,
                "ctime": 1,
                "content": {"message": "comment"},
                "member": {
                    "mid": "bili-user",
                    "uname": "B站原名",
                    "sex": "男",
                    "sign": "签名",
                    "avatar": "https://img/bili.jpg",
                },
            },
        )
    )
    assert capture.comment["user_id"] == "bili-user"
    assert capture.comment["nickname"] == "B站原名"
    assert capture.comment["sign"] == "签名"

    asyncio.run(
        bili_store.update_bilibili_creator_contact(
            {"id": "up", "name": "UP原名", "sign": "up-sign", "avatar": "up.jpg"},
            {"id": "fan", "name": "粉丝原名", "sign": "fan-sign", "avatar": "fan.jpg"},
        )
    )
    assert capture.contact["up_id"] == "up"
    assert capture.contact["fan_name"] == "粉丝原名"


def test_tieba_and_zhihu_extractors_keep_original_user_fields():
    tieba_note = TieBaExtractor().extract_note_detail_from_api(
        {
            "thread": {"id": "100", "title": "title"},
            "first_floor": {"author_id": 7, "content": "body", "time": 1},
            "forum": {"id": 3, "name": "测试"},
            "page": {"total_page": 1},
            "user_list": [
                {
                    "id": 7,
                    "portrait": "portrait-7",
                    "name_show": "贴吧原名",
                }
            ],
        }
    )
    assert tieba_note.user_nickname == "贴吧原名"
    assert "portrait-7" in tieba_note.user_link
    assert "portrait-7" in tieba_note.user_avatar

    zhihu_content = ZhihuContent(content_id="content-1", content_type="answer")
    zhihu_comment = ZhihuExtractor()._extract_comment(
        zhihu_content,
        {
            "id": "comment-1",
            "type": "comment",
            "content": "comment",
            "created_time": 1,
            "comment_tag": [{"type": "ip_info", "text": "江苏"}],
            "author": {
                "id": "zh-user",
                "name": "知乎原名",
                "url_token": "zh-token",
                "avatar_url": "https://img/zh.jpg",
            },
        },
    )
    assert zhihu_comment.user_id == "zh-user"
    assert zhihu_comment.user_nickname == "知乎原名"
    assert zhihu_comment.user_link.endswith("/people/zh-token")
    assert zhihu_comment.ip_location == "江苏"


def test_full_user_columns_and_creator_models_are_present():
    expected_columns = {
        models.DouyinAwemeComment: {
            "user_id",
            "sec_uid",
            "short_user_id",
            "user_unique_id",
            "nickname",
            "avatar",
            "user_signature",
            "ip_location",
        },
        models.XhsNoteComment: {
            "user_id",
            "nickname",
            "avatar",
            "ip_location",
        },
        models.KuaishouVideoComment: {"user_id", "nickname", "avatar"},
        models.WeiboNoteComment: {
            "user_id",
            "nickname",
            "avatar",
            "gender",
            "profile_url",
            "ip_location",
        },
        models.TiebaComment: {
            "user_link",
            "user_nickname",
            "user_avatar",
            "ip_location",
        },
        models.ZhihuComment: {
            "user_id",
            "user_link",
            "user_nickname",
            "user_avatar",
            "ip_location",
        },
        models.BilibiliVideoComment: {
            "user_id",
            "nickname",
            "sex",
            "sign",
            "avatar",
        },
    }
    for model, expected in expected_columns.items():
        assert expected.issubset(
            {column.name for column in model.__table__.columns}
        )

    assert {
        models.DyCreator.__tablename__,
        models.XhsCreator.__tablename__,
        models.KuaishouCreator.__tablename__,
        models.WeiboCreator.__tablename__,
        models.TiebaCreator.__tablename__,
        models.ZhihuCreator.__tablename__,
        models.BilibiliUpInfo.__tablename__,
        models.BilibiliContactInfo.__tablename__,
    } == {
        "dy_creator",
        "xhs_creator",
        "kuaishou_creator",
        "weibo_creator",
        "tieba_creator",
        "zhihu_creator",
        "bilibili_up_info",
        "bilibili_contact_info",
    }
