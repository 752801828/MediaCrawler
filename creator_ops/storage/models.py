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
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    synced_at = Column(DateTime)
