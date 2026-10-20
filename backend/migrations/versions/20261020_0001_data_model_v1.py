"""Data model v1 (#25): tenant-scoped sources, sync runs, records, organizations,
matches and changes.

Every table except tenant has a non-null tenant_id, and every reference between
tables goes through (tenant_id, id) so it cannot cross tenants (D5).

Revision ID: 0001
Revises:
Create Date: 2026-10-20 00:26:38.703067
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("omerlo_media_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant")),
        sa.UniqueConstraint("omerlo_media_id", name=op.f("uq_tenant_omerlo_media_id")),
    )
    op.create_table(
        "organization",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("primary_domain", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_organization_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_organization_tenant_id_id")),
    )
    op.create_table(
        "source",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("watermark_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('omerlo', 'csv', 'mock')", name=op.f("ck_source_kind")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_source_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_source_tenant_id_id")),
    )
    op.create_table(
        "sync_run",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name=op.f("ck_sync_run_status")
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_sync_run_finished_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["source.tenant_id", "source.id"],
            name=op.f("fk_sync_run_tenant_id_source_id_source"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_sync_run_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_run")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sync_run_tenant_id_id")),
    )
    op.create_index(
        "ix_sync_run_source_started",
        "sync_run",
        ["tenant_id", "source_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "raw_record",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("sync_run_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("entity_kind", sa.Text(), nullable=False),
        sa.Column("payload_uri", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "entity_kind IN ('organization', 'person', 'project', 'event', 'content')",
            name=op.f("ck_raw_record_entity_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sync_run_id"],
            ["sync_run.tenant_id", "sync_run.id"],
            name=op.f("fk_raw_record_tenant_id_sync_run_id_sync_run"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_raw_record_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_record")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_raw_record_tenant_id_id")),
    )
    op.create_index(
        "ix_raw_record_sync_run", "raw_record", ["tenant_id", "sync_run_id"], unique=False
    )
    op.create_table(
        "source_record",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name_normalized", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("linkedin", sa.Text(), nullable=True),
        sa.Column(
            "external_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_run", sa.UUID(), nullable=False),
        sa.Column("last_seen_run", sa.UUID(), nullable=False),
        sa.Column("raw_record_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('organization', 'person', 'project', 'event', 'content')",
            name=op.f("ck_source_record_kind"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name=op.f("ck_source_record_valid_range")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "first_seen_run"],
            ["sync_run.tenant_id", "sync_run.id"],
            name=op.f("fk_source_record_tenant_id_first_seen_run_sync_run"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "last_seen_run"],
            ["sync_run.tenant_id", "sync_run.id"],
            name=op.f("fk_source_record_tenant_id_last_seen_run_sync_run"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "raw_record_id"],
            ["raw_record.tenant_id", "raw_record.id"],
            name=op.f("fk_source_record_tenant_id_raw_record_id_raw_record"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["source.tenant_id", "source.id"],
            name=op.f("fk_source_record_tenant_id_source_id_source"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_source_record_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_record")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_source_record_tenant_id_id")),
    )
    op.create_index(
        "ix_source_record_domain",
        "source_record",
        ["tenant_id", "domain"],
        unique=False,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_source_record_first_seen_run",
        "source_record",
        ["tenant_id", "first_seen_run"],
        unique=False,
    )
    op.create_index(
        "ix_source_record_last_seen_run",
        "source_record",
        ["tenant_id", "last_seen_run"],
        unique=False,
    )
    op.create_index(
        "ix_source_record_linkedin",
        "source_record",
        ["tenant_id", "linkedin"],
        unique=False,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_source_record_name",
        "source_record",
        ["tenant_id", "name_normalized"],
        unique=False,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_source_record_raw_record", "source_record", ["tenant_id", "raw_record_id"], unique=False
    )
    op.create_index(
        "ix_source_record_versions",
        "source_record",
        ["tenant_id", "source_id", "external_id", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ux_source_record_current",
        "source_record",
        ["tenant_id", "source_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_table(
        "match_candidate",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("left_record_id", sa.UUID(), nullable=False),
        sa.Column("right_record_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column(
            "matched_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name=op.f("ck_match_candidate_status")
        ),
        sa.CheckConstraint(
            "left_record_id < right_record_id", name=op.f("ck_match_candidate_ordered_pair")
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 1", name=op.f("ck_match_candidate_score_range")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "left_record_id"],
            ["source_record.tenant_id", "source_record.id"],
            name=op.f("fk_match_candidate_tenant_id_left_record_id_source_record"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "right_record_id"],
            ["source_record.tenant_id", "source_record.id"],
            name=op.f("fk_match_candidate_tenant_id_right_record_id_source_record"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_match_candidate_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_candidate")),
        sa.UniqueConstraint(
            "tenant_id",
            "left_record_id",
            "right_record_id",
            name=op.f("uq_match_candidate_tenant_id_left_record_id_right_record_id"),
        ),
    )
    op.create_index(
        "ix_match_candidate_right_record",
        "match_candidate",
        ["tenant_id", "right_record_id"],
        unique=False,
    )
    op.create_table(
        "org_link",
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method IN ('domain', 'linkedin', 'external_id', 'name_city', 'manual')",
            name=op.f("ck_org_link_method"),
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_org_link_confidence_range")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id"],
            ["organization.tenant_id", "organization.id"],
            name=op.f("fk_org_link_tenant_id_organization_id_organization"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_record_id"],
            ["source_record.tenant_id", "source_record.id"],
            name=op.f("fk_org_link_tenant_id_source_record_id_source_record"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_org_link_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("source_record_id", name=op.f("pk_org_link")),
    )
    op.create_index(
        "ix_org_link_organization", "org_link", ["tenant_id", "organization_id"], unique=False
    )
    op.create_table(
        "record_change",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("sync_run_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column(
            "changed_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "change_type IN ('added', 'modified', 'removed')",
            name=op.f("ck_record_change_change_type"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_record_id"],
            ["source_record.tenant_id", "source_record.id"],
            name=op.f("fk_record_change_tenant_id_source_record_id_source_record"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sync_run_id"],
            ["sync_run.tenant_id", "sync_run.id"],
            name=op.f("fk_record_change_tenant_id_sync_run_id_sync_run"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_record_change_tenant_id_tenant")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_change")),
        sa.UniqueConstraint(
            "tenant_id",
            "sync_run_id",
            "source_record_id",
            name=op.f("uq_record_change_tenant_id_sync_run_id_source_record_id"),
        ),
    )
    op.create_index(
        "ix_record_change_source_record",
        "record_change",
        ["tenant_id", "source_record_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_record_change_source_record", table_name="record_change")
    op.drop_table("record_change")
    op.drop_index("ix_org_link_organization", table_name="org_link")
    op.drop_table("org_link")
    op.drop_index("ix_match_candidate_right_record", table_name="match_candidate")
    op.drop_table("match_candidate")
    op.drop_index(
        "ux_source_record_current",
        table_name="source_record",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_index("ix_source_record_versions", table_name="source_record")
    op.drop_index("ix_source_record_raw_record", table_name="source_record")
    op.drop_index(
        "ix_source_record_name",
        table_name="source_record",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_index(
        "ix_source_record_linkedin",
        table_name="source_record",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_index("ix_source_record_last_seen_run", table_name="source_record")
    op.drop_index("ix_source_record_first_seen_run", table_name="source_record")
    op.drop_index(
        "ix_source_record_domain",
        table_name="source_record",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_table("source_record")
    op.drop_index("ix_raw_record_sync_run", table_name="raw_record")
    op.drop_table("raw_record")
    op.drop_index("ix_sync_run_source_started", table_name="sync_run")
    op.drop_table("sync_run")
    op.drop_table("source")
    op.drop_table("organization")
    op.drop_table("tenant")
