import uuid
from typing import ClassVar

from sqlalchemy import ForeignKey, ForeignKeyConstraint, MetaData, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Fixed constraint names, so migrations can refer to them and Alembic can compare them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict] = {uuid.UUID: UUID(as_uuid=True)}


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


def tenant_id_column() -> Mapped[uuid.UUID]:
    """Non-null tenant_id: every table except tenant belongs to exactly one tenant (D5)."""
    return mapped_column(ForeignKey("tenant.id"))


def json_column(empty: str = "{}") -> Mapped[dict]:
    return mapped_column(JSONB, server_default=text(f"'{empty}'::jsonb"))


def same_tenant_fk(column: str, target: str) -> ForeignKeyConstraint:
    """Reference `target` through (tenant_id, id), so a row can only point inside its tenant.

    Every referenced table has a unique (tenant_id, id) constraint for this.
    """
    return ForeignKeyConstraint(["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"])


def one_of(column: str, values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"
