"""Schema rules of data model v1 (#25), checked on the model metadata without a database."""

import pytest
from sqlalchemy import ForeignKeyConstraint, Index, Table, UniqueConstraint

from app.models import Base

TABLES = Base.metadata.tables
TENANT_SCOPED = [table for name, table in TABLES.items() if name != "tenant"]


def foreign_keys(table: Table) -> list[ForeignKeyConstraint]:
    return [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]


def indexes(table: Table) -> list[tuple[list[str], bool]]:
    """(columns, unique) for every index Postgres has: indexes, unique constraints, primary key."""
    found = [([c.name for c in index.columns], bool(index.unique)) for index in table.indexes]
    found += [
        ([c.name for c in constraint.columns], True)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    found.append(([c.name for c in table.primary_key.columns], True))
    return found


def covers(index_columns: list[str], unique: bool, fk_columns: list[str]) -> bool:
    """An index serves a foreign key when it starts with the key's columns, in any order,
    or when it is unique on some of them (one row matches, so the rest is a cheap filter)."""
    leading = set(index_columns[: len(fk_columns)])
    return leading == set(fk_columns) or (unique and set(index_columns) <= set(fk_columns))


def test_data_model_v1_has_the_nine_tables():
    assert set(TABLES) == {
        "tenant",
        "source",
        "sync_run",
        "raw_record",
        "source_record",
        "organization",
        "org_link",
        "match_candidate",
        "record_change",
    }


@pytest.mark.parametrize("table", TENANT_SCOPED, ids=lambda t: t.name)
def test_every_table_belongs_to_a_tenant(table):
    column = table.c.tenant_id

    assert not column.nullable
    assert {fk.target_fullname for fk in column.foreign_keys} >= {"tenant.id"}


@pytest.mark.parametrize("table", TENANT_SCOPED, ids=lambda t: t.name)
def test_references_between_tables_stay_inside_the_tenant(table):
    for fk in foreign_keys(table):
        target = fk.referred_table.name
        if target == "tenant":
            continue
        pairs = {(c.name, e.column.name) for c, e in zip(fk.columns, fk.elements, strict=True)}
        assert ("tenant_id", "tenant_id") in pairs, f"{fk.name} does not carry tenant_id"


@pytest.mark.parametrize("table", TENANT_SCOPED, ids=lambda t: t.name)
def test_every_foreign_key_is_indexed(table):
    table_indexes = indexes(table)
    for fk in foreign_keys(table):
        columns = [c.name for c in fk.columns]
        assert any(covers(cols, unique, columns) for cols, unique in table_indexes), (
            f"{fk.name} on {columns} has no index serving it"
        )


def test_at_most_one_current_version_per_source_record():
    index = next(i for i in TABLES["source_record"].indexes if i.name == "ux_source_record_current")

    assert isinstance(index, Index)
    assert index.unique
    assert [c.name for c in index.columns] == ["tenant_id", "source_id", "external_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "valid_to IS NULL"
