import uuid

import pytest

from app.storage.archive import (
    ArchiveAccessError,
    ArchiveError,
    archive_key,
    canonical_json,
    check_key,
    payload_hash,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
RUN = uuid.UUID("33333333-3333-3333-3333-333333333333")
DIGEST = "a" * 64


def test_canonical_json_ignores_key_order_and_whitespace():
    # Arrange
    first = {"name": "Café", "tags": [1, 2], "nested": {"b": 1, "a": 2}}
    second = {"nested": {"a": 2, "b": 1}, "tags": [1, 2], "name": "Café"}

    # Act
    encoded = canonical_json(first)

    # Assert
    assert encoded == canonical_json(second)
    assert encoded == '{"name":"Café","nested":{"a":2,"b":1},"tags":[1,2]}'.encode()


def test_payload_hash_is_sha256_hex():
    # Act
    digest = payload_hash(b"{}")

    # Assert
    assert digest == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"


def test_canonical_json_rejects_values_json_cannot_hold():
    # Act / Assert
    with pytest.raises(ValueError):
        canonical_json({"score": float("nan")})


def test_archive_key_is_scoped_by_tenant_run_and_kind():
    # Act
    key = archive_key(TENANT, RUN, "organization", DIGEST)

    # Assert
    assert key == f"tenants/{TENANT}/runs/{RUN}/organization/{DIGEST}.json"
    assert check_key(key, TENANT) == key


@pytest.mark.parametrize("kind", ["../person", "Organization", "", "a/b"])
def test_archive_key_rejects_unsafe_entity_kinds(kind):
    # Act / Assert
    with pytest.raises(ArchiveError):
        archive_key(TENANT, RUN, kind, DIGEST)


@pytest.mark.parametrize(
    "key",
    [
        f"tenants/{OTHER_TENANT}/runs/{RUN}/organization/{DIGEST}.json",
        f"tenants/{TENANT}/runs/{RUN}/../../{OTHER_TENANT}/x/{DIGEST}.json",
        f"tenants/{TENANT}/../{OTHER_TENANT}/runs/{RUN}/organization/{DIGEST}.json",
        f"/tenants/{TENANT}/runs/{RUN}/organization/{DIGEST}.json",
        f"tenants/{TENANT}/runs/{RUN}/organization/secret.txt",
    ],
)
def test_check_key_rejects_other_tenants_and_traversal(key):
    # Act / Assert
    with pytest.raises(ArchiveAccessError):
        check_key(key, TENANT)
