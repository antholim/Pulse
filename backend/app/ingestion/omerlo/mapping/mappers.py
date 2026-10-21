"""Map Omerlo backoffice detail payloads to PULSE source records."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from app.ingestion.omerlo.mapping.fields import (
    cities,
    contact_identifiers,
    dicts,
    first,
    flag,
    grouped,
    html_text,
    id_text,
    live_entries,
    metadata_ids,
    profile_workspace_id,
    text,
    timestamp,
    unique,
)
from app.processing.normalization import (
    normalize_organization_name,
    normalize_person_name,
    normalize_text,
)

PERSON_IDENTIFIERS = ("emails", "linkedin")


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
    external_ids: dict[str, list[str]] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


def map_organization(payload: dict[str, Any]) -> MappedRecord:
    record_id = required_id(payload)
    name = text(payload.get("name"))
    if name is None:
        raise MappingError("organization has no name")
    identifiers = contact_identifiers(payload)
    return MappedRecord(
        kind="organization",
        external_id=record_id,
        workspace_id=profile_workspace_id(payload),
        name_normalized=normalize_organization_name(name),
        domain=first(identifiers["domains"]),
        linkedin=first(identifiers["linkedin"]),
        attributes=profile_attributes(payload, identifiers),
    )


def map_person(payload: dict[str, Any]) -> MappedRecord:
    record_id = required_id(payload)
    first_name, last_name = text(payload.get("first_name")), text(payload.get("last_name"))
    full_name = " ".join(part for part in (first_name, last_name) if part)
    if not full_name:
        raise MappingError("person has no name")
    identifiers = contact_identifiers(payload)
    titles = (
        (text(locale.get("locale")), text(locale.get("job_title")))
        for locale in live_entries(payload, "locales")
    )
    return MappedRecord(
        kind="person",
        external_id=record_id,
        workspace_id=profile_workspace_id(payload),
        name_normalized=normalize_person_name(full_name),
        linkedin=first(identifiers["linkedin"]),
        attributes={
            "first_name": first_name,
            "last_name": last_name,
            "job_titles": {locale: title for locale, title in titles if locale and title},
            "identifiers": {key: identifiers[key] for key in PERSON_IDENTIFIERS},
        },
    )


def map_project(payload: dict[str, Any]) -> MappedRecord:
    return map_named_profile("project", payload)


def map_event(payload: dict[str, Any]) -> MappedRecord:
    return map_named_profile("event", payload)


def map_named_profile(kind: str, payload: dict[str, Any]) -> MappedRecord:
    """The first locale name is the key; none is fine, since these are not matched by name."""
    names = (text(locale.get("name")) for locale in live_entries(payload, "locales"))
    return MappedRecord(
        kind=kind,
        external_id=required_id(payload),
        workspace_id=profile_workspace_id(payload),
        name_normalized=normalize_text(first(names)),
        attributes=profile_attributes(payload, contact_identifiers(payload)),
    )


def map_content(payload: dict[str, Any], blocks: list[Any]) -> MappedRecord:
    locales = live_entries(payload, "locales")
    title = first(html_text(locale.get("title_html")) for locale in locales)
    authors = unique(
        id_text(author.get("profile_id"))
        for locale in locales
        for author in dicts(locale.get("authors"))
    )
    return MappedRecord(
        kind="content",
        external_id=required_id(payload),
        workspace_id=id_text(payload.get("workspace_id")),
        name_normalized=normalize_text(title),
        attributes={
            **without_id(payload),
            "is_sponsored": flag(payload.get("is_sponsored")),
            "is_advertising": flag(payload.get("is_advertising")),
            "published_at": timestamp(payload.get("published_at")),
            "author_profile_ids": authors,
            "linked_profiles": linked_profiles(blocks),
        },
    )


def linked_profiles(blocks: list[Any]) -> dict[str, list[str]]:
    """Profile ids linked through Profiles blocks, by profile kind (person, organization...)."""
    return grouped(
        (text(block.get("profile_kind")), id_text(entry.get("profile_id")))
        for block in dicts(blocks)
        if block.get("kind") == "profiles"
        for entry in dicts(block.get("profile_entries"))
    )


def profile_attributes(
    payload: dict[str, Any], identifiers: dict[str, list[str]]
) -> dict[str, Any]:
    """The whole payload, so nothing is lost, plus the identifiers and cities read from it."""
    return {**without_id(payload), "identifiers": identifiers, "cities": cities(payload)}


def without_id(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "id"}


def required_id(payload: dict[str, Any]) -> str:
    value = id_text(payload.get("id"))
    if value is None:
        raise MappingError("payload has no id")
    return value


PROFILE_MAPPERS: dict[str, Callable[[dict[str, Any]], MappedRecord]] = {
    "organization": map_organization,
    "person": map_person,
    "project": map_project,
    "event": map_event,
}


def map_record(
    kind: str,
    payload: Any,
    *,
    metadata: Iterable[Any] = (),
    blocks: Iterable[Any] = (),
) -> MappedRecord:
    """Map one detail payload with its metadata entries and, for a content, its blocks."""
    if not isinstance(payload, dict):
        raise MappingError("payload is not a JSON object")
    if kind == "content":
        record = map_content(payload, list(blocks))
    elif kind in PROFILE_MAPPERS:
        record = PROFILE_MAPPERS[kind](payload)
    else:
        raise MappingError(f"no mapper for entity kind {kind!r}")
    return replace(record, external_ids=metadata_ids(list(metadata)))
