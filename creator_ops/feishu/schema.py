from __future__ import annotations

ACCOUNT_FIELDS = {
    "id": "ID",
    "platform": "平台",
    "main": "主账号",
    "water": "水号",
}

LINK_FIELDS = {
    "platform": "平台",
    "enabled": "是否查询",
    "xhs_target": "链接",
    "douyin_target": "ID",
    "get_comments": "是否查询评论",
}

USER_FIELDS = {
    "platform": "平台",
    "enabled": "是否查询",
    "target": "ID",
}

PLATFORM_LABELS = {
    "小红书": "xhs",
    "抖音": "dy",
}

XHS_STATS_FIELDS = (
    "标题",
    "创建时间",
    "曝光",
    "浏览",
    "封面点击率",
    "点赞",
    "评论",
    "收藏",
    "涨粉",
    "分享",
    "人均观看时长",
    "弹幕",
)

DOUYIN_STATS_FIELDS = (
    "标题",
    "创建时间",
    "浏览",
    "完播率",
    "5S完播率",
    "封面点击率",
    "2S跳出率",
    "人均观看时长",
    "点赞",
    "分享",
    "评论",
    "收藏",
    "主页访问量",
    "涨粉",
)
