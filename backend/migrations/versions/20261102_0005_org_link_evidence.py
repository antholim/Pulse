# AI declaration: Below 50% AI-generated
"""Store the evidence behind each organization link.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "org_link",
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_org_link_evidence_is_array"), "org_link", "jsonb_typeof(evidence) = 'array'"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_org_link_evidence_is_array"), "org_link", type_="check")
    op.drop_column("org_link", "evidence")
