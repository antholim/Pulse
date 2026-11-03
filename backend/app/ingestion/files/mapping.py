# AI contribution: 50% or more AI-generated
"""Map valid import rows to source records, normalized like Omerlo records for matching."""

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from app.ingestion.connector import RawRecord
from app.ingestion.mapped import MappedRecord, MappingFailure, MappingResult, clean_mapped
from app.processing.normalization import (
    normalize_city,
    normalize_domain,
    normalize_email,
    normalize_linkedin,
    normalize_organization_name,
    normalize_person_name,
    normalize_phone,
)


def map_rows(
    records: Iterable[RawRecord], rejected: Iterable[MappingFailure] = ()
) -> MappingResult:
    """Map and clean the rows; `rejected` rows are reported after the rows cleaning drops."""
    result = clean_mapped(MAPPERS[record.entity_kind](record) for record in records)
    return replace(result, failures=result.failures + tuple(rejected))


def map_organization(record: RawRecord) -> MappedRecord:
    values = record.payload
    identifiers = {
        "emails": present(normalize_email(values.get("email"))),
        "phones": present(normalize_phone(values.get("phone")).e164),
        "domains": present(normalize_domain(values.get("website"))),
        "linkedin": present(normalize_linkedin(values.get("linkedin"))),
    }
    return MappedRecord(
        kind="organization",
        external_id=record.external_id,
        workspace_id=None,
        name_normalized=normalize_organization_name(values.get("name")),
        domain=first(identifiers["domains"]),
        linkedin=first(identifiers["linkedin"]),
        city=normalize_city(values.get("city")),
        attributes={**without_id(values), "identifiers": identifiers},
    )


def map_person(record: RawRecord) -> MappedRecord:
    values = record.payload
    names = (values.get("first_name"), values.get("last_name"))
    identifiers = {
        "emails": present(normalize_email(values.get("email"))),
        "linkedin": present(normalize_linkedin(values.get("linkedin"))),
    }
    return MappedRecord(
        kind="person",
        external_id=record.external_id,
        workspace_id=None,
        name_normalized=normalize_person_name(" ".join(name for name in names if name)),
        linkedin=first(identifiers["linkedin"]),
        attributes={**without_id(values), "identifiers": identifiers},
    )


MAPPERS: dict[str, Callable[[RawRecord], MappedRecord]] = {
    "organization": map_organization,
    "person": map_person,
}


def present(value: str | None) -> list[str]:
    return [] if value is None else [value]


def first(values: list[str]) -> str | None:
    return values[0] if values else None


def without_id(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key != "id"}
