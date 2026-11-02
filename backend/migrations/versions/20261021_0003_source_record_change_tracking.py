"""Track content changes and removals of source record versions.

content_hash lets a sync compare a record with its current version without reading
its JSON. removed_run marks a version closed because a full sync no longer found it.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_record",
        sa.Column("content_hash", sa.Text(), server_default="", nullable=False),
    )
    op.add_column("source_record", sa.Column("removed_run", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_source_record_tenant_id_removed_run_sync_run"),
        "source_record",
        "sync_run",
        ["tenant_id", "removed_run"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_source_record_removed_is_closed"),
        "source_record",
        "removed_run IS NULL OR valid_to IS NOT NULL",
    )
    op.create_index(
        "ix_source_record_removed_run",
        "source_record",
        ["tenant_id", "removed_run"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_source_record_removed_run", table_name="source_record")
    op.drop_constraint(op.f("ck_source_record_removed_is_closed"), "source_record", type_="check")
    op.drop_constraint(
        op.f("fk_source_record_tenant_id_removed_run_sync_run"),
        "source_record",
        type_="foreignkey",
    )
    op.drop_column("source_record", "removed_run")
    op.drop_column("source_record", "content_hash")
