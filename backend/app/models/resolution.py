import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Double, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, json_column, one_of, same_tenant_fk, tenant_id_column, uuid_pk

LINK_METHODS = ("domain", "linkedin", "external_id", "name_city", "manual")
CANDIDATE_STATUSES = ("pending", "accepted", "rejected")


class Organization(Base):
    """What PULSE believes is one real-world organization."""

    __tablename__ = "organization"
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    display_name: Mapped[str] = mapped_column(Text)
    primary_domain: Mapped[str | None] = mapped_column(Text)


class OrgLink(Base):
    """The decision that a source record version belongs to an organization (#61).

    The version is the primary key, so each version belongs to at most one organization.
    A new version starts unlinked: versioning (#58) must copy the link to it in the same
    transaction that closes the old version. Current membership of an organization joins
    source_record on valid_to IS NULL.
    """

    __tablename__ = "org_link"
    __table_args__ = (
        same_tenant_fk("organization_id", "organization"),
        same_tenant_fk("source_record_id", "source_record"),
        CheckConstraint(one_of("method", LINK_METHODS), name="method"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        # An organization's source records (#27); indexes the organization foreign key.
        Index("ix_org_link_organization", "tenant_id", "organization_id"),
    )

    source_record_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID]
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Double)
    decided_by: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchCandidate(Base):
    """A possible match between two source records, set aside instead of merged (#61).

    left_record_id < right_record_id, so each pair is stored once whatever the order.
    Like OrgLink, a candidate points at versions: versioning (#58) must copy a record's
    candidates, with their status, to its new version, or an accepted or rejected pair
    comes back as pending.
    """

    __tablename__ = "match_candidate"
    __table_args__ = (
        # One row per pair of versions, so re-matching the same versions is idempotent;
        # indexes the left side.
        UniqueConstraint("tenant_id", "left_record_id", "right_record_id"),
        same_tenant_fk("left_record_id", "source_record"),
        same_tenant_fk("right_record_id", "source_record"),
        CheckConstraint("left_record_id < right_record_id", name="ordered_pair"),
        CheckConstraint("score BETWEEN 0 AND 1", name="score_range"),
        CheckConstraint(one_of("status", CANDIDATE_STATUSES), name="status"),
        # Candidates involving a record from the right side; indexes that foreign key.
        Index("ix_match_candidate_right_record", "tenant_id", "right_record_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_id_column()
    left_record_id: Mapped[uuid.UUID]
    right_record_id: Mapped[uuid.UUID]
    score: Mapped[float] = mapped_column(Double)
    matched_fields: Mapped[list] = json_column("[]")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
