"""Field-level differences between two versions of a source record."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.processing.content_hash import VOLATILE_KEYS, without_volatile

# Keys left out of the comparison at any depth, the same ones the content hash drops:
# they move when a record is fetched or saved again without its content changing.
IGNORED_FIELDS = VOLATILE_KEYS

# The columns compared, those the content hash covers. Bookkeeping columns (id, valid_from,
# valid_to, the run ids, content_hash, raw_record_id) are never compared.
COMPARED_FIELDS = (
    "kind",
    "workspace_id",
    "name_normalized",
    "domain",
    "linkedin",
    "external_ids",
    "attributes",
)

FieldChanges = dict[str, dict[str, Any]]


class Comparable(Protocol):
    """A MappedRecord or a SourceRecord version."""

    kind: str
    workspace_id: str | None
    name_normalized: str | None
    domain: str | None
    linkedin: str | None
    external_ids: dict
    attributes: dict


def snapshot(record: Comparable) -> dict[str, Any]:
    """The compared fields of a record, without the ignored ones."""
    return {name: without_volatile(getattr(record, name)) for name in COMPARED_FIELDS}


def field_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> FieldChanges:
    """Each changed leaf as `path: {"before": ..., "after": ...}`, paths sorted.

    Paths join keys with dots (`attributes.profile.canonical_url`). A list of objects with
    distinct `locale` keys is compared per locale (`attributes.contact[fr].phone`); any other
    list is one value.
    """
    changes: FieldChanges = {}
    for key in sorted(before.keys() | after.keys()):
        if key not in IGNORED_FIELDS:
            collect(before.get(key), after.get(key), key, changes)
    return changes


def collect(before: Any, after: Any, path: str, changes: FieldChanges) -> None:
    if before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            if key not in IGNORED_FIELDS:
                collect(before.get(key), after.get(key), f"{path}.{key}", changes)
        return
    old, new = by_locale(before), by_locale(after)
    if old is not None and new is not None:
        for locale in sorted(old.keys() | new.keys()):
            collect(old.get(locale), new.get(locale), f"{path}[{locale}]", changes)
        return
    changes[path] = {"before": before, "after": after}


def by_locale(value: Any) -> dict[str, Any] | None:
    """A per-locale list as locale to entry, or None when it is not one."""
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(item, dict) and isinstance(item.get("locale"), str) for item in value):
        return None
    keyed = {item["locale"]: item for item in value}
    return keyed if len(keyed) == len(value) else None


@dataclass
class SnapshotDiff:
    """External ids added and removed, and the field changes of those modified."""

    added: list[str] = field(default_factory=list)
    modified: dict[str, FieldChanges] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)


def diff_snapshots(
    before: Mapping[str, Mapping[str, Any]], after: Mapping[str, Mapping[str, Any]]
) -> SnapshotDiff:
    """Compare two states of a source, each a map of external id to snapshot."""
    diff = SnapshotDiff(
        added=sorted(after.keys() - before.keys()),
        removed=sorted(before.keys() - after.keys()),
    )
    for external_id in sorted(before.keys() & after.keys()):
        changes = field_changes(before[external_id], after[external_id])
        if changes:
            diff.modified[external_id] = changes
    return diff
