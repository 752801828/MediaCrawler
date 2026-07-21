from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


class SettingsError(ValueError):
    """Raised when creator operations configuration is invalid."""


@dataclass(frozen=True)
class MysqlSettings:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class FeishuSettings:
    app_id: str
    app_secret: str
    app_token: str
    link_table_id: str
    link_view_id: str
    user_table_id: str
    user_view_id: str
    account_table_id: str
    account_view_id: str
    xhs_stats_table_id: str
    douyin_stats_table_id: str
    comment_table_id: str
    comment_view_id: str
    douyin_creator_table_id: str
    xhs_creator_table_id: str
    history_view_id: str
    douyin_comment_table_id: str = ""


@dataclass(frozen=True)
class Settings:
    browser_data_root: Path
    mysql: MysqlSettings
    feishu: FeishuSettings
    database_type: str = "mysql"

    def profile_path(self, template: str, platform: str) -> Path:
        if not template.strip():
            raise SettingsError("browser profile template is empty")
        name = template % platform if "%s" in template else template
        root = self.browser_data_root.resolve()
        candidate = (root / name).resolve()
        if candidate == root or root not in candidate.parents:
            raise SettingsError("browser profile escapes BROWSER_DATA_ROOT")
        return candidate

    def redacted_summary(self) -> str:
        return json.dumps(
            {
                "database_type": self.database_type,
                "database_host": self.mysql.host,
                "database_port": self.mysql.port,
                "database_name": self.mysql.database,
                "browser_data_root": str(self.browser_data_root),
                "feishu_app_id": _mask(self.feishu.app_id),
                "feishu_tables_configured": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


_REQUIRED_KEYS = (
    "RELATION_DB_HOST",
    "RELATION_DB_PORT",
    "RELATION_DB_USER",
    "RELATION_DB_PWD",
    "RELATION_DB_NAME",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_APP_TOKEN",
    "FEISHU_LINK_TABLE_ID",
    "FEISHU_LINK_VIEW_ID",
    "FEISHU_USER_TABLE_ID",
    "FEISHU_USER_VIEW_ID",
    "FEISHU_ACCOUNT_TABLE_ID",
    "FEISHU_ACCOUNT_VIEW_ID",
    "FEISHU_XHS_STATS_TABLE_ID",
    "FEISHU_DOUYIN_STATS_TABLE_ID",
    "FEISHU_COMMENT_TABLE_ID",
    "FEISHU_COMMENT_VIEW_ID",
    "FEISHU_DOUYIN_CREATOR_TABLE_ID",
    "FEISHU_XHS_CREATOR_TABLE_ID",
    "FEISHU_HISTORY_VIEW_ID",
)


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    if environ is None:
        load_dotenv()
        values: Mapping[str, str] = os.environ
    else:
        values = environ

    missing = [key for key in _REQUIRED_KEYS if not values.get(key, "").strip()]
    if missing:
        raise SettingsError("missing required settings: " + ", ".join(sorted(missing)))

    try:
        port = int(values["RELATION_DB_PORT"])
    except ValueError as exc:
        raise SettingsError("RELATION_DB_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SettingsError("RELATION_DB_PORT must be between 1 and 65535")

    root = Path(values.get("BROWSER_DATA_ROOT", r"D:\browser_data")).expanduser()
    if not root.is_dir():
        raise SettingsError(f"BROWSER_DATA_ROOT does not exist: {root}")

    return Settings(
        browser_data_root=root.resolve(),
        mysql=MysqlSettings(
            host=values["RELATION_DB_HOST"],
            port=port,
            user=values["RELATION_DB_USER"],
            password=values["RELATION_DB_PWD"],
            database=values["RELATION_DB_NAME"],
        ),
        feishu=FeishuSettings(
            app_id=values["FEISHU_APP_ID"],
            app_secret=values["FEISHU_APP_SECRET"],
            app_token=values["FEISHU_APP_TOKEN"],
            link_table_id=values["FEISHU_LINK_TABLE_ID"],
            link_view_id=values["FEISHU_LINK_VIEW_ID"],
            user_table_id=values["FEISHU_USER_TABLE_ID"],
            user_view_id=values["FEISHU_USER_VIEW_ID"],
            account_table_id=values["FEISHU_ACCOUNT_TABLE_ID"],
            account_view_id=values["FEISHU_ACCOUNT_VIEW_ID"],
            xhs_stats_table_id=values["FEISHU_XHS_STATS_TABLE_ID"],
            douyin_stats_table_id=values["FEISHU_DOUYIN_STATS_TABLE_ID"],
            comment_table_id=values["FEISHU_COMMENT_TABLE_ID"],
            comment_view_id=values["FEISHU_COMMENT_VIEW_ID"],
            douyin_creator_table_id=values["FEISHU_DOUYIN_CREATOR_TABLE_ID"],
            xhs_creator_table_id=values["FEISHU_XHS_CREATOR_TABLE_ID"],
            history_view_id=values["FEISHU_HISTORY_VIEW_ID"],
            douyin_comment_table_id=values.get("FEISHU_DOUYIN_COMMENT_TABLE_ID", ""),
        ),
    )


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}***{value[-2:]}"
