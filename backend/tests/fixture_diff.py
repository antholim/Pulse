"""Read synthetic fixtures and their expected diff in the terms of normalized source records.

The mutation script describes changes in fixture terms (`organizations`, `contact[fr].email`,
`metadata.crm_id`); change detection works on mapped records (`organization`,
`attributes.contact[fr].email`, `external_ids.crm_id`). These helpers translate between the two.
"""

from dataclasses import dataclass, field
from typing import Any

from app.ingestion.omerlo.mapping.mappers import MappedRecord, map_record
from synthetic.omerlo_fixtures import TenantData

# Fixture files stored as source records, and their entity kind. Workspaces, categories and
# event sessions are not source records, so their changes are not expected.
KINDS = {
    "organizations": "organization",
    "people": "person",
    "projects": "project",
    "events": "event",
}

# Contact fields and the identifiers the mapper derives from them.
IDENTIFIERS = {
    "email": {"attributes.identifiers.emails"},
    "phone": {"attributes.identifiers.phones"},
    "website": {"attributes.identifiers.domains", "domain"},
    "linkedin": {"attributes.identifiers.linkedin", "linkedin"},
}
PERSON_IDENTIFIERS = {key: IDENTIFIERS[key] for key in ("email", "linkedin")}
NAMES = {"organization": ("name",), "person": ("first_name", "last_name")}

Key = tuple[str, str]


@dataclass
class Expected:
    """An expected diff of one tenant, keyed by (entity kind, external id)."""

    added: set[Key] = field(default_factory=set)
    modified: dict[Key, list[dict[str, Any]]] = field(default_factory=dict)
    removed: set[Key] = field(default_factory=set)


def mapped_records(data: TenantData, *, updated_after: str | None = None) -> list[MappedRecord]:
    """The tenant's records mapped as a sync would; only those updated after a time if given."""
    return [
        map_record(kind, payload, metadata=data.metadata.get(payload["id"], []))
        for name, kind in KINDS.items()
        for payload in data.resources[name]
        if updated_after is None or payload["updated_at"] > updated_after
    ]


def expected(tenant_diff: dict[str, list]) -> Expected:
    """The part of one tenant's expected diff that change detection can see."""
    result = Expected()
    for entry in tenant_diff["added"]:
        if entry["kind"] in KINDS:
            result.added.add((KINDS[entry["kind"]], entry["id"]))
    for entry in tenant_diff["modified"]:
        if entry["kind"] in KINDS:
            result.modified[(KINDS[entry["kind"]], entry["id"])] = entry["changes"]
    for entry in tenant_diff["removed"]:
        if entry["kind"] in KINDS:
            result.removed.add((KINDS[entry["kind"]], entry["id"]))
    return result


def split(path: str) -> tuple[str, str, str]:
    """`contact[fr].email` as ("contact", "fr", "email"); `name` as ("name", "", "")."""
    head, _, leaf = path.partition(".")
    section, _, locale = head.removesuffix("]").partition("[")
    return section, locale, leaf


def normalized_paths(kind: str, path: str) -> set[str]:
    """The changed_fields paths a fixture change can show up as."""
    if path.startswith("metadata."):
        return {"external_ids." + path.removeprefix("metadata.")}
    section, _, leaf = split(path)
    direct = direct_path(kind, path)
    paths = {direct} if direct else set()
    if section == "contact":
        identifiers = PERSON_IDENTIFIERS if kind == "person" else IDENTIFIERS
        paths |= identifiers.get(leaf, set())
    if path in NAMES.get(kind, ()):
        paths.add("name_normalized")
    return paths


def direct_path(kind: str, path: str) -> str | None:
    """The path holding the fixture value as is; the person mapper keeps only some fields."""
    if path.startswith("metadata."):
        return "external_ids." + path.removeprefix("metadata.")
    if kind != "person" or path in NAMES["person"]:
        return f"attributes.{path}"
    section, locale, leaf = split(path)
    if section == "locales" and leaf == "job_title":
        return f"attributes.job_titles.{locale}"
    return None


def direct_change(kind: str, change: dict[str, Any]) -> tuple[str, Any, Any] | None:
    """The changed_fields entry expected for a fixture change, when one holds it as is."""
    path, before, after = change["field"], change["before"], change["after"]
    direct = direct_path(kind, path)
    if direct is None:
        return None
    if path.startswith("metadata."):
        # Metadata values are grouped by key into lists.
        return direct, wrap(before), wrap(after)
    return direct, before, after


def wrap(value: Any) -> list[Any] | None:
    return None if value is None else [value]


def assert_fields_correspond(kind: str, changes: list[dict], fields: dict[str, dict]) -> None:
    """The changed fields are exactly what the fixture changes explain, with their values."""
    allowed = set().union(*(normalized_paths(kind, change["field"]) for change in changes))
    unexplained = set(fields) - allowed
    assert not unexplained, f"changed fields no fixture change explains: {unexplained}"
    for change in changes:
        paths = normalized_paths(kind, change["field"])
        assert paths & set(fields), f"{change['field']} changed but none of {paths} did"
        direct = direct_change(kind, change)
        if direct:
            path, before, after = direct
            assert fields[path] == {"before": before, "after": after}, path
