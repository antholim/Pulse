# AI declaration: 50% or more AI-generated
"""Store the normalized city of source records.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_record", sa.Column("city", sa.Text(), nullable=True))
    op.create_index(
        "ix_source_record_city",
        "source_record",
        ["tenant_id", "city"],
        unique=False,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    # Stored organizations already keep their cities in attributes. A record whose cities
    # now normalize differently gets new attributes, so its next sync writes a new version.
    op.execute(
        """
        UPDATE source_record
        SET city = attributes -> 'cities' ->> 0
        WHERE kind = 'organization'
          AND jsonb_typeof(attributes -> 'cities') = 'array'
          AND jsonb_array_length(attributes -> 'cities') = 1
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_record_city",
        table_name="source_record",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_column("source_record", "city")
