import uuid

import pytest

from app.models import SyncRun
from app.services.record_changes import Change, count, diff_runs, order


def change(change_type: str, external_id: str = "org-1", kind: str = "organization") -> Change:
    return Change(change_type, kind, external_id, uuid.uuid4(), {})


def test_counts_hold_every_change_type_even_when_zero():
    # Arrange
    changes = [change("added", "org-1"), change("added", "org-2"), change("removed", "org-3")]

    # Act
    counts = count(changes)

    # Assert
    assert counts == {"added": 2, "modified": 0, "removed": 1}


def test_changes_are_ordered_by_kind_then_external_id():
    # Arrange
    changes = [change("added", "b"), change("removed", "a", "person"), change("modified", "a")]

    # Act
    ordered = sorted(changes, key=order)

    # Assert
    assert [(c.kind, c.external_id) for c in ordered] == [
        ("organization", "a"),
        ("organization", "b"),
        ("person", "a"),
    ]


def test_runs_of_two_sources_are_refused_before_any_query():
    # Arrange
    tenant_id = uuid.uuid4()
    first = SyncRun(tenant_id=tenant_id, source_id=uuid.uuid4())
    second = SyncRun(tenant_id=tenant_id, source_id=uuid.uuid4())

    # Act, Assert
    with pytest.raises(ValueError, match="same source"):
        diff_runs(None, first, second)
