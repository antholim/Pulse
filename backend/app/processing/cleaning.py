"""Clean PULSE data after mapping and before storage.

The original raw payload must be archived before mapping and cleaning.
This module only cleans mapped records and does not handle raw data storage.

The cleaner handles missing values, whitespace, Unicode, common encoding
problems, numbers, booleans, dates, emails, categories, and duplicate records.
Problems are flagged with the original value instead of silently deleting data.

The caller supplies existing records for historical duplicate checks.
This module does not connect to a database by itself.
"""

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MISSING_VALUES = {"", "n/a", "na", "null", "none", "unknown", "-"}
TRUE_VALUES = {"true", "yes", "oui", "1"}
FALSE_VALUES = {"false", "no", "non", "0"}
EMAIL_PATTERN = r"[^\s@]+@[^\s@]+\.[^\s@]+"


@dataclass
class FieldRule:
    """Rules used to clean one field."""

    type: str = "string"
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: tuple | None = None
    categories: dict = field(default_factory=dict)
    input_formats: tuple = ()
    source_timezone: str | None = None
    decimal_comma: bool = False


@dataclass
class CleaningConfig:
    """Cleaning rules for a specific kind of record."""

    fields: dict = field(default_factory=dict)
    unique_by: tuple = ()
    keep_extra_fields: bool = True
    remove_duplicate_records: bool = True


@dataclass
class CleaningResult:
    """Cleaned records, duplicates, problem flags, and counts."""

    cleaned: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    unprocessed: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    flag_counts: dict = field(default_factory=dict)


def _fix_encoding(text):
    """Try to repair common UTF-8 text decoded using the wrong encoding."""

    if not any(marker in text for marker in ("Ã", "Â", "â€", "â€™", "â€œ", "â€“")):
        return text

    for encoding in ("cp1252", "latin1"):
        try:
            fixed = text.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue

        # Only change it when the result looks less corrupted.
        bad_before = sum(text.count(marker) for marker in ("Ã", "Â", "â€"))
        bad_after = sum(fixed.count(marker) for marker in ("Ã", "Â", "â€"))
        if bad_after < bad_before:
            return fixed

    return text


def _clean_text(value):
    """Clean whitespace, Unicode, and common missing-value strings."""

    value = unicodedata.normalize("NFC", value)
    value = _fix_encoding(value)
    value = unicodedata.normalize("NFC", value)
    value = " ".join(value.split())

    if value.casefold() in MISSING_VALUES:
        return None

    return value


def _basic_clean(value):
    """Clean normal and nested values without changing the input object."""

    if isinstance(value, str):
        return _clean_text(value)

    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            cleaned_list.append(_basic_clean(item))
        return cleaned_list

    if isinstance(value, dict):
        cleaned_dict = {}
        for name, item in value.items():
            cleaned_dict[name] = _basic_clean(item)
        return cleaned_dict

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


def _make_flag(index, name, original, reason):
    """Create one report describing a problem with a record."""

    return {
        "record_index": index,
        "field": name,
        "original_value": original,
        "reason": reason,
    }


def _parse_date(value, rule):
    """Convert a date to YYYY-MM-DD or a datetime to ISO 8601 UTC."""

    date_value = None

    if isinstance(value, (datetime, date, date)):
        date_value = value
    elif isinstance(value, str):
        text = value
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        # ISO dates are unambiguous and can be read without a format setting.
        try:
            if rule.type == "date":
                date_value = date.fromisoformat(text)
            else:
                date_value = datetime.fromisoformat(text)
        except ValueError:
            pass

        # Other formats must be explicitly configured for the source.
        if date_value is None:
            for pattern in rule.input_formats:
                try:
                    date_value = datetime.strptime(value, pattern)
                    break
                except ValueError:
                    continue

        if date_value is None:
            if re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}.*", value):
                raise ValueError("ambiguous or unsupported day/month date; set input_formats")
            raise ValueError("invalid or unsupported date format")
    else:
        raise ValueError("invalid date or datetime")

    if rule.type == "date":
        if isinstance(date_value, datetime):
            # A date has no timezone. Only keep the calendar day.
            date_value = date_value.date()
        return date_value.isoformat()

    if not isinstance(date_value, datetime):
        raise ValueError("datetime needs a time value")

    if date_value.tzinfo is None:
        if not rule.source_timezone:
            raise ValueError("datetime has no timezone; configure source_timezone")

        try:
            local_timezone = ZoneInfo(rule.source_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("unknown source timezone") from error

        # Check daylight saving time: some local times are missing or occur twice.
        first = date_value.replace(tzinfo=local_timezone, fold=0)
        second = date_value.replace(tzinfo=local_timezone, fold=1)
        first_back = first.astimezone(UTC).astimezone(local_timezone)
        second_back = second.astimezone(UTC).astimezone(local_timezone)
        first_valid = first_back.replace(tzinfo=None) == date_value
        second_valid = second_back.replace(tzinfo=None) == date_value

        if not first_valid and not second_valid:
            raise ValueError("local datetime does not exist because of daylight saving time")
        if first.utcoffset() != second.utcoffset() and first_valid and second_valid:
            raise ValueError("ambiguous local datetime because of daylight saving time")

        date_value = first if first_valid else second

    return date_value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _convert(value, rule):
    """Convert a field into the type listed in its FieldRule."""

    if rule.type == "string":
        if not isinstance(value, str):
            raise ValueError("must be text")

    elif rule.type == "integer":
        if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value)):
            raise ValueError("invalid integer")
        value = int(value)

    elif rule.type == "number":
        if isinstance(value, bool):
            raise ValueError("invalid number")

        if isinstance(value, str) and rule.decimal_comma and "," in value and "." not in value:
            value = value.replace(",", ".")

        try:
            value = float(value)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("invalid number") from error

        if not math.isfinite(value):
            raise ValueError("number must be finite")

    elif rule.type == "boolean":
        if not isinstance(value, bool):
            # Reject arbitrary integers such as 2, but accept 0 and 1.
            if isinstance(value, int) and value not in (0, 1):
                raise ValueError("invalid boolean")
            text = str(value).casefold()
            if text in TRUE_VALUES:
                value = True
            elif text in FALSE_VALUES:
                value = False
            else:
                raise ValueError("invalid boolean")

    elif rule.type == "date" or rule.type == "datetime":
        value = _parse_date(value, rule)

    elif rule.type == "email":
        if not isinstance(value, str) or not re.fullmatch(EMAIL_PATTERN, value):
            raise ValueError("invalid email")
        value = value.casefold()

    else:
        raise ValueError("unknown field type: " + str(rule.type))

    # Categories can have French and English names for the same value.
    if rule.categories and isinstance(value, str):
        lookup = value.casefold()
        mapping = {}
        for name, standard_value in rule.categories.items():
            mapping[str(name).casefold()] = standard_value
        if lookup in mapping:
            value = mapping[lookup]

    # Unknown values stay in the record, but the caller adds a flag.
    if rule.allowed_values is not None and value not in rule.allowed_values:
        raise ValueError("value not in allowed values")

    if rule.min_value is not None or rule.max_value is not None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("number limits require a numeric field")
        if rule.min_value is not None and value < rule.min_value:
            raise ValueError("value is below minimum")
        if rule.max_value is not None and value > rule.max_value:
            raise ValueError("value is above maximum")

    return value


def _clean_one_record(original, config, index):
    """Clean one dictionary and return both the record and its flags."""

    flags = []
    cleaned = {}

    if config.keep_extra_fields:
        for name, value in original.items():
            cleaned[name] = _basic_clean(value)

    for name, rule in config.fields.items():
        raw_value = original.get(name)
        value = _basic_clean(raw_value)

        if value is None:
            cleaned[name] = None
            if rule.required:
                flags.append(_make_flag(index, name, raw_value, "required field is missing"))
            continue

        try:
            cleaned[name] = _convert(value, rule)
        except ValueError as error:
            # Keep the value instead of deleting it when conversion fails.
            cleaned[name] = value
            flags.append(_make_flag(index, name, raw_value, str(error)))

    return cleaned, flags


def record_fingerprint(record, fields=None):
    """Make a fingerprint of the full record or just chosen fields."""

    if fields is None:
        data = record
    else:
        data = {}
        for name in fields:
            data[name] = record.get(name)

    text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _can_compare(record, flags, fields):
    """Avoid using invalid or missing values to decide two records match."""

    if fields is None:
        return len(flags) == 0

    for name in fields:
        if record.get(name) is None:
            return False
        for flag in flags:
            if flag["field"] == name:
                return False
    return True


def remove_duplicates(new_records, existing_records=None, fields=None):
    """Standalone duplicate check for already cleaned dictionaries.

    The caller should pass cleaned records for accurate comparisons.
    Returns unique new records and separate duplicate records.
    """

    seen = set()
    unique = []
    duplicates = []

    for record in existing_records or []:
        if isinstance(record, dict) and _can_compare(record, [], fields):
            seen.add(record_fingerprint(record, fields))

    for record in new_records:
        if not isinstance(record, dict) or not _can_compare(record, [], fields):
            unique.append(record)
            continue
        fingerprint = record_fingerprint(record, fields)
        if fingerprint in seen:
            duplicates.append(record)
        else:
            unique.append(record)
            seen.add(fingerprint)

    return unique, duplicates


def clean_records(records, config, existing_records=None):
    """Clean a new batch and compare with old records when provided.

    Flagged records stay in cleaned. Duplicates go in a separate list,
    so they can be skipped during storage without losing their details.
    """

    result = CleaningResult()
    historical = set()
    seen_new = set()
    fields = config.unique_by if config.unique_by else None

    # Prepare old records using the exact same rules as new ones.
    if config.remove_duplicate_records:
        for old in existing_records or []:
            if not isinstance(old, dict):
                continue
            cleaned_old, old_flags = _clean_one_record(old, config, -1)
            if _can_compare(cleaned_old, old_flags, fields):
                historical.add(record_fingerprint(cleaned_old, fields))

    for index, original in enumerate(records):
        if not isinstance(original, dict):
            flag = _make_flag(index, "__record__", original, "record must be a dictionary")
            result.flags.append(flag)
            result.unprocessed.append({"index": index, "record": original})
            continue

        cleaned, flags = _clean_one_record(original, config, index)
        result.flags.extend(flags)

        if config.remove_duplicate_records:
            if _can_compare(cleaned, flags, fields):
                fingerprint = record_fingerprint(cleaned, fields)
                if fingerprint in historical:
                    reason = "duplicate of historical record"
                elif fingerprint in seen_new:
                    reason = "duplicate in current batch"
                else:
                    reason = None

                if reason is not None:
                    result.flags.append(_make_flag(index, "__record__", original, reason))
                    result.duplicates.append(
                        {
                            "index": index,
                            "record": cleaned,
                            "reason": reason,
                        }
                    )
                    continue

                seen_new.add(fingerprint)
            else:
                # Missing deduplication fields are already flagged if required.
                if fields is not None:
                    missing = [name for name in fields if cleaned.get(name) is None]
                    if missing:
                        result.flags.append(
                            _make_flag(
                                index,
                                ",".join(missing),
                                {name: original.get(name) for name in missing},
                                "missing duplicate key",
                            )
                        )

        # Includes records with data quality flags, as required by PULSE.
        result.cleaned.append(cleaned)

    # Store all counts in one place so the sync service can persist them.
    for flag in result.flags:
        reason = flag["reason"]
        result.flag_counts[reason] = result.flag_counts.get(reason, 0) + 1

    result.stats = {
        "received": len(records),
        "cleaned": len(result.cleaned),
        "duplicates": len(result.duplicates),
        "duplicate_in_batch": result.flag_counts.get("duplicate in current batch", 0),
        "duplicate_historical": result.flag_counts.get("duplicate of historical record", 0),
        "unprocessed": len(result.unprocessed),
        "flag_count": len(result.flags),
        "flagged_records": len(set(flag["record_index"] for flag in result.flags)),
    }
    return result
