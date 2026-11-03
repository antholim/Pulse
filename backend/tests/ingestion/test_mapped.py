# AI contribution: 50% or more AI-generated
"""Cleaning of mapped records, shared by every source."""

from app.ingestion.mapped import MappedRecord, MappingFailure, clean_mapped


def org(external_id="o1", name="acme", **fields):
    return MappedRecord(
        kind="organization",
        external_id=external_id,
        workspace_id=None,
        name_normalized=name,
        **fields,
    )


def test_a_record_left_without_a_required_field_becomes_a_failure():
    # Act
    result = clean_mapped([org(name=None), org("o2")])

    # Assert
    assert [r.external_id for r in result.records] == ["o2"]
    assert result.failures == (
        MappingFailure("organization", "o1", "cleaning removed required fields: name_normalized"),
    )
    assert result.cleaning_flag_counts == {"required field is missing": 1}


def test_exact_repeats_in_one_batch_keep_a_single_record():
    # Act
    result = clean_mapped([org(), org(), org("o2")])

    # Assert
    assert [r.external_id for r in result.records] == ["o1", "o2"]
    assert result.cleaning_flag_counts == {"duplicate in current batch": 1}


def test_failures_from_mapping_are_kept_before_the_cleaning_failures():
    # Arrange
    earlier = MappingFailure("organization", "o9", "organization has no name")

    # Act
    result = clean_mapped([org(name=None)], failures=[earlier])

    # Assert
    assert [f.external_id for f in result.failures] == ["o9", "o1"]
