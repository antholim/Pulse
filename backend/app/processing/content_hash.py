"""Fingerprint a mapped record, so a sync can tell a changed record from an unchanged one."""

import hashlib
import json
from typing import Any

from app.ingestion.omerlo.mapping.mappers import MappedRecord

# Bookkeeping fields that can move without the record's content changing.
VOLATILE_KEYS = frozenset({"updated_at"})


def content_hash(record: MappedRecord) -> str:
    """SHA-256 of the normalized columns and the payload kept in `attributes`.

    Keys are sorted and volatile keys dropped at any depth, so two fetches of the same
    content hash the same.
    """
    content = {
        "kind": record.kind,
        "workspace_id": record.workspace_id,
        "name_normalized": record.name_normalized,
        "domain": record.domain,
        "linkedin": record.linkedin,
        "external_ids": record.external_ids,
        "attributes": without_volatile(record.attributes),
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: without_volatile(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [without_volatile(item) for item in value]
    return value
