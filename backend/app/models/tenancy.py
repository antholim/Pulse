import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, json_column, one_of, same_tenant_fk, tenant_id_column, uuid_pk

SOURCE_KINDS = ("omerlo", "csv", "mock")
SYNC_RUN_STATUSES = ("running", "succeeded", "failed")


class Tenant(Base):
    """One Omerlo client. The Law 25 boundary: no data crosses tenants."""

    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text)
    omerlo_media_id: Mapped[str | None] = mapped_column(Text, unique=True)


class Source(Base):
    """A connected data source of one tenant."""

    __tablename__ = "source"
    __table_args__ = (
        # Target of same-tenant foreign keys; its leading tenant_id also indexes the tenant FK.
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(one_of("kind", SOURCE_KINDS), name="kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    kind: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = json_column()
    watermark_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncRun(Base):
    """One connector execution: the snapshot that change detection compares."""

    __tablename__ = "sync_run"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        same_tenant_fk("source_id", "source"),
        CheckConstraint(one_of("status", SYNC_RUN_STATUSES), name="status"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_start"
        ),
        # A source's runs in order: finds the previous run to diff against (#60) and
        # indexes the source foreign key.
        Index("ix_sync_run_source_started", "tenant_id", "source_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    source_id: Mapped[uuid.UUID]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="running")
    counts: Mapped[dict] = json_column()
