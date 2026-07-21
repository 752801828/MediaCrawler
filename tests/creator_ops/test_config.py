from pathlib import Path

import pytest

from creator_ops.config import SettingsError, load_settings


def valid_env(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "xhs_use_data_dir").mkdir()
    return {
        "BROWSER_DATA_ROOT": str(tmp_path),
        "RELATION_DB_HOST": "127.0.0.1",
        "RELATION_DB_PORT": "3306",
        "RELATION_DB_USER": "root",
        "RELATION_DB_PWD": "database-secret",
        "RELATION_DB_NAME": "media_crawler",
        "FEISHU_APP_ID": "cli_xxx",
        "FEISHU_APP_SECRET": "feishu-secret",
        "FEISHU_APP_TOKEN": "app-token",
        "FEISHU_LINK_TABLE_ID": "tbl_link",
        "FEISHU_LINK_VIEW_ID": "vew_link",
        "FEISHU_USER_TABLE_ID": "tbl_user",
        "FEISHU_USER_VIEW_ID": "vew_user",
        "FEISHU_ACCOUNT_TABLE_ID": "tbl_account",
        "FEISHU_ACCOUNT_VIEW_ID": "vew_account",
        "FEISHU_XHS_STATS_TABLE_ID": "tbl_xhs_stats",
        "FEISHU_DOUYIN_STATS_TABLE_ID": "tbl_dy_stats",
        "FEISHU_COMMENT_TABLE_ID": "tbl_comments",
        "FEISHU_COMMENT_VIEW_ID": "vew_comments",
        "FEISHU_DOUYIN_CREATOR_TABLE_ID": "tbl_dy_creator",
        "FEISHU_XHS_CREATOR_TABLE_ID": "tbl_xhs_creator",
        "FEISHU_HISTORY_VIEW_ID": "vew_history",
    }


def test_load_settings_defaults_to_mysql_and_expands_profile(tmp_path: Path):
    settings = load_settings(valid_env(tmp_path))

    assert settings.database_type == "mysql"
    assert settings.profile_path("%s_use_data_dir", "xhs") == (
        tmp_path / "xhs_use_data_dir"
    ).resolve()


def test_load_settings_reports_missing_name_without_secret_value(tmp_path: Path):
    env = valid_env(tmp_path)
    del env["FEISHU_APP_SECRET"]

    with pytest.raises(SettingsError) as exc_info:
        load_settings(env)

    message = str(exc_info.value)
    assert "FEISHU_APP_SECRET" in message
    assert "feishu-secret" not in message


def test_redacted_summary_hides_credentials(tmp_path: Path):
    settings = load_settings(valid_env(tmp_path))

    summary = settings.redacted_summary()

    assert "database-secret" not in summary
    assert "feishu-secret" not in summary
    assert "app-token" not in summary
    assert "media_crawler" in summary


def test_profile_path_rejects_escape_from_browser_root(tmp_path: Path):
    settings = load_settings(valid_env(tmp_path))

    with pytest.raises(SettingsError, match="escapes BROWSER_DATA_ROOT"):
        settings.profile_path("../outside_%s", "xhs")
