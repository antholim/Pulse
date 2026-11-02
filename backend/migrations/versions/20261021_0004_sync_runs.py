"""Record sync runs: run mode and error, watermarks per workspace, every raw record kind.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTITY_KINDS = "'organization', 'person', 'project', 'event', 'content'"
RAW_ENTITY_KINDS = (
    f"{ENTITY_KINDS}, 'workspace', 'category', 'organization_metadata', 'person_metadata', "
    "'project_metadata', 'event_metadata', 'event_session', 'content_blocks'"
)


def upgrade() -> None:
    op.add_column(
        "source",
        sa.Column(
            "workspace_watermarks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "sync_run", sa.Column("mode", sa.Text(), server_default="incremental", nullable=False)
    )
    op.add_column("sync_run", sa.Column("error", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_sync_run_mode"), "sync_run", "mode IN ('incremental', 'full')"
    )

    op.add_column("raw_record", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("raw_record", sa.Column("parent_external_id", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_raw_record_entity_kind"), "raw_record", type_="check")
    op.create_check_constraint(
        op.f("ck_raw_record_entity_kind"), "raw_record", f"entity_kind IN ({RAW_ENTITY_KINDS})"
    )
    op.create_index(
        "ix_raw_record_external_id",
        "raw_record",
        ["tenant_id", "entity_kind", "external_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_raw_record_external_id", table_name="raw_record")
    # Rows of the added kinds cannot satisfy the narrower constraint.
    op.execute(f"DELETE FROM raw_record WHERE entity_kind NOT IN ({ENTITY_KINDS})")
    op.drop_constraint(op.f("ck_raw_record_entity_kind"), "raw_record", type_="check")
    op.create_check_constraint(
        op.f("ck_raw_record_entity_kind"), "raw_record", f"entity_kind IN ({ENTITY_KINDS})"
    )
    op.drop_column("raw_record", "parent_external_id")
    op.drop_column("raw_record", "updated_at")

    op.drop_constraint(op.f("ck_sync_run_mode"), "sync_run", type_="check")
    op.drop_column("sync_run", "error")
    op.drop_column("sync_run", "mode")
    op.drop_column("source", "workspace_watermarks")
