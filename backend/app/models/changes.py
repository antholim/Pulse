import uuid

from sqlalchemy import CheckConstraint, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, json_column, one_of, same_tenant_fk, tenant_id_column, uuid_pk

CHANGE_TYPES = ("added", "modified", "removed")


class RecordChange(Base):
    """One added, modified or removed record between two sync runs (#60)."""

    __tablename__ = "record_change"
    __table_args__ = (
        # One change per record per run; also lists a run's changes and indexes the sync
        # run foreign key.
        UniqueConstraint("tenant_id", "sync_run_id", "source_record_id"),
        same_tenant_fk("sync_run_id", "sync_run"),
        same_tenant_fk("source_record_id", "source_record"),
        CheckConstraint(one_of("change_type", CHANGE_TYPES), name="change_type"),
        # A record's change history; indexes the source record foreign key.
        Index("ix_record_change_source_record", "tenant_id", "source_record_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    sync_run_id: Mapped[uuid.UUID]
    source_record_id: Mapped[uuid.UUID]
    change_type: Mapped[str] = mapped_column(Text)
    changed_fields: Mapped[dict] = json_column()
