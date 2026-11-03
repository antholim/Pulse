# AI contribution: 50% or more AI-generated
"""Records mapped from any source, and the cleaning they all go through before storage."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from app.processing.cleaning import DUPLICATE_IN_BATCH_REASON, clean_records, record_fingerprint
from app.processing.cleaning_config import get_cleaning_config

logger = logging.getLogger(__name__)

MISSING_REASON = "required field is missing"


class MappingError(ValueError):
    """The payload lacks a field the record cannot exist without."""


@dataclass(frozen=True)
class MappedRecord:
    """The columns of a `source_record` version that come from the payload."""

    kind: str
    external_id: str
    workspace_id: str | None
    name_normalized: str | None
    domain: str | None = None
    linkedin: str | None = None
    city: str | None = None
    external_ids: dict[str, list[str]] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MappingFailure:
    entity_kind: str
    external_id: str
    reason: str


@dataclass(frozen=True)
class MappingResult:
    records: tuple[MappedRecord, ...]
    failures: tuple[MappingFailure, ...]
    cleaning_flag_counts: dict[str, int] = field(default_factory=dict)


def clean_mapped(
    mapped: Iterable[MappedRecord], failures: Iterable[MappingFailure] = ()
) -> MappingResult:
    """Clean the scalar columns of each record and drop exact repeats within the batch.

    A record that loses a required field is added to `failures` after the given ones.
    """
    records = list(mapped)
    failed = list(failures)
    cleaned: list[MappedRecord] = []
    flag_counts: dict[str, int] = {}
    seen: set[str] = set()
    configs = {kind: get_cleaning_config(kind) for kind in {record.kind for record in records}}
    # Keep the last repeat, matching the versioned upsert's last-occurrence policy.
    for record in reversed(records):
        config = configs[record.kind]
        # Read only scalar columns; leave nested data untouched without copying it.
        values = {name: getattr(record, name) for name in config.fields}
        # No stored records: versioning alone decides whether a resync changed.
        result = clean_records([values], config)
        for reason, count in result.flag_counts.items():
            flag_counts[reason] = flag_counts.get(reason, 0) + count
        missing = [flag["field"] for flag in result.flags if flag["reason"] == MISSING_REASON]
        if missing:
            reason = "cleaning removed required fields: " + ", ".join(missing)
            logger.warning("Could not clean %s %s: %s", record.kind, record.external_id, reason)
            failed.append(MappingFailure(record.kind, record.external_id, reason))
            continue
        value = result.cleaned[0]
        fingerprint = record_fingerprint(
            {
                **value,
                "attributes": record.attributes,
                "external_ids": record.external_ids,
            }
        )
        if fingerprint in seen:
            flag_counts[DUPLICATE_IN_BATCH_REASON] = (
                flag_counts.get(DUPLICATE_IN_BATCH_REASON, 0) + 1
            )
            continue
        seen.add(fingerprint)
        cleaned.append(replace(record, **value))
    return MappingResult(tuple(reversed(cleaned)), tuple(failed), flag_counts)
