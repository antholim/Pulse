"""Unit tests for PULSE cleaning. Each test uses Arrange, Act, Assert."""

from datetime import date, datetime, timezone

import pytest

from app.processing.cleaning import (
    CleaningConfig,
    FieldRule,
    _basic_clean,
    _convert,
    clean_records,
    record_fingerprint,
    remove_duplicates,
)
from app.processing.cleaning_config import get_cleaning_config


def test_empty_batch():
    # Arrange
    config = CleaningConfig()
    # Act
    result = clean_records([], config)
    # Assert
    assert result.cleaned == []
    assert result.flags == []
    assert result.stats["received"] == 0


def test_text_spaces_and_newlines():
    # Arrange
    records = [{"name": "  Jazz\n  Festival \t Montréal "}]
    config = CleaningConfig(fields={"name": FieldRule(required=True)})
    # Act
    result = clean_records(records, config)
    # Assert
    assert result.cleaned[0]["name"] == "Jazz Festival Montréal"


@pytest.mark.parametrize("value", ["N/A", " unknown ", "NULL", "none", "-", "", " nA "])
def test_missing_value_markers(value):
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule()})
    # Act
    result = clean_records([{"name": value}], config)
    # Assert
    assert result.cleaned[0]["name"] is None


def test_missing_required_is_flagged_but_kept():
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule(required=True)})
    # Act
    result = clean_records([{"name": "N/A"}], config)
    # Assert
    assert result.cleaned == [{"name": None}]
    assert result.flags[0] == {
        "record_index": 0,
        "field": "name",
        "original_value": "N/A",
        "reason": "required field is missing",
    }


def test_missing_field_in_dictionary():
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule(required=True)})
    # Act
    result = clean_records([{}], config)
    # Assert
    assert result.cleaned == [{"name": None}]
    assert result.stats["flagged_records"] == 1


def test_optional_field_can_be_missing():
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule()})
    # Act
    result = clean_records([{}], config)
    # Assert
    assert result.flags == []
    assert result.cleaned == [{"name": None}]


def test_unicode_normalization_nfc():
    # Arrange
    decomposed = "Cafe\u0301"
    config = CleaningConfig(fields={"name": FieldRule(required=True)})
    # Act
    result = clean_records([{"name": decomposed}], config)
    # Assert
    assert result.cleaned[0]["name"] == "Café"


@pytest.mark.parametrize(
    "broken, fixed",
    [
        ("QuÃ©bec", "Québec"),
        ("FranÃ§ais", "Français"),
        ("Itâ€™s", "It’s"),
    ],
)
def test_common_encoding_repairs(broken, fixed):
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule(required=True)})
    # Act
    result = clean_records([{"name": broken}], config)
    # Assert
    assert result.cleaned[0]["name"] == fixed


def test_nested_list_and_dictionary_text():
    # Arrange
    records = [{"details": {"city": "  Montréal  ", "tags": [" music ", " N/A "]}}]
    config = CleaningConfig()
    # Act
    result = clean_records(records, config)
    # Assert
    assert result.cleaned[0]["details"] == {"city": "Montréal", "tags": ["music", None]}
    assert records[0]["details"]["tags"][0] == " music "


def test_convert_integer():
    # Arrange
    config = CleaningConfig(fields={"capacity": FieldRule(type="integer")})
    # Act
    result = clean_records([{"capacity": "120"}], config)
    # Assert
    assert result.cleaned[0]["capacity"] == 120
    assert isinstance(result.cleaned[0]["capacity"], int)


@pytest.mark.parametrize("value", ["12.5", "words", True])
def test_invalid_integer_keeps_original_and_flags(value):
    # Arrange
    config = CleaningConfig(fields={"capacity": FieldRule(type="integer")})
    # Act
    result = clean_records([{"capacity": value}], config)
    # Assert
    assert result.cleaned[0]["capacity"] == value
    assert result.flags[0]["reason"] == "invalid integer"


def test_numeric_conversion():
    # Arrange
    config = CleaningConfig(fields={"price": FieldRule(type="number")})
    # Act
    result = clean_records([{"price": "19.95"}], config)
    # Assert
    assert result.cleaned[0]["price"] == 19.95
    assert isinstance(result.cleaned[0]["price"], float)


@pytest.mark.parametrize("value", ["bad", True, "inf", "NaN"])
def test_invalid_numeric_values_flagged(value):
    # Arrange
    config = CleaningConfig(fields={"price": FieldRule(type="number")})
    # Act
    result = clean_records([{"price": value}], config)
    # Assert
    assert len(result.flags) == 1
    assert result.cleaned[0]["price"] == value


def test_french_decimal_comma_if_configured():
    # Arrange
    config = CleaningConfig(fields={"price": FieldRule(type="number", decimal_comma=True)})
    # Act
    result = clean_records([{"price": "12,50"}], config)
    # Assert
    assert result.cleaned[0]["price"] == 12.5


def test_decimal_comma_not_guessed():
    # Arrange
    config = CleaningConfig(fields={"price": FieldRule(type="number")})
    # Act
    result = clean_records([{"price": "12,50"}], config)
    # Assert
    assert result.flags[0]["reason"] == "invalid number"


@pytest.mark.parametrize(
    "input_value, output",
    [
        ("YES", True),
        ("no", False),
        ("oui", True),
        ("NON", False),
        ("TRUE", True),
        ("false", False),
        (1, True),
        (0, False),
        (True, True),
    ],
)
def test_boolean_french_english(input_value, output):
    # Arrange
    config = CleaningConfig(fields={"active": FieldRule(type="boolean")})
    # Act
    result = clean_records([{"active": input_value}], config)
    # Assert
    assert result.cleaned[0]["active"] is output


@pytest.mark.parametrize("value", ["maybe", 2, 0.5])
def test_invalid_boolean_is_flagged(value):
    # Arrange
    config = CleaningConfig(fields={"active": FieldRule(type="boolean")})
    # Act
    result = clean_records([{"active": value}], config)
    # Assert
    assert result.flags[0]["reason"] == "invalid boolean"


def test_email_lowercase_and_spaces():
    # Arrange
    config = CleaningConfig(fields={"email": FieldRule(type="email")})
    # Act
    result = clean_records([{"email": "  HELLO@EXAMPLE.COM  "}], config)
    # Assert
    assert result.cleaned[0]["email"] == "hello@example.com"


def test_invalid_email_kept_and_flagged():
    # Arrange
    config = CleaningConfig(fields={"email": FieldRule(type="email")})
    # Act
    result = clean_records([{"email": "not-an-email"}], config)
    # Assert
    assert result.cleaned[0]["email"] == "not-an-email"
    assert result.flags[0]["reason"] == "invalid email"


def test_numeric_limits():
    # Arrange
    config = CleaningConfig(fields={"rating": FieldRule(type="number", min_value=0, max_value=5)})
    # Act
    result = clean_records([{"rating": "4.5"}, {"rating": "-1"}, {"rating": "6"}], config)
    # Assert
    assert [item["rating"] for item in result.cleaned] == [4.5, "-1", "6"]
    assert [flag["reason"] for flag in result.flags] == [
        "value is below minimum",
        "value is above maximum",
    ]


def test_range_rule_on_non_number_is_flagged():
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule(min_value=1)})
    # Act
    result = clean_records([{"name": "Event"}], config)
    # Assert
    assert result.flags[0]["reason"] == "number limits require a numeric field"


def test_allowed_values():
    # Arrange
    config = CleaningConfig(fields={"status": FieldRule(allowed_values=("open", "closed"))})
    # Act
    result = clean_records([{"status": "open"}, {"status": "pending"}], config)
    # Assert
    assert result.cleaned[1]["status"] == "pending"
    assert result.flags[0]["original_value"] == "pending"
    assert result.flags[0]["reason"] == "value not in allowed values"


def test_category_mapping_mixed_french_english():
    # Arrange
    rule = FieldRule(
        allowed_values=("organizer", "speaker"),
        categories={
            "organisateur": "organizer",
            "ORGANIZER": "organizer",
            "conférencier": "speaker",
        },
    )
    config = CleaningConfig(fields={"role": rule})
    # Act
    result = clean_records([{"role": "ORGANISATEUR"}, {"role": "conférencier"}], config)
    # Assert
    assert result.cleaned == [{"role": "organizer"}, {"role": "speaker"}]
    assert result.flags == []


def test_unknown_category_is_kept_and_flagged():
    # Arrange
    rule = FieldRule(allowed_values=("organizer",), categories={"organisateur": "organizer"})
    config = CleaningConfig(fields={"role": rule})
    # Act
    result = clean_records([{"role": "volunteer"}], config)
    # Assert
    assert result.cleaned == [{"role": "volunteer"}]
    assert result.flags[0]["original_value"] == "volunteer"


def test_iso_date():
    # Arrange
    config = CleaningConfig(fields={"day": FieldRule(type="date")})
    # Act
    result = clean_records([{"day": "2026-12-31"}], config)
    # Assert
    assert result.cleaned[0]["day"] == "2026-12-31"


def test_configured_non_iso_date():
    # Arrange
    config = CleaningConfig(fields={"day": FieldRule(type="date", input_formats=("%d/%m/%Y",))})
    # Act
    result = clean_records([{"day": "31/12/2026"}], config)
    # Assert
    assert result.cleaned[0]["day"] == "2026-12-31"


def test_ambiguous_day_month_date_is_flagged():
    # Arrange
    config = CleaningConfig(fields={"day": FieldRule(type="date")})
    # Act
    result = clean_records([{"day": "03/04/2026"}], config)
    # Assert
    assert result.cleaned[0]["day"] == "03/04/2026"
    assert "day/month" in result.flags[0]["reason"]


def test_impossible_date_flagged():
    # Arrange
    config = CleaningConfig(fields={"day": FieldRule(type="date")})
    # Act
    result = clean_records([{"day": "2026-02-30"}], config)
    # Assert
    assert result.flags[0]["reason"] == "invalid or unsupported date format"


def test_date_object():
    # Arrange
    config = CleaningConfig(fields={"day": FieldRule(type="date")})
    # Act
    result = clean_records([{"day": date(2026, 11, 20)}], config)
    # Assert
    assert result.cleaned[0]["day"] == "2026-11-20"


def test_datetime_with_z_converts_to_utc():
    # Arrange
    config = CleaningConfig(fields={"start": FieldRule(type="datetime")})
    # Act
    result = clean_records([{"start": "2026-10-20T16:30:00+02:00"}], config)
    # Assert
    assert result.cleaned[0]["start"] == "2026-10-20T14:30:00Z"


def test_datetime_zulu_remains_zulu():
    # Arrange
    config = CleaningConfig(fields={"start": FieldRule(type="datetime")})
    # Act
    result = clean_records([{"start": "2026-10-20T14:30:00Z"}], config)
    # Assert
    assert result.cleaned[0]["start"] == "2026-10-20T14:30:00Z"


def test_naive_datetime_requires_timezone():
    # Arrange
    config = CleaningConfig(fields={"start": FieldRule(type="datetime")})
    # Act
    result = clean_records([{"start": "2026-10-20T14:30:00"}], config)
    # Assert
    assert "source_timezone" in result.flags[0]["reason"]


def test_local_datetime_with_source_timezone():
    # Arrange
    config = CleaningConfig(
        fields={"start": FieldRule(type="datetime", source_timezone="America/Toronto")}
    )
    # Act
    result = clean_records([{"start": "2026-10-20T14:30:00"}], config)
    # Assert
    assert result.cleaned[0]["start"] == "2026-10-20T18:30:00Z"


def test_configured_datetime_format():
    # Arrange
    rule = FieldRule(
        type="datetime", input_formats=("%d/%m/%Y %H:%M",), source_timezone="America/Toronto"
    )
    config = CleaningConfig(fields={"start": rule})
    # Act
    result = clean_records([{"start": "20/10/2026 14:30"}], config)
    # Assert
    assert result.cleaned[0]["start"] == "2026-10-20T18:30:00Z"


def test_dst_repeated_time_is_flagged():
    # Arrange
    rule = FieldRule(type="datetime", source_timezone="America/Toronto")
    config = CleaningConfig(fields={"start": rule})
    # Act
    result = clean_records([{"start": "2026-11-01T01:30:00"}], config)
    # Assert
    assert "ambiguous local datetime" in result.flags[0]["reason"]


def test_dst_missing_time_is_flagged():
    # Arrange
    rule = FieldRule(type="datetime", source_timezone="America/Toronto")
    config = CleaningConfig(fields={"start": rule})
    # Act
    result = clean_records([{"start": "2026-03-08T02:30:00"}], config)
    # Assert
    assert "does not exist" in result.flags[0]["reason"]


def test_bad_timezone_is_flagged():
    # Arrange
    config = CleaningConfig(
        fields={"start": FieldRule(type="datetime", source_timezone="Invalid/Zone")}
    )
    # Act
    result = clean_records([{"start": "2026-10-20T14:30:00"}], config)
    # Assert
    assert result.flags[0]["reason"] == "unknown source timezone"


def test_keep_extra_fields_and_clean_nested_data():
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule(required=True)})
    # Act
    result = clean_records([{"name": "Art", "note": "  good   event "}], config)
    # Assert
    assert result.cleaned[0]["note"] == "good event"


def test_remove_extra_fields():
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule()}, keep_extra_fields=False)
    # Act
    result = clean_records([{"name": "Art", "note": "Hi"}], config)
    # Assert
    assert result.cleaned == [{"name": "Art"}]


def test_batch_duplicates_by_key():
    # Arrange
    config = CleaningConfig(fields={"id": FieldRule(required=True)}, unique_by=("id",))
    # Act
    result = clean_records([{"id": "101"}, {"id": "102"}, {"id": "101"}], config)
    # Assert
    assert [record["id"] for record in result.cleaned] == ["101", "102"]
    assert len(result.duplicates) == 1
    assert result.stats["duplicate_in_batch"] == 1
    assert result.duplicates[0]["record"] == {"id": "101"}


def test_historical_duplicates_by_key():
    # Arrange
    config = CleaningConfig(fields={"id": FieldRule(required=True)}, unique_by=("id",))
    old = [{"id": "101"}]
    # Act
    result = clean_records([{"id": "101"}, {"id": "102"}], config, existing_records=old)
    # Assert
    assert result.cleaned == [{"id": "102"}]
    assert result.stats["duplicate_historical"] == 1


def test_historical_data_cleaned_before_comparison():
    # Arrange
    config = CleaningConfig(fields={"name": FieldRule(required=True)}, unique_by=("name",))
    # Act
    result = clean_records([{"name": "Québec"}], config, [{"name": " QuÃ©bec  "}])
    # Assert
    assert result.cleaned == []
    assert result.duplicates[0]["reason"] == "duplicate of historical record"


def test_historical_converted_key_matches_new_key():
    # Arrange
    config = CleaningConfig(
        fields={"id": FieldRule(type="integer", required=True)}, unique_by=("id",)
    )
    # Act
    result = clean_records([{"id": 12}], config, [{"id": "12"}])
    # Assert
    assert result.cleaned == []
    assert len(result.duplicates) == 1


def test_whole_record_duplicate_when_no_key():
    # Arrange
    config = CleaningConfig()
    records = [{"id": 1, "name": "Art"}, {"name": "Art", "id": 1}, {"name": "Art", "id": 2}]
    # Act
    result = clean_records(records, config)
    # Assert
    assert len(result.cleaned) == 2
    assert result.stats["duplicates"] == 1


def test_whole_record_historical_duplicate():
    # Arrange
    config = CleaningConfig()
    # Act
    result = clean_records([{"id": 1, "name": "Art"}], config, [{"name": "Art", "id": 1}])
    # Assert
    assert result.cleaned == []
    assert result.stats["duplicate_historical"] == 1


def test_invalid_historical_key_does_not_block_new_record():
    # Arrange
    config = CleaningConfig(fields={"id": FieldRule(type="integer")}, unique_by=("id",))
    # Act
    result = clean_records([{"id": 1}], config, [{"id": "oops"}])
    # Assert
    assert result.cleaned == [{"id": 1}]
    assert result.duplicates == []


def test_missing_duplicate_key_flagged_not_removed():
    # Arrange
    config = CleaningConfig(unique_by=("id",))
    # Act
    result = clean_records([{"name": "Concert"}], config)
    # Assert
    assert result.cleaned == [{"name": "Concert"}]
    assert result.flags[0]["reason"] == "missing duplicate key"


def test_duplicate_removal_can_be_disabled():
    # Arrange
    config = CleaningConfig(remove_duplicate_records=False)
    # Act
    result = clean_records([{"id": 1}, {"id": 1}], config, [{"id": 1}])
    # Assert
    assert len(result.cleaned) == 2
    assert result.duplicates == []


def test_standalone_remove_duplicates():
    # Arrange
    new = [{"id": 1}, {"id": 2}, {"id": 2}]
    old = [{"id": 1}]
    # Act
    unique, duplicates = remove_duplicates(new, old, fields=("id",))
    # Assert
    assert unique == [{"id": 2}]
    assert duplicates == [{"id": 1}, {"id": 2}]


def test_standalone_remove_duplicates_skips_missing_key():
    # Arrange
    new = [{"name": "Event"}, {"name": "Event"}]
    # Act
    unique, duplicates = remove_duplicates(new, fields=("id",))
    # Assert
    assert len(unique) == 2
    assert duplicates == []


def test_full_fingerprint_ignores_dictionary_order():
    # Arrange
    first = {"name": "Art", "id": 1}
    second = {"id": 1, "name": "Art"}
    # Act
    first_hash = record_fingerprint(first)
    second_hash = record_fingerprint(second)
    # Assert
    assert first_hash == second_hash


def test_fingerprint_selected_fields():
    # Arrange
    first = {"id": 1, "name": "Art"}
    second = {"id": 1, "name": "Music"}
    # Act
    first_hash = record_fingerprint(first, ("id",))
    second_hash = record_fingerprint(second, ("id",))
    # Assert
    assert first_hash == second_hash


def test_bad_record_type_is_reported():
    # Arrange
    config = CleaningConfig()
    # Act
    result = clean_records(["bad", 42, {"name": "Art"}], config)
    # Assert
    assert len(result.unprocessed) == 2
    assert result.cleaned == [{"name": "Art"}]
    assert result.stats["unprocessed"] == 2
    assert result.flags[0]["field"] == "__record__"


def test_stats_and_flag_counts():
    # Arrange
    config = CleaningConfig(fields={"id": FieldRule(required=True)}, unique_by=("id",))
    data = [{"id": "A"}, {"id": "A"}, {"id": None}, "wrong"]
    # Act
    result = clean_records(data, config)
    # Assert
    assert result.stats["received"] == 4
    assert result.stats["cleaned"] == 2
    assert result.stats["duplicates"] == 1
    assert result.stats["unprocessed"] == 1
    assert result.stats["flagged_records"] == 3
    assert result.stats["flag_count"] == 4
    assert result.flag_counts["required field is missing"] == 1


def test_does_not_change_original_records():
    # Arrange
    records = [{"name": "  Café  ", "extra": ["  hello  "]}]
    config = CleaningConfig(fields={"name": FieldRule()})
    # Act
    clean_records(records, config)
    # Assert
    assert records == [{"name": "  Café  ", "extra": ["  hello  "]}]


def test_cleaning_is_idempotent():
    # Arrange
    rule = FieldRule(type="datetime", source_timezone="America/Toronto")
    config = CleaningConfig(fields={"start": rule, "name": FieldRule()})
    records = [{"name": " QuÃ©bec   Event ", "start": "2026-10-20T13:00:00"}]
    # Act
    first = clean_records(records, config)
    second = clean_records(first.cleaned, config)
    # Assert
    assert second.cleaned == first.cleaned
    assert second.flags == []


def test_flags_repeat_deterministically_for_bad_value():
    # Arrange
    config = CleaningConfig(fields={"rating": FieldRule(type="number")})
    records = [{"rating": "not a number"}]
    # Act
    first = clean_records(records, config)
    second = clean_records(records, config)
    # Assert
    assert first.cleaned == second.cleaned
    assert first.flags == second.flags


def test_multiple_rules_can_flag_one_record():
    # Arrange
    config = CleaningConfig(
        fields={"name": FieldRule(required=True), "price": FieldRule(type="number")}
    )
    # Act
    result = clean_records([{"name": "", "price": "wrong"}], config)
    # Assert
    assert result.stats["flagged_records"] == 1
    assert result.stats["flag_count"] == 2


def test_unknown_field_type_keeps_value_and_flags():
    # Arrange
    config = CleaningConfig(fields={"value": FieldRule(type="wrong")})
    # Act
    result = clean_records([{"value": "abc"}], config)
    # Assert
    assert result.cleaned == [{"value": "abc"}]
    assert "unknown field type" in result.flags[0]["reason"]


def test_config_is_selected_by_entity_kind():
    # Arrange
    event = {"external_id": "12", "name": "  Jazz  ", "active": "oui", "status": "prévu"}
    # Act
    result = clean_records([event], get_cleaning_config("event"))
    # Assert
    assert result.cleaned[0]["name"] == "Jazz"
    assert result.cleaned[0]["active"] is True
    assert result.cleaned[0]["status"] == "planned"


def test_unknown_entity_kind_fails_loudly():
    # Arrange
    unknown_kind = "not_configured"
    # Act and Assert
    with pytest.raises(ValueError, match="No cleaning config"):
        get_cleaning_config(unknown_kind)


def test_basic_clean_finite_float_and_missing_nested():
    # Arrange
    record = {"values": [float("inf"), " null ", " ok "]}
    # Act
    result = _basic_clean(record)
    # Assert
    assert result == {"values": [None, None, "ok"]}


def test_convert_accepts_datetime_object():
    # Arrange
    rule = FieldRule(type="datetime")
    value = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    # Act
    result = _convert(value, rule)
    # Assert
    assert result == "2026-10-20T10:00:00Z"


def test_mixed_french_english_records():
    # Arrange
    # Sample data is written here so we do not need a separate JSON file.
    records = [
        {
            "external_id": "E101",
            "name": " QuÃ©bec   Festival ",
            "active": "oui",
            "status": "prévu",
            "start_at": "20/10/2026 14:30",
        },
        {
            "external_id": "E102",
            "name": "",
            "active": "no",
            "status": "annulé",
            "start_at": "03/04/2026",
        },
        {
            "external_id": "E101",
            "name": "Québec Festival",
            "active": "oui",
            "status": "planned",
            "start_at": "2026-10-20T18:30:00Z",
        },
        {"external_id": "E103", "name": "Talk", "active": "maybe", "status": "unrecognized"},
        {"external_id": "E104", "name": " Music Night ", "active": "true", "status": "completed"},
    ]
    config = get_cleaning_config("event")

    # Act
    result = clean_records(records, config)

    # Assert
    assert result.stats["received"] == 5
    assert result.stats["duplicates"] == 1
    assert result.stats["flagged_records"] >= 3
    assert result.cleaned[0]["name"] == "Québec Festival"
