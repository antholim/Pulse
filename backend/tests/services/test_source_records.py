import uuid
from datetime import UTC, datetime

from app.ingestion.omerlo.mapping.mappers import MappedRecord
from app.models import SyncRun
from app.processing.content_hash import content_hash
from app.services.source_records import Latest, plan_batch

RUN = SyncRun(
    id=uuid.uuid4(),
    tenant_id=uuid.uuid4(),
    source_id=uuid.uuid4(),
    started_at=datetime(2026, 10, 21, tzinfo=UTC),
)


def record(external_id: str, name: str = "groupe exemple") -> MappedRecord:
    return MappedRecord(
        kind="organization", external_id=external_id, workspace_id=None, name_normalized=name
    )


def latest(name: str = "groupe exemple", *, current: bool = True) -> Latest:
    return Latest(uuid.uuid4(), content_hash(record("org-1", name)), current=current)


def test_a_record_never_seen_is_inserted_as_added():
    # Act
    plan = plan_batch(RUN, [record("org-1")], {})

    # Assert
    assert plan.result.added == ["org-1"]
    assert plan.to_close == plan.to_touch == plan.carried == []
    [row] = plan.inserts
    assert row["valid_from"] == RUN.started_at
    assert row["first_seen_run"] == row["last_seen_run"] == RUN.id
    assert row["content_hash"] == content_hash(record("org-1"))


def test_an_unchanged_record_is_only_touched():
    # Arrange
    current = latest()

    # Act
    plan = plan_batch(RUN, [record("org-1")], {"org-1": current})

    # Assert
    assert plan.result.unchanged == ["org-1"]
    assert plan.to_touch == [current.id]
    assert plan.inserts == plan.to_close == plan.carried == []


def test_a_changed_record_closes_its_version_and_carries_its_links():
    # Arrange
    current = latest()

    # Act
    plan = plan_batch(RUN, [record("org-1", "nouveau nom")], {"org-1": current})

    # Assert
    assert plan.result.changed == ["org-1"]
    assert plan.to_close == [current.id]
    [row] = plan.inserts
    assert row["name_normalized"] == "nouveau nom"
    assert plan.carried == [(current.id, row["id"])]


def test_a_record_back_after_removal_is_added_and_carries_its_links():
    # Arrange
    removed = latest(current=False)

    # Act
    plan = plan_batch(RUN, [record("org-1")], {"org-1": removed})

    # Assert
    assert plan.result.added == ["org-1"]
    assert plan.to_close == plan.to_touch == []
    [row] = plan.inserts
    assert plan.carried == [(removed.id, row["id"])]
