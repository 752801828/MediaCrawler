from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT

from database.models import Base


class CreatorOpsRun(Base):
    __tablename__ = "creator_ops_run"

    id = Column(Integer, primary_key=True)
    run_uuid = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False, default="running", index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)
    total_tasks = Column(Integer, nullable=False, default=0)
    succeeded_tasks = Column(Integer, nullable=False, default=0)
    failed_tasks = Column(Integer, nullable=False, default=0)


class CreatorOpsTask(Base):
    __tablename__ = "creator_ops_task"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=False, index=True)
    task_key = Column(String(255), nullable=False, index=True)
    platform = Column(String(16), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
    profile_key = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="running", index=True)
    attempts = Column(Integer, nullable=False, default=1)
    error_message = Column(Text, nullable=False, default="")
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)


class CreatorAccountMetricSnapshot(Base):
    __tablename__ = "creator_account_metric_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "profile_key",
            "snapshot_date",
            name="uq_creator_account_metric_daily",
        ),
    )

    id = Column(Integer, primary_key=True)
    platform = Column(String(16), nullable=False, index=True)
    profile_key = Column(String(255), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    metrics_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class CreatorContentMetricSnapshot(Base):
    __tablename__ = "creator_content_metric_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "profile_key",
            "content_key",
            "snapshot_date",
            name="uq_creator_content_metric_daily",
        ),
    )

    id = Column(Integer, primary_key=True)
    platform = Column(String(16), nullable=False, index=True)
    profile_key = Column(String(255), nullable=False, index=True)
    content_key = Column(String(128), nullable=False, index=True)
    title = Column(Text, nullable=False, default="")
    content_url = Column(Text, nullable=False, default="")
    published_at = Column(DateTime)
    snapshot_date = Column(Date, nullable=False, index=True)
    metrics_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class CreatorPublicContentSnapshot(Base):
    __tablename__ = "creator_public_content_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "content_key",
            "snapshot_date",
            name="uq_creator_public_content_daily",
        ),
    )

    id = Column(Integer, primary_key=True)
    platform = Column(String(16), nullable=False, index=True)
    content_key = Column(String(128), nullable=False, index=True)
    creator_hash = Column(String(64), nullable=False, default="", index=True)
    masked_nickname = Column(Text, nullable=False, default="")
    snapshot_date = Column(Date, nullable=False, index=True)
    metrics_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class CreatorOpsSyncOutbox(Base):
    __tablename__ = "creator_ops_sync_outbox"
    __table_args__ = (
        UniqueConstraint(
            "target_table",
            "business_key",
            name="uq_creator_ops_sync_business_key",
        ),
    )

    id = Column(Integer, primary_key=True)
    target_table = Column(String(128), nullable=False, index=True)
    business_key = Column(String(512), nullable=False)
    payload_json = Column(Text, nullable=False)
    remote_record_id = Column(String(128), nullable=False, default="")
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    synced_at = Column(DateTime)


class DouyinTagAweme(Base):
    __tablename__ = "douyin_tag_aweme"
    __table_args__ = (
        UniqueConstraint(
            "tag_id",
            "aweme_id",
            "author_id",
            name="uq_douyin_tag_aweme_identity",
        ),
    )

    id = Column(Integer, primary_key=True)
    tag_id = Column(String(64), nullable=False, index=True)
    tag_name = Column(Text, nullable=False, default="")
    tag_url = Column(Text, nullable=False, default="")
    aweme_id = Column(String(64), nullable=False, index=True)
    author_id = Column(String(255), nullable=False, index=True)
    sec_uid = Column(String(255), nullable=False, default="", index=True)
    source_cursor = Column(BigInteger, nullable=False, default=0)

    title = Column(Text, nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    aweme_type = Column(Integer)
    media_type = Column(Integer)
    published_at = Column(DateTime, index=True)
    region = Column(String(64), nullable=False, default="")
    share_url = Column(Text, nullable=False, default="")

    duration_ms = Column(BigInteger)
    width = Column(Integer)
    height = Column(Integer)
    cover_url = Column(Text, nullable=False, default="")
    play_url = Column(Text, nullable=False, default="")

    author_nickname = Column(Text, nullable=False, default="")
    author_unique_id = Column(String(255), nullable=False, default="", index=True)
    author_account_region = Column(String(64), nullable=False, default="")
    author_custom_verify = Column(Text, nullable=False, default="")
    author_enterprise_verify_reason = Column(Text, nullable=False, default="")
    author_follower_count = Column(BigInteger)
    author_following_count = Column(BigInteger)
    author_total_favorited = Column(BigInteger)

    play_count = Column(BigInteger)
    digg_count = Column(BigInteger)
    comment_count = Column(BigInteger)
    share_count = Column(BigInteger)
    collect_count = Column(BigInteger)
    exposure_count = Column(BigInteger)
    recommend_count = Column(BigInteger)

    text_extra_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    video_tag_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    raw_aweme_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    fetched_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
