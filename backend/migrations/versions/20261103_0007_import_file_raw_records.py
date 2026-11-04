# AI contribution: 50% or more AI-generated
"""Archive the whole file a file import reads as a raw record.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03 02:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RAW_ENTITY_KINDS = (
    "'organization', 'person', 'project', 'event', 'content', 'workspace', 'category', "
    "'organization_metadata', 'person_metadata', 'project_metadata', 'event_metadata', "
    "'event_session', 'content_blocks'"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_raw_record_entity_kind"), "raw_record", type_="check")
    op.create_check_constraint(
        op.f("ck_raw_record_entity_kind"),
        "raw_record",
        f"entity_kind IN ({RAW_ENTITY_KINDS}, 'import_file')",
    )


def downgrade() -> None:
    # Archived files cannot satisfy the narrower constraint.
    op.execute("DELETE FROM raw_record WHERE entity_kind = 'import_file'")
    op.drop_constraint(op.f("ck_raw_record_entity_kind"), "raw_record", type_="check")
    op.create_check_constraint(
        op.f("ck_raw_record_entity_kind"), "raw_record", f"entity_kind IN ({RAW_ENTITY_KINDS})"
    )
