"""Versions of one source record cannot overlap in time (#25, #58).

Without this, two closed versions could cover the same instant and the as-of query
would return both. btree_gist lets the GiST index compare the uuid and text columns
with =.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20 18:05:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    # create_exclude_constraint cannot take the tstzrange expression, so write the SQL.
    op.execute(
        "ALTER TABLE source_record ADD CONSTRAINT ex_source_record_versions_overlap "
        "EXCLUDE USING gist (tenant_id WITH =, source_id WITH =, external_id WITH =, "
        "tstzrange(valid_from, valid_to) WITH &&)"
    )


def downgrade() -> None:
    op.drop_constraint("ex_source_record_versions_overlap", "source_record")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
