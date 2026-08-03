import pytest

import config


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("xhs", True),
        ("dy", True),
        ("ks", False),
        ("bili", False),
        ("wb", False),
        ("tieba", False),
        ("zhihu", False),
    ],
)
def test_sub_comments_are_enabled_only_for_allowed_platforms(
    monkeypatch, platform, expected
):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)

    assert config.is_get_sub_comments_enabled(platform) is expected


@pytest.mark.parametrize("platform", ["xhs", "dy"])
def test_sub_comments_require_first_level_comments(monkeypatch, platform):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", True)

    assert config.is_get_sub_comments_enabled(platform) is False


def test_sub_comments_respect_global_switch(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", False)

    assert config.is_get_sub_comments_enabled("dy") is False
