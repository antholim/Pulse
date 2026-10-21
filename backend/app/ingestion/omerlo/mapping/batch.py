"""Map the raw records of one sync run without letting one bad record stop it (#57)."""

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
    """Map every entity record; failures are logged with the external id and returned."""
    records = list(raw_records)
    companions = {
        (record.entity_kind, record.parent_external_id): record.payload
        for record in records
        if is_companion(record.entity_kind) and record.parent_external_id
    }
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


def map_with_companions(record: RawRecord, companions: dict[tuple[str, str], Any]) -> MappedRecord:
    metadata = companions.get((record.entity_kind + METADATA_SUFFIX, record.external_id))
    blocks = companions.get((CONTENT_BLOCKS, record.external_id))
    return map_record(
        record.entity_kind,
        record.payload,
        metadata=data_list(metadata),
        blocks=data_list(blocks),
    )


def is_companion(entity_kind: str) -> bool:
    return entity_kind.endswith(METADATA_SUFFIX) or entity_kind == CONTENT_BLOCKS


def data_list(body: Any) -> list[Any]:
    """The `data` list of an API response body, or an empty list."""
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, list) else []
