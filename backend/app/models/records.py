import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Text,
    UniqueConstraint,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, json_column, one_of, same_tenant_fk, tenant_id_column, uuid_pk

ENTITY_KINDS = ("organization", "person", "project", "event", "content")

CURRENT_VERSION = text("valid_to IS NULL")


class RawRecord(Base):
    """Pointer to one payload archived exactly as the source returned it (D4)."""

    __tablename__ = "raw_record"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        same_tenant_fk("sync_run_id", "sync_run"),
        CheckConstraint(one_of("entity_kind", ENTITY_KINDS), name="entity_kind"),
        # The payloads a run archived; indexes the sync run foreign key.
        Index("ix_raw_record_sync_run", "tenant_id", "sync_run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    sync_run_id: Mapped[uuid.UUID]
    external_id: Mapped[str] = mapped_column(Text)
    entity_kind: Mapped[str] = mapped_column(Text)
    payload_uri: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(Text)


class SourceRecord(Base):
    """What one source says about one entity, normalized for matching.

    Each row is one version. The logical record is (tenant_id, source_id, external_id),
    and the current version is the one whose valid_to is null.
    """

    __tablename__ = "source_record"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        same_tenant_fk("source_id", "source"),
        same_tenant_fk("first_seen_run", "sync_run"),
        same_tenant_fk("last_seen_run", "sync_run"),
        same_tenant_fk("raw_record_id", "raw_record"),
        CheckConstraint(one_of("kind", ENTITY_KINDS), name="kind"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        # At most one current version per record; also finds that version during a sync.
        Index(
            "ux_source_record_current",
            "tenant_id",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=CURRENT_VERSION,
        ),
        # Versions of one record never overlap in time, so the as-of query (#58) finds at
        # most one. The equality columns need the btree_gist extension.
        ExcludeConstraint(
            ("tenant_id", "="),
            ("source_id", "="),
            ("external_id", "="),
            (func.tstzrange(literal_column("valid_from"), literal_column("valid_to")), "&&"),
            name="ex_source_record_versions_overlap",
            using="gist",
        ),
        # Every version of a record in order, for the as-of query (#58); indexes the
        # source foreign key.
        Index("ix_source_record_versions", "tenant_id", "source_id", "external_id", "valid_from"),
        # Tier 1 matching (#61) looks up current versions by each identifier. Partial
        # indexes stay small because closed versions are never matched.
        Index(
            "ix_source_record_name",
            "tenant_id",
            "name_normalized",
            postgresql_where=CURRENT_VERSION,
        ),
        Index("ix_source_record_domain", "tenant_id", "domain", postgresql_where=CURRENT_VERSION),
        Index(
            "ix_source_record_linkedin",
            "tenant_id",
            "linkedin",
            postgresql_where=CURRENT_VERSION,
        ),
        # Records seen by a run: removal detection compares last_seen_run (#58, #60).
        # Both also index their sync run foreign keys.
        Index("ix_source_record_first_seen_run", "tenant_id", "first_seen_run"),
        Index("ix_source_record_last_seen_run", "tenant_id", "last_seen_run"),
        # Provenance from a payload to the versions built from it; indexes the foreign key.
        Index("ix_source_record_raw_record", "tenant_id", "raw_record_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    source_id: Mapped[uuid.UUID]
    external_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    name_normalized: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    linkedin: Mapped[str | None] = mapped_column(Text)
    external_ids: Mapped[dict] = json_column()
    attributes: Mapped[dict] = json_column()
    workspace_id: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_run: Mapped[uuid.UUID]
    last_seen_run: Mapped[uuid.UUID]
    raw_record_id: Mapped[uuid.UUID | None]
