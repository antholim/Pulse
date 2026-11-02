"""Raw payload archive: payloads are stored as received, under their tenant's key prefix.

Keys look like `tenants/<tenant_id>/runs/<sync_run_id>/<entity_kind>/<sha256>.json`.
Every backend checks on read that a key stays under the reading tenant's prefix.
"""

import hashlib
import json
import re
import uuid
from typing import Any, Protocol

from app.core.errors import PulseError

KEY_PATTERN = re.compile(
    r"tenants/(?P<tenant>[0-9a-f-]{36})/runs/[0-9a-f-]{36}/[a-z][a-z0-9_]*/[0-9a-f]{64}\.json"
)
ENTITY_KIND_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class ArchiveError(PulseError):
    """The raw payload archive could not store or return a payload."""


class ArchiveAccessError(ArchiveError):
    """A URI points outside the archive or outside the reading tenant's prefix."""

    status_code = 403
    code = "forbidden"


class ArchiveNotFoundError(ArchiveError):
    status_code = 404
    code = "not_found"


class ArchiveIntegrityError(ArchiveError):
    """An archived payload no longer matches the hash recorded for it."""


class PayloadArchive(Protocol):
    def put(self, key: str, data: bytes) -> str:
        """Store `data` under `key` and return its URI. Storing the same key again is a no-op."""
        ...

    def get(self, uri: str, tenant_id: uuid.UUID) -> bytes:
        """Return the bytes at `uri`, which must lie under `tenant_id`'s prefix."""
        ...


def canonical_json(payload: dict[str, Any]) -> bytes:
    """Encode a payload so equal payloads always give the same bytes."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def payload_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tenant_prefix(tenant_id: uuid.UUID) -> str:
    return f"tenants/{tenant_id}/"


def archive_key(tenant_id: uuid.UUID, sync_run_id: uuid.UUID, entity_kind: str, digest: str) -> str:
    if not ENTITY_KIND_PATTERN.fullmatch(entity_kind):
        raise ArchiveError(f"Invalid entity kind for the archive: {entity_kind!r}")
    return f"{tenant_prefix(tenant_id)}runs/{sync_run_id}/{entity_kind}/{digest}.json"


def check_key(key: str, tenant_id: uuid.UUID) -> str:
    """Return `key` if it is a well-formed archive key of `tenant_id`, else raise."""
    match = KEY_PATTERN.fullmatch(key)
    if match is None or match["tenant"] != str(tenant_id):
        raise ArchiveAccessError("Archived payload is outside this tenant's archive")
    return key
