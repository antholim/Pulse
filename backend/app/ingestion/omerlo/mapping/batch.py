"""Map the raw records of one sync run without letting one bad record stop it."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.ingestion.connector import RawRecord
from app.ingestion.omerlo.mapping.mappers import MappedRecord, MappingError, map_record
from app.models.records import ENTITY_KINDS

logger = logging.getLogger(__name__)

METADATA_SUFFIX = "_metadata"
CONTENT_BLOCKS = "content_blocks"


@dataclass(frozen=True)
class MappingFailure:
    entity_kind: str
    external_id: str
    reason: str


@dataclass(frozen=True)
class MappingResult:
    records: tuple[MappedRecord, ...]
    failures: tuple[MappingFailure, ...]


def map_records(raw_records: Iterable[RawRecord]) -> MappingResult:
    """Map every entity record; failures are logged with the external id and returned.

    A record and its companions must be in the same call, so the whole run is held in memory.
    """
    records = list(raw_records)
    companions = group_companions(records)
    mapped: list[MappedRecord] = []
    failures: list[MappingFailure] = []
    for record in records:
        if record.entity_kind not in ENTITY_KINDS:
            continue
        kind, key = record.entity_kind, record.external_id
        try:
            mapped.append(map_with_companions(record, companions))
        except MappingError as error:
            logger.warning("Could not map Omerlo %s %s: %s", kind, key, error)
            failures.append(MappingFailure(kind, key, str(error)))
        except Exception as error:
            # A payload shape no reader anticipated; keep the traceback to fix the mapper.
            logger.exception("Unexpected error mapping Omerlo %s %s", kind, key)
            failures.append(MappingFailure(kind, key, f"unexpected {type(error).__name__}"))
    return MappingResult(tuple(mapped), tuple(failures))


def group_companions(records: list[RawRecord]) -> dict[tuple[str, str], list[Any]]:
    """The `data` entries of companion records by (kind, parent id), joined across pages."""
    entity_ids = {record.external_id for record in records if record.entity_kind in ENTITY_KINDS}
    groups: dict[tuple[str, str], list[Any]] = {}
    for record in records:
        if not is_companion(record.entity_kind):
            continue
        parent = record.parent_external_id
        if parent not in entity_ids:
            logger.warning(
                "Dropping Omerlo %s %s: parent %s is not in this batch",
                record.entity_kind,
                record.external_id,
                parent,
            )
            continue
        groups.setdefault((record.entity_kind, parent), []).extend(data_list(record.payload))
    return groups


def map_with_companions(
    record: RawRecord, companions: dict[tuple[str, str], list[Any]]
) -> MappedRecord:
    key = record.external_id
    return map_record(
        record.entity_kind,
        record.payload,
        metadata=companions.get((record.entity_kind + METADATA_SUFFIX, key), []),
        blocks=companions.get((CONTENT_BLOCKS, key), []),
    )


def is_companion(entity_kind: str) -> bool:
    return entity_kind.endswith(METADATA_SUFFIX) or entity_kind == CONTENT_BLOCKS


def data_list(body: Any) -> list[Any]:
    """The `data` list of an API response body, or an empty list."""
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, list) else []
